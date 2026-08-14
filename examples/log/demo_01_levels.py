"""Niveau et namespace : deux interrupteurs, et pourquoi il en faut deux.

    python examples/log/demo_01_levels.py

Un niveau de log est **ordonné**. `PLOT` (6) est sous `DATAFRAME` (8), donc
régler un logger sur `PLOT` émet forcément aussi les DataFrames. Il est
impossible d'avoir les graphes **sans** les DataFrames avec le seul niveau.

C'est une limite du mécanisme, pas un défaut d'implémentation. D'où le second
interrupteur : le **namespace**. Chaque famille de sortie va dans son propre
logger (`app.data`, `app.plot`), réglable indépendamment.

Ce qu'il faut voir : les quatre premières passes ajoutent cumulativement, et la
cinquième obtient ce qu'aucun niveau ne sait donner — les graphes seuls.
"""

import logging
import random

from utilities import LoggingConfigurator
from utilities.log import DATAFRAME, PLOT, log_frame, spark
from utilities.log.plots import plot_line

# Le logging du package, configuré une fois pour tout le script. `configure()`
# est un one-shot : le second appel ne fait rien. On l'ouvre donc au niveau le
# plus bas, et on joue ensuite sur le niveau de **chaque logger** — c'est le
# mécanisme réel, et c'est ce que la démo veut montrer.
LoggingConfigurator.configure(level="PLOT", console_width=120)

random.seed(7)
NAV = [100.0]
for _ in range(299):
    NAV.append(NAV[-1] * (1 + random.gauss(0.0004, 0.006)))


def emettre():
    """Le même travail à chaque passe. Seule la configuration change."""
    racine = logging.getLogger("app")
    data = logging.getLogger("app.data")
    plot = logging.getLogger("app.plot")

    racine.info("nav n=%d %s [%.2f, %.2f]", len(NAV), spark(NAV), min(NAV), max(NAV))
    racine.debug("détail de calcul que seul DEBUG montre")

    try:
        import polars as pl
        df = pl.DataFrame({"jour": list(range(len(NAV))), "nav": NAV})
    except ImportError:
        df = None
    if df is not None:
        log_frame(data, df, mode="head", n=3, label="nav")

    plot_line(plot, NAV, title="NAV")


def configurer(niveau_racine, niveau_plot=None):
    """Règle les niveaux. Les handlers, eux, viennent de LoggingConfigurator.

    Un logger à NOTSET hérite du niveau de son parent : c'est ce qui permet de
    piloter `app.data` et `app.plot` depuis `app`, puis d'en détacher un seul.
    """
    for nom in ("app.data", "app.plot"):
        logging.getLogger(nom).setLevel(logging.NOTSET)
    logging.getLogger("app").setLevel(niveau_racine)
    if niveau_plot is not None:
        logging.getLogger("app.plot").setLevel(niveau_plot)


PASSES = (
    ("INFO", logging.INFO, None,
     "la sparkline seule — une ligne, greppable, lisible sur un téléphone"),
    ("DEBUG", logging.DEBUG, None,
     "les lignes de debug s'ajoutent, toujours ni frame ni graphe"),
    ("DATAFRAME", DATAFRAME, None,
     "le DataFrame apparaît, le graphe non : DATAFRAME (8) est au-dessus de PLOT (6)"),
    ("PLOT", PLOT, None,
     "tout, y compris le graphe — le niveau le plus bas prend forcément tout"),
    ("INFO + namespace app.plot à PLOT", logging.INFO, PLOT,
     "les graphes SANS les DataFrames : impossible avec le seul niveau"),
)


def main():
    for titre, niveau, niveau_plot, commentaire in PASSES:
        print("\n" + "=" * 78)
        print("%s\n  -> %s" % (titre, commentaire))
        print("=" * 78)
        configurer(niveau, niveau_plot)
        emettre()


if __name__ == "__main__":
    main()
