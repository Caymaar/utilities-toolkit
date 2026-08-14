"""Bac à sable : voir ce que rendent les niveaux, les formes, les tables.

    python examples/log/log_playground.py

Le fichier est découpé en cellules `# %%` : dans VS Code, chaque bloc se lance
seul avec « Run Cell ». `log_playground.ipynb` en est la copie exacte, cellule
pour cellule, si vous préférez Jupyter.

Contrairement aux `demo_*.py`, qui démontrent chacun un point précis, celui-ci
est fait pour être **modifié** : changez les données, les modes, les niveaux, et
regardez ce que ça donne.
"""

# %% [markdown]
# # Bac à sable — niveaux, formes et sorties
#
# Trois choses à observer : **où** part la sortie, **quel niveau** la laisse
# passer, et **quelle forme** elle prend.

# %%
import logging
import math
import random
import re

from utilities import LoggingConfigurator
from utilities.log import DATAFRAME, PLOT, Lazy, log_frame, spark
from utilities.log.plots import plot_bar, plot_hist, plot_line, plot_scatter

random.seed(0)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
print("niveaux :", logging.getLevelName(6), logging.getLevelName(8), logging.getLevelName(15))

# %% [markdown]
# ## La configuration du package, une fois pour toutes
#
# On ne pose pas de handler à la main : `LoggingConfigurator` s'en charge —
# console Rich, fichiers rotatifs, nettoyage des ANSI. Deux paramètres
# comptent ici :
#
# - `level="PLOT"` ouvre les handlers au niveau le plus bas. Les niveaux se
#   règlent ensuite **par logger**, ce qui est le vrai mécanisme ;
# - `console_width=120` parce qu'un graphe fait 72 colonnes, plus ~29 de
#   gouttière. Sous 116, le graphe est replié — en script, où la colonne de
#   chemin prend encore ~15 colonnes de plus.
#
# **Dans un notebook**, `configure()` détecte le noyau et s'adapte tout seul
# (`notebook=None` par défaut, forçable à True ou False). Sans ça, Rich rend
# chaque enregistrement en HTML via `display()` : un bloc de sortie par ligne
# de log, séparé des autres par les marges de Jupyter. Le mode notebook repasse
# en texte continu et retire la colonne de chemin, qui n'affichait que le
# fichier temporaire de la cellule — le fameux `3403673953.py:6`.
#
# `configure()` est un **one-shot** : le second appel ne fait rien. Relancer
# cette cellule est donc sans effet, et sans risque d'empiler les handlers.

# %%
LoggingConfigurator.configure(level="PLOT", console_width=120)


def journal(nom="nb", niveau=PLOT):
    """Règle le niveau d'un logger. Les handlers viennent du configurateur."""
    log = logging.getLogger(nom)
    log.setLevel(niveau)
    return log


log = journal()
log.info("passé par la console Rich du package")

# %% [markdown]
# ## Les niveaux, sur le même appel
#
# `PLOT` (6) < `DATAFRAME` (8) < `DEBUG` (10) < `PERF` (15) < `INFO` (20).
# Un niveau est **ordonné** : descendre prend tout ce qui est au-dessus.

# %%
serie = [100 + math.sin(i / 8) * 6 + random.random() for i in range(200)]

for niveau in (logging.INFO, logging.DEBUG, DATAFRAME, PLOT):
    log = journal(niveau=niveau)
    print("\n--- niveau réglé sur %s ---" % logging.getLevelName(niveau))
    log.info("info  : passe toujours")
    log.debug("debug : passe à partir de DEBUG")
    log.log(DATAFRAME, "dataframe : passe à partir de DATAFRAME")
    log.log(PLOT, "plot  : passe seulement à PLOT")

# %% [markdown]
# ## Le namespace, pour ce que le niveau ne sait pas faire
#
# Impossible d'avoir les graphes **sans** les DataFrames avec le seul niveau,
# puisque `PLOT` est en dessous. Deux loggers séparés, eux, se règlent
# indépendamment.

# %%
racine = journal("app", niveau=logging.INFO)
data = logging.getLogger("app.data")
plot = logging.getLogger("app.plot")
data.setLevel(logging.INFO)   # muet
plot.setLevel(PLOT)           # bavard

print("app.data émet un DataFrame ?", data.isEnabledFor(DATAFRAME))
print("app.plot émet un graphe ?   ", plot.isEnabledFor(PLOT))

# %% [markdown]
# ## Les formes que rend `spark()`
#
# C'est le premier réflexe : une ligne, greppable, ~12 µs pour 300 points.
# Regardez si la forme se reconnaît.

# %%
formes = {
    "croissant     ": list(range(100)),
    "décroissant   ": list(range(100, 0, -1)),
    "sinus         ": [math.sin(i / 5) for i in range(100)],
    "en cloche     ": [math.exp(-((i - 50) ** 2) / 300) for i in range(100)],
    "bimodal (trié)": sorted([random.gauss(-2, 0.5) for _ in range(200)]
                             + [random.gauss(2, 0.5) for _ in range(200)]),
    "marche aléat. ": serie,
    "constant      ": [7] * 40,
    "un seul point ": [42],
    "vide          ": [],
    "avec des trous": [1, None, 3, float("nan"), 5, float("inf"), 7],
}
for nom, valeurs in formes.items():
    print("%s %s" % (nom, spark(valeurs)))

# %%
# La largeur se règle, et les extrémités sont toujours conservées.
pic_final = [0.0] * 40 + [100.0]
for largeur in (8, 16, 24, 48):
    print("n=%2d %s" % (largeur, spark(pic_final, n=largeur)))

# %% [markdown]
# ## `log_frame` — les quatre modes et leur forme
#
# Sauté si polars n'est pas là : le package ne l'importe jamais, il le détecte
# sur l'objet qu'on lui passe.

# %%
try:
    import polars as pl
except ImportError:
    pl = None
    print("polars absent : uv sync --group dev pour cette section")

if pl is not None:
    n = 4_000
    df = pl.DataFrame({
        "ticker": [random.choice(["AAPL", "MSFT", "SAN", "BNP"]) for _ in range(n)],
        "quantite": [random.randint(-500, 500) for _ in range(n)],
        "prix": [round(random.uniform(10, 400), 2) for _ in range(n)],
    })
    log = journal("app.data", niveau=DATAFRAME)
    for mode in ("head", "tail", "describe"):
        print("\n=== mode=%s ===" % mode)
        log_frame(log, df, mode=mode, n=4, label="positions")

# %%
# Le plafond du mode `full`, et sa mention de troncature.
if pl is not None:
    print("=== full, plafond abaissé à 5 ===")
    log_frame(log, df, mode="full", label="positions", max_rows=5)

    print("\n=== full sur 500 000 lignes, plafond par défaut ===")
    gros = pl.DataFrame({"i": list(range(500_000)), "x": [i * 0.5 for i in range(500_000)]})
    log_frame(log, gros, mode="full", label="gros")

# %%
# La même tranche en table Rich, pour comparer la forme.
if pl is not None:
    print("=== rich=False (repr natif) ===")
    log_frame(log, df, mode="head", n=3, label="positions")
    print("\n=== rich=True ===")
    log_frame(log, df, mode="head", n=3, label="positions", rich=True)

# %%
# Un LazyFrame n'est jamais matérialisé : on logue le plan.
if pl is not None:
    plan = df.lazy().filter(pl.col("quantite") > 0).group_by("ticker").agg(
        pl.col("prix").mean().alias("prix_moyen")
    )
    log_frame(log, plan, label="agrégation")

# %% [markdown]
# ## Les graphes
#
# ~1.7 ms le tracé, contre ~12 µs la sparkline. À réserver aux moments qui le
# méritent — une fois par run, pas une fois par itération.

# %%
log = journal("app.plot", niveau=PLOT)

nav = [100.0]
for _ in range(299):
    nav.append(nav[-1] * (1 + random.gauss(0.0006, 0.006)))

print("sparkline :", spark(nav))
plot_line(log, nav, title="NAV")

# %%
xs = [random.gauss(0, 1) for _ in range(200)]
ys = [1.5 * x + random.gauss(0, 0.5) for x in xs]
plot_scatter(log, xs, ys, title="corrélation visible")

# %%
melange = ([random.gauss(-2, 0.6) for _ in range(600)]
           + [random.gauss(2.5, 0.9) for _ in range(400)])
plot_hist(log, melange, bins=25, title="distribution bimodale")

# %%
plot_bar(log, ["Tech", "Santé", "Énergie", "Finance", "Conso"],
         [32.4, 18.1, 12.7, 11.9, 9.8], title="exposition par secteur (%)")

# %% [markdown]
# ## Les ANSI, retirées par le configurateur
#
# plotext émet des séquences ANSI même sous `theme("clear")`. Les handlers de
# `LoggingConfigurator` les retirent : dans un fichier elles sont du bruit, et
# sur la console `RichHandler` les afficherait en texte visible — un `[0m` au
# milieu du graphe — puisqu'il rend le message comme du texte.
#
# Un handler posé à la main, lui, les laisse passer. C'est le handler qui
# tranche, jamais l'émetteur.

# %%
import tempfile
from pathlib import Path

dossier = Path(tempfile.mkdtemp(prefix="playground_"))
brut = dossier / "brut.log"

log = journal("app.ansi", PLOT)
h_brut = logging.FileHandler(brut, encoding="utf-8")
h_brut.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(h_brut)

plot_line(log, [i * i for i in range(30)], title="quadratique")

h_brut.flush()
log.removeHandler(h_brut)
h_brut.close()

print("handler brut               : %2d séquences ANSI" % len(ANSI.findall(brut.read_text())))
print("console de LoggingConfigurator :  0 — regardez le graphe ci-dessus, aucun [0m")

# %% [markdown]
# ## `Lazy` : ne calculer que si quelqu'un écoute

# %%
compteur = {"appels": 0}


def calcul_cher():
    compteur["appels"] += 1
    return "résultat coûteux"


log = journal("app.lazy", niveau=logging.INFO)
log.debug("jamais évalué : %s", Lazy(calcul_cher))
print("après un debug au niveau INFO :", compteur["appels"], "appel(s)")

log.setLevel(logging.DEBUG)
log.debug("évalué maintenant : %s", Lazy(calcul_cher))
print("après un debug au niveau DEBUG :", compteur["appels"], "appel(s)")

# %% [markdown]
# ## Ce que ça coûte
#
# Seule section à ne **pas** passer par la console du package, et c'est
# délibéré : on mesure le coût de construction du rendu, pas celui de
# l'affichage. Sinon on chronométrerait surtout le terminal, et cinquante
# graphes défileraient à l'écran.

# %%
from time import perf_counter


def cout(fn, n):
    t0 = perf_counter()
    for _ in range(n):
        fn()
    return (perf_counter() - t0) / n * 1e6


muet = journal("app.muet", niveau=logging.INFO)   # au-dessus de DATAFRAME et PLOT
sourd = logging.getLogger("app.sourd")            # niveau ouvert, sortie jetée
sourd.handlers = [logging.NullHandler()]
sourd.propagate = False
sourd.setLevel(PLOT)

print("éteint  plot_line   %8.3f us" % cout(lambda: plot_line(muet, nav), 100_000))
print("allumé  spark       %8.1f us" % cout(lambda: spark(nav), 20_000))
print("allumé  plot_line   %8.1f us" % cout(lambda: plot_line(sourd, nav), 50))
if pl is not None:
    print("allumé  log_frame   %8.1f us" % cout(lambda: log_frame(sourd, df, mode="head"), 1_000))
