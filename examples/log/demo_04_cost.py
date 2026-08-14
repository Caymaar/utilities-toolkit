"""Ce que coûtent ces helpers, éteints puis allumés.

    python examples/log/demo_04_cost.py

Deux choses à vérifier :

1. **Éteint, un appel ne construit rien.** Le seul coût est le test de niveau,
   quelques centaines de nanosecondes. C'est ce qui permet de laisser les
   appels en place dans du code de production. Le script échoue si ce coût
   dépasse 2 µs.

2. **`spark()` contre `plot_line()`.** Deux ordres de grandeur d'écart. C'est
   la raison pour laquelle la sparkline est le premier réflexe et plotext le
   second.
"""

import logging
import math
import sys
from time import perf_counter

from utilities.log import DATAFRAME, PLOT, log_frame, spark
from utilities.log.plots import plot_line

SEUIL_ETEINT_US = 2.0

YS = [100 + math.sin(i / 10) * 5 for i in range(300)]


def bench(fn, n, repeats=3):
    """µs par appel, meilleur run."""
    best = float("inf")
    for _ in range(repeats):
        t0 = perf_counter()
        for _ in range(n):
            fn()
        best = min(best, perf_counter() - t0)
    return best / n * 1e6


# Seule démo à ne PAS passer par LoggingConfigurator, et c'est délibéré : on
# mesure ici le coût de **construction** du rendu, pas celui de l'écriture sur
# un terminal. Un handler Rich ajouterait quelques millisecondes d'affichage
# par appel, et cinquante graphes déroulés à l'écran par-dessus le marché. Les
# deux loggers ci-dessous sont donc des instruments de mesure, pas du logging.

def logger_muet():
    """Niveau au-dessus de DATAFRAME et de PLOT : rien ne doit être construit."""
    log = logging.getLogger("bench.muet")
    log.handlers = []
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def logger_bavard():
    """Niveau ouvert, mais sortie jetée : on isole le rendu de l'affichage."""
    log = logging.getLogger("bench.bavard")
    log.handlers = [logging.NullHandler()]
    log.setLevel(PLOT)
    log.propagate = False
    return log


def main():
    muet, bavard = logger_muet(), logger_bavard()

    try:
        import polars as pl
        colonne = YS * 17
        df = pl.DataFrame({"i": list(range(len(colonne))), "x": colonne})
    except ImportError:
        df = None

    print("=" * 62)
    print("NIVEAU ÉTEINT — rien ne doit être construit")
    print("=" * 62)
    off_plot = bench(lambda: plot_line(muet, YS, title="NAV"), 200_000)
    print("  plot_line()      %8.3f us" % off_plot)
    off_frame = None
    if df is not None:
        off_frame = bench(lambda: log_frame(muet, df, mode="describe"), 200_000)
        print("  log_frame()      %8.3f us" % off_frame)

    pire = max(x for x in (off_plot, off_frame) if x is not None)
    if pire > SEUIL_ETEINT_US:
        print("\n  ALERTE : %.3f us éteint (seuil %.1f us)." % (pire, SEUIL_ETEINT_US))
        print("  Quelque chose est construit avant le test de niveau.")
        return 1
    print("\n  OK : sous les %.1f us, rien n'est construit." % SEUIL_ETEINT_US)

    print("\n" + "=" * 62)
    print("NIVEAU ALLUMÉ — le coût réel du rendu")
    print("=" * 62)
    t_spark = bench(lambda: spark(YS), 20_000)
    print("  spark(300 pts)   %8.1f us" % t_spark)
    t_plot = bench(lambda: plot_line(bavard, YS, title="NAV"), 50)
    print("  plot_line()      %8.1f us   -> %.0fx plus cher que spark" % (t_plot, t_plot / t_spark))
    if df is not None:
        t_head = bench(lambda: log_frame(bavard, df, mode="head", n=10), 2_000)
        t_desc = bench(lambda: log_frame(bavard, df, mode="describe"), 500)
        print("  log_frame head   %8.1f us" % t_head)
        print("  log_frame descr. %8.1f us" % t_desc)

    print("\nRègle : une sparkline dans une boucle, un graphe une fois par run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
