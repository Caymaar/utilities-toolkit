"""Restitution du registry : texte pur, table Rich, dictionnaires.

``rich`` n'est jamais importé au niveau module — uniquement dans la fonction
qui en a besoin, pour que le coût d'import de :mod:`utilities.probe` reste
négligeable quand personne ne rend de table.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from utilities.probe.core import TIER, Stat, _reset_hooks, snapshot

__all__ = ["report", "to_dicts"]

_SORT_KEYS = {
    "wall": lambda s: s.wall_s,
    "self": lambda s: s.self_s,
    "wait": lambda s: s.wait_s,
    "n": lambda s: float(s.n),
}

_COLUMNS = ("label", "n", "wall", "self", "wait", "mean", "p95")

#: Nombre total d'appels mesurés au moment du dernier rendu, pour que le
#: rendu automatique de fin de process ne double pas un rendu explicite.
_last_reported_calls = -1


def _sorted_rows(sort: str) -> List[Stat]:
    try:
        key = _SORT_KEYS[sort]
    except KeyError:
        raise ValueError(
            "sort=%r inconnu, attendu l'un de %s" % (sort, sorted(_SORT_KEYS))
        ) from None
    return sorted(snapshot(), key=key, reverse=True)


def _fmt_s(v: float) -> str:
    # Un wait légèrement négatif (résolution des deux horloges) s'affiche 0.000s
    # plutôt que -0.000s, qui fait douter d'un bug qui n'existe pas.
    return "%.3fs" % (v if abs(v) >= 5e-4 else 0.0)


def _fmt_ms(v: float) -> str:
    return "%.2fms" % (v * 1e3)


def _fmt_mib(v_kib: float) -> str:
    mib = v_kib / 1024.0
    return "%.1fMiB" % (mib if abs(mib) >= 0.05 else 0.0)


def _text_table(rows: List[Stat], mem: bool) -> str:
    head = "%-34s%6s%11s%11s%11s%12s%12s" % _COLUMNS
    if mem:
        head += "%12s" % "alloc"
    lines = [head, "-" * len(head)]
    for s in rows:
        line = "%-34s%6d%11s%11s%11s%12s%12s" % (
            s.label[:34], s.n,
            _fmt_s(s.wall_s), _fmt_s(s.self_s), _fmt_s(s.wait_s),
            _fmt_ms(s.mean_s), _fmt_ms(s.quantile(0.95)),
        )
        if mem:
            line += "%12s" % _fmt_mib(s.alloc_kib)
        lines.append(line)
    return "\n".join(lines)


def _rich_print(rows: List[Stat], mem: bool, sort: str) -> bool:
    """Rend une table Rich. Renvoie False si Rich est indisponible."""
    try:
        from rich.console import Console
        from rich.table import Table

        from utilities.log.setup import LoggingConfigurator
    except Exception:  # pragma: no cover - rich est une dépendance obligatoire
        return False

    table = Table(
        title="utilities.probe — tier %d, sorted by %s" % (TIER, sort),
        title_justify="left",
        header_style="bold",
    )
    table.add_column("label", overflow="fold")
    for name in ("n", "wall", "self", "wait", "mean", "p95"):
        table.add_column(name, justify="right")
    if mem:
        table.add_column("alloc", justify="right")

    for s in rows:
        cells = [
            s.label, str(s.n),
            _fmt_s(s.wall_s), _fmt_s(s.self_s), _fmt_s(s.wait_s),
            _fmt_ms(s.mean_s), _fmt_ms(s.quantile(0.95)),
        ]
        if mem:
            cells.append(_fmt_mib(s.alloc_kib))
        table.add_row(*cells)

    # Réutilise la console du logger si l'application en a configuré une.
    console = LoggingConfigurator.get_console() or Console(stderr=True)
    console.print(table)
    return True


def report(
    stream: Optional[Any] = None,
    *,
    sort: str = "wall",
    rich: Optional[bool] = None,
) -> str:
    """Rend la table agrégée. Renvoie **toujours** la version texte.

    - ``stream`` fourni : le texte pur y est écrit (``rich`` est ignoré) ;
    - ``stream=None`` et ``rich`` non-``False`` : table Rich sur la console
      partagée du logger, ou sur stderr ;
    - ``stream=None`` et ``rich=False`` : rien n'est imprimé, seul le texte est
      renvoyé.

    ``sort`` vaut ``"wall"``, ``"self"``, ``"wait"`` ou ``"n"``. Trier par
    ``self`` donne le vrai classement des coupables ; trier par ``wait``
    répond à « est-ce que j'attends une machine d'en face ? ».

    **``sort="self"`` n'est pas lisible sous ``asyncio.gather``.** Chaque
    ``Task`` travaille sur une copie du contexte, donc le temps d'un enfant
    lancé dans une autre tâche ne se retranche pas de son parent : parent et
    enfants revendiquent alors le même temps, et la somme des ``self`` dépasse
    la durée du programme. Sur du code concurrent, lire ``wall`` et ``wait``.
    """
    global _last_reported_calls

    rows = _sorted_rows(sort)
    if not rows:
        return ""

    mem = TIER >= 2
    text = _text_table(rows, mem)
    _last_reported_calls = sum(s.n for s in rows)

    if stream is not None:
        print(text, file=stream)
    elif rich is not False:
        if not _rich_print(rows, mem, sort):
            print(text, file=sys.stderr)

    return text


def to_dicts(*, sort: str = "wall") -> List[Dict[str, Any]]:
    """Le registry sous forme de lignes sérialisables (JSON, CSV, DataFrame)."""
    return [
        {
            "label": s.label,
            "n": s.n,
            "wall_s": s.wall_s,
            "cpu_s": s.cpu_s,
            "self_s": s.self_s,
            "wait_s": s.wait_s,
            "mean_s": s.mean_s,
            "p95_s": s.quantile(0.95),
            "alloc_kib": s.alloc_kib,
        }
        for s in _sorted_rows(sort)
    ]


def _forget_last_report() -> None:
    """Oublie le dernier rendu. Branché sur :func:`utilities.probe.reset`.

    Sans ça, un ``reset()`` suivi du **même nombre exact** de mesures ferait
    croire au rendu de fin de process qu'il a déjà tout imprimé, et la table
    ne sortirait jamais.
    """
    global _last_reported_calls
    _last_reported_calls = -1


_reset_hooks.append(_forget_last_report)


def _report_at_exit() -> None:
    """Rendu de fin de process, silencieux s'il n'y a rien de neuf à dire."""
    rows = snapshot()
    if not rows:
        return
    if sum(s.n for s in rows) == _last_reported_calls:
        return  # déjà rendu explicitement, et rien mesuré depuis
    report()
