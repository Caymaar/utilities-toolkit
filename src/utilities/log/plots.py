"""Graphes en caractères terminal, logués au niveau ``PLOT`` (6).

Pour un batch dont le log se lit en SSH : pas d'image, pas de fichier, pas de
matplotlib (2.6 s d'import contre 15 ms pour plotext, et de toute façon une
image ne se lit pas dans un ``tail -f``).

**Avant d'appeler ces helpers, regardez** :func:`utilities.log.frames.spark` :
sur 300 points, une sparkline coûte ~12 µs contre ~1.7 ms pour un graphe
plotext, soit **145 fois moins**, tient sur une ligne et reste greppable. Elle
répond à la question qu'on se pose vraiment neuf fois sur dix. plotext est le
second réflexe, quand il faut voir une forme.

``plotext`` est une dépendance **optionnelle** :

    pip install "utilities-toolkit[plot]"

Rien n'est construit si le niveau est éteint : c'est la seule chose que coûte
un appel dans ce cas.
"""

from __future__ import annotations

import threading
from typing import Any, Optional, Sequence

from utilities.log.levels import PLOT

__all__ = ["plot_line", "plot_scatter", "plot_hist", "plot_bar"]

#: Taille figée. Sans ça, plotext interroge le terminal et la sortie change
#: selon qu'on lit la console ou un fichier de log.
WIDTH = 72
HEIGHT = 15

#: plotext est un module à **état global** : `clf()`, `plot()` et `build()`
#: travaillent sur une figure unique et partagée. Deux threads qui tracent en
#: même temps produisent un graphe mélangé.
_lock = threading.Lock()

_MESSAGE = (
    "plotext n'est pas installé : les helpers plot_* en ont besoin.\n"
    '  pip install "utilities-toolkit[plot]"   ou   uv add "utilities-toolkit[plot]"\n'
    "Sans lui, utilities.log.frames.spark() rend une sparkline sans dépendance."
)


def _require():
    """Importe plotext, ou lève un message actionnable plutôt qu'un ImportError brut."""
    try:
        import plotext
    except ImportError as exc:
        raise RuntimeError(_MESSAGE) from exc
    return plotext


def _emit(log: Any, title: str, draw) -> None:
    """Prépare la figure, la construit sous verrou, et logue le résultat."""
    plt = _require()
    with _lock:
        plt.clf()
        plt.plotsize(WIDTH, HEIGHT)
        plt.theme("clear")
        draw(plt)
        if title:
            plt.title(title)
        rendu = plt.build()
    # Formatage paresseux : le rendu est déjà construit, mais le message final
    # n'est assemblé que si un handler traite l'enregistrement.
    #
    # markup=False : un graphe est plein de crochets — `┤`, les bornes d'axes,
    # un titre qui contient `[%]`. Un RichHandler en `markup=True` les
    # interpréterait, et lèverait sur le premier qui ressemble à une balise.
    log.log(PLOT, "%s\n%s", title or "(sans titre)", rendu,
            extra={"markup": False, "highlighter": None})


def plot_line(log: Any, ys: Sequence[float], *, title: str = "",
              x: Optional[Sequence[float]] = None) -> None:
    """Courbe. Le tracé de série temporelle, NAV en tête."""
    if not log.isEnabledFor(PLOT):
        return
    _emit(log, title, lambda plt: plt.plot(list(x), list(ys)) if x is not None
          else plt.plot(list(ys)))


def plot_scatter(log: Any, xs: Sequence[float], ys: Sequence[float], *,
                 title: str = "") -> None:
    """Nuage de points. Résidus contre valeurs ajustées, corrélations."""
    if not log.isEnabledFor(PLOT):
        return
    _emit(log, title, lambda plt: plt.scatter(list(xs), list(ys)))


def plot_hist(log: Any, values: Sequence[float], *, bins: int = 30,
              title: str = "") -> None:
    """Distribution. Ce que `spark()` suggère, en plus lisible."""
    if not log.isEnabledFor(PLOT):
        return
    _emit(log, title, lambda plt: plt.hist(list(values), bins))


def plot_bar(log: Any, labels: Sequence[Any], values: Sequence[float], *,
             title: str = "") -> None:
    """Barres. Exposition par secteur, comptages par catégorie."""
    if not log.isEnabledFor(PLOT):
        return
    _emit(log, title, lambda plt: plt.bar([str(o) for o in labels], list(values)))
