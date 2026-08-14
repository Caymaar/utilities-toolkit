"""Cœur du module : lecture du tier, modèle de mesure, probe et probed.

Voir :mod:`utilities.probe` pour la documentation d'usage.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import math
import os
import threading
import time
import tracemalloc
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast

from utilities.log.levels import PERF

__all__ = [
    "PERF",
    "TIER",
    "ENABLED",
    "Probe",
    "Stat",
    "probe",
    "probed",
    "registry",
    "snapshot",
    "reset",
]

#: Le module ne configure **jamais** le logging de son hôte : pas de handler,
#: pas de niveau posé. Il se contente d'émettre si quelqu'un écoute.
_log = logging.getLogger("utilities.probe")

_TIERS = {
    "": 0, "0": 0, "off": 0, "false": 0, "no": 0,
    "1": 1, "time": 1, "on": 1, "true": 1, "yes": 1,
    "2": 2, "mem": 2, "memory": 2, "full": 2,
}


def _read_tier() -> int:
    return _TIERS.get(os.environ.get("PROBE_TIER", "").strip().lower(), 0)


#: 0 = off, 1 = temps, 2 = temps + mémoire.
#:
#: **Figé à l'import**, et c'est le compromis fondamental du module : c'est ce
#: qui permet à :func:`probed` de ne poser aucun wrapper en tier 0. Un flag
#: relu à chaud imposerait un test par appel (~200-400 ns), ce qui ruinerait la
#: garantie de coût nul.
TIER = _read_tier()
ENABLED = TIER > 0

#: Nombre d'échantillons conservés par label pour le calcul des quantiles.
#: Au-delà, on continue d'agréger les totaux mais on cesse d'accumuler.
_MAX_SAMPLES = 20_000

_MEM = TIER >= 2

# Résolus une fois : évite deux lookups d'attribut par mesure.
_perf_counter = time.perf_counter
_traced = tracemalloc.get_traced_memory

#: Temps CPU **du thread courant**, pas du process.
#:
#: Avec ``process_time``, un bloc qui dort pendant que deux autres threads
#: calculent affiche ``cpu ≈ wall`` donc ``wait ≈ 0`` : l'inverse exact du
#: diagnostic, et la métrique centrale du module devient trompeuse dès qu'un
#: programme a plus d'un thread. ``thread_time`` ne compte que le CPU brûlé par
#: le thread qui mesure.
#:
#: Bonus mesuré : 107 ns contre 209 ns par appel, soit deux fois moins cher.
#: Repli sur ``process_time`` sur les plateformes sans horloge par thread.
_cpu_time = getattr(time, "thread_time", time.process_time)


# --------------------------------------------------------------------------- #
# Modèle
# --------------------------------------------------------------------------- #


class Probe:
    """Mesure d'un bloc unique, et son propre context manager.

    Une seule allocation par bloc mesuré : l'objet porte à la fois l'état de
    mesure et le résultat. ``__slots__`` plutôt que ``dataclass`` — le package
    cible Python 3.9, où ``dataclass(slots=True)`` n'existe pas.
    """

    __slots__ = (
        "label", "wall_s", "cpu_s", "self_s", "alloc_kib",
        "_t0", "_c0", "_m0", "_token",
    )

    def __init__(
        self,
        label: str,
        wall_s: float = 0.0,
        cpu_s: float = 0.0,
        self_s: float = 0.0,
        alloc_kib: float = 0.0,
    ) -> None:
        self.label = label
        #: Temps écoulé, horloge murale.
        self.wall_s = wall_s
        #: Temps CPU **du thread** pendant le bloc (utilisateur + système). Le
        #: travail confié à d'autres threads n'y figure pas : c'est ce qui rend
        #: ``wait_s`` lisible dans un programme multithread.
        self.cpu_s = cpu_s
        #: ``wall_s`` moins le temps des probes enfants — l'équivalent du
        #: ``tottime`` de cProfile.
        self.self_s = self_s
        #: Delta **net retenu** de mémoire tracée (tier 2 uniquement) : ce que
        #: le bloc a alloué *et gardé*, pas le volume total alloué. Un bloc qui
        #: alloue 1 Gio puis le libère affiche ~0.
        self.alloc_kib = alloc_kib

    @property
    def wait_s(self) -> float:
        """Temps hors CPU : I/O, réseau, verrou, attente du GIL.

        C'est la métrique qui décide de la suite des travaux : proche de zéro,
        le problème est algorithmique ; proche de ``wall_s``, on attend une
        machine d'en face.
        """
        return self.wall_s - self.cpu_s

    def __enter__(self) -> "Probe":
        self._token = _child_wall.set(0.0)
        self._m0 = _traced()[0] if _MEM else 0
        self._c0 = _cpu_time()
        self._t0 = _perf_counter()
        return self

    def __exit__(self, *exc: Any) -> bool:
        wall = _perf_counter() - self._t0
        self.cpu_s = _cpu_time() - self._c0
        self.wall_s = wall
        if _MEM:
            self.alloc_kib = (_traced()[0] - self._m0) / 1024.0

        # Ce que les enfants ont consommé pendant ce bloc.
        self.self_s = wall - _child_wall.get()

        try:
            _child_wall.reset(self._token)
        except ValueError:
            # Entrée et sortie de part et d'autre d'une frontière de contexte
            # (bloc traversant un await sur une autre task). L'imputation au
            # parent est perdue, la mesure du bloc reste juste.
            pass
        _child_wall.set(_child_wall.get() + wall)

        with _registry_lock:
            stat = registry.get(self.label)
            if stat is None:
                stat = registry[self.label] = Stat(self.label)
            stat.add(self)

        if _log.isEnabledFor(PERF):
            # Formatage paresseux via %-args : rien n'est construit si aucun
            # handler ne traite l'enregistrement.
            _log.log(
                PERF,
                "%-28s wall=%7.3fs cpu=%7.3fs wait=%7.3fs self=%7.3fs",
                self.label, self.wall_s, self.cpu_s, self.wait_s, self.self_s,
                # markup=False : un label est une chaîne libre, et un
                # RichHandler en markup=True lèverait sur un label contenant
                # quelque chose comme `étape[2]`.
                extra={"probe": self, "markup": False},
            )
        return False

    def __repr__(self) -> str:
        return "Probe(%r, wall_s=%.6f, cpu_s=%.6f, self_s=%.6f)" % (
            self.label, self.wall_s, self.cpu_s, self.self_s,
        )


class Stat:
    """Agrégat de tous les appels portant le même label."""

    __slots__ = ("label", "n", "wall_s", "cpu_s", "self_s", "alloc_kib", "_samples")

    def __init__(self, label: str) -> None:
        self.label = label
        self.n = 0
        self.wall_s = 0.0
        self.cpu_s = 0.0
        self.self_s = 0.0
        self.alloc_kib = 0.0
        self._samples: List[float] = []

    def add(self, p: Probe) -> None:
        """Agrège une mesure. **À appeler sous** :data:`_registry_lock`.

        ``self.n += 1`` est un LOAD/ADD/STORE non atomique, y compris sous GIL :
        un changement de thread entre les trois pas d'un incrément fait perdre
        la mesure de l'autre thread.
        """
        self.n += 1
        self.wall_s += p.wall_s
        self.cpu_s += p.cpu_s
        self.self_s += p.self_s
        self.alloc_kib += p.alloc_kib
        if len(self._samples) < _MAX_SAMPLES:
            self._samples.append(p.wall_s)

    @property
    def wait_s(self) -> float:
        return self.wall_s - self.cpu_s

    @property
    def mean_s(self) -> float:
        return self.wall_s / self.n if self.n else 0.0

    def quantile(self, q: float) -> float:
        """Quantile des ``wall_s``, méthode du rang le plus proche."""
        if not self._samples:
            return 0.0
        ordered = sorted(self._samples)
        idx = int(math.ceil(q * len(ordered))) - 1
        return ordered[min(len(ordered) - 1, max(0, idx))]

    def __repr__(self) -> str:
        return "Stat(%r, n=%d, wall_s=%.6f, self_s=%.6f)" % (
            self.label, self.n, self.wall_s, self.self_s,
        )


#: Agrégats par label, alimentés à la sortie de chaque bloc mesuré.
registry: Dict[str, Stat] = {}

#: Protège le registry **et** les compteurs des :class:`Stat`.
#:
#: Deux threads qui mesurent le même label se marchent dessus autrement : la
#: création du ``Stat`` est un get-puis-set non atomique (un des deux objets est
#: perdu), et chaque ``+=`` de :meth:`Stat.add` est un LOAD/ADD/STORE
#: interruptible. Les incréments manquent silencieusement, et d'autant plus que
#: le label est chaud.
#:
#: Coût mesuré : +69 ns par mesure, sur les ~1400 ns d'une probe en tier 1.
_registry_lock = threading.Lock()


def snapshot() -> List[Stat]:
    """Copie de la liste des agrégats, prise sous verrou.

    Itérer directement sur ``registry`` pendant qu'un autre thread mesure lève
    ``RuntimeError: dictionary changed size during iteration``.
    """
    with _registry_lock:
        return list(registry.values())

#: Temps cumulé des probes enfants du bloc courant. ``contextvars`` plutôt que
#: ``threading.local`` : correct en asyncio **et** isolé par thread.
_child_wall: "contextvars.ContextVar[float]" = contextvars.ContextVar(
    "utilities_probe_child_wall", default=0.0
)


# --------------------------------------------------------------------------- #
# Chemin désactivé
# --------------------------------------------------------------------------- #


class _NullCtx:
    """No-op sans allocation.

    Un ``@contextmanager`` générateur, même vide, coûte ~1.2 µs par
    entrée/sortie (création du générateur, machinerie ``throw``). Une classe à
    ``__slots__`` dont l'instance est un singleton tombe à ~200 ns.
    """

    __slots__ = ()

    def __enter__(self) -> Probe:
        return _DUMMY

    def __exit__(self, *exc: Any) -> bool:
        return False


#: Probe partagée renvoyée en tier 0. Ses champs valent 0.0 et n'ont pas de
#: sens : en tier 0, on ne mesure rien.
_DUMMY = Probe("")
_NULL = _NullCtx()


def _probe_off(label: str) -> _NullCtx:
    return _NULL


#: ``probe(label)`` — résolu à l'import. En tier 0 : un singleton, aucune
#: allocation. Sinon la classe :class:`Probe` elle-même, qui est son propre
#: context manager.
probe = cast(Callable[[str], Any], Probe if ENABLED else _probe_off)


# --------------------------------------------------------------------------- #
# Décorateur
# --------------------------------------------------------------------------- #

F = TypeVar("F", bound=Callable[..., Any])

_CO_COROUTINE = 0x80


def probed(label: Optional[str] = None) -> Callable[[F], F]:
    """Décore une fonction ou une coroutine pour la mesurer.

    En tier 0, renvoie la fonction **inchangée** : aucun wrapper n'est posé,
    donc rien n'est payé à l'exécution — pas même un test de flag.

    Le label par défaut est ``module.qualname``.
    """

    def deco(fn: F) -> F:
        if not ENABLED:
            return fn

        name = label or "%s.%s" % (fn.__module__, fn.__qualname__)

        # Déballe les décorateurs déjà posés pour voir la vraie fonction, sans
        # importer `inspect` (~1 ms d'import pour un seul test).
        target: Any = fn
        while hasattr(target, "__wrapped__"):
            target = target.__wrapped__
        code = getattr(target, "__code__", None)

        if code is not None and code.co_flags & _CO_COROUTINE:

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                with Probe(name):
                    return await fn(*args, **kwargs)

            return cast(F, awrapper)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with Probe(name):
                return fn(*args, **kwargs)

        return cast(F, wrapper)

    return deco


#: Appelés par :func:`reset`. Sert à la restitution, qui mémorise le nombre
#: d'appels déjà rendus pour ne pas imprimer deux fois la même table : sans ce
#: crochet, un `reset()` suivi du même nombre exact de mesures ferait croire au
#: rendu de fin de process qu'il n'y a rien de neuf, et il n'imprimerait rien.
_reset_hooks: List[Callable[[], None]] = []


def reset() -> None:
    """Vide le registry. Les mesures déjà rendues ne sont pas affectées."""
    with _registry_lock:
        registry.clear()
    for crochet in _reset_hooks:
        crochet()


if _MEM and not tracemalloc.is_tracing():
    # 1 frame : on n'exploite aucune traceback, en demander 25 revient à payer
    # 25 fois le coût de capture pour rien.
    tracemalloc.start(1)
