"""Les quatre tracés, sur des données de forme reconnaissable.

    python examples/log/demo_03_plots.py

Ce qu'il faut voir : à 72×15 caractères, une tendance, une corrélation, une loi
bimodale et sept catégories restent parfaitement lisibles. Et où ça ne suffit
plus — un nuage dense se transforme en pâté, une distribution à queue longue
écrase tout le reste.

Chaque tracé est précédé de sa sparkline, pour comparer ce que coûte chacun :
~12 µs contre ~1.7 ms sur 300 points. Lancez `demo_04_cost.py` pour les chiffres
de votre machine.
"""

import logging
import random

from utilities import LoggingConfigurator
from utilities.log import PLOT, spark
from utilities.log.plots import plot_bar, plot_hist, plot_line, plot_scatter

random.seed(11)


def configurer():
    """Le logging du package.

    `console_width=120` n'est pas décoratif : un graphe fait 72 colonnes, et
    RichHandler lui prend ~29 colonnes de gouttière plus ~15 pour le chemin à
    droite. Sous 116, le graphe est replié et devient illisible.
    """
    LoggingConfigurator.configure(level="PLOT", console_width=120)
    log = logging.getLogger("app.plot")
    log.setLevel(PLOT)
    return log


def main():
    log = configurer()

    # Marche aléatoire tendancielle
    nav = [100.0]
    for _ in range(299):
        nav.append(nav[-1] * (1 + random.gauss(0.0008, 0.006)))
    print("sparkline équivalente :", spark(nav))
    plot_line(log, nav, title="NAV — marche aléatoire tendancielle")

    # Corrélation visible
    xs = [random.gauss(0, 1) for _ in range(200)]
    ys = [1.8 * x + random.gauss(0, 0.6) for x in xs]
    plot_scatter(log, xs, ys, title="rendement du fonds vs indice (beta ~1.8)")

    # Loi mixte bimodale
    vals = ([random.gauss(-2, 0.6) for _ in range(600)]
            + [random.gauss(2.5, 0.9) for _ in range(400)])
    print("sparkline équivalente :", spark(sorted(vals)))
    plot_hist(log, vals, bins=30, title="distribution bimodale des rendements")

    # Sept catégories
    secteurs = ["Tech", "Santé", "Énergie", "Finance", "Conso", "Indus", "Utilities"]
    expo = [32.4, 18.1, 12.7, 11.9, 9.8, 8.6, 6.5]
    plot_bar(log, secteurs, expo, title="exposition par secteur (%)")

    print("\nUne sparkline coûte ~12 µs, un de ces graphes ~1.7 ms — 145 fois plus.")
    print("Sur une ligne de log par itération de boucle, le choix est vite fait.")


if __name__ == "__main__":
    main()
