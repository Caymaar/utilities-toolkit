"""Bac à sable : mesurer, lire la table, et le piège du tier figé.

    PROBE_TIER=1 python examples/probe/probe_playground.py

Le fichier est découpé en cellules `# %%` : dans VS Code, chaque bloc se lance
seul avec « Run Cell ». `probe_playground.ipynb` en est la copie exacte.

**Le piège, à connaître avant tout le reste** : le tier est lu **une seule fois,
à l'import**. Dans un notebook, il faut donc poser `PROBE_TIER` dans la toute
première cellule, avant d'importer `utilities` — et si le paquet est déjà
importé, redémarrer le noyau. La première cellule s'en charge et vous le dit.
"""

# %% [markdown]
# # Bac à sable — instrumentation
#
# Trois questions : où passe le temps, est-ce du CPU ou de l'attente, et
# qu'est-ce qui alloue.

# %%
# ⚠ CETTE CELLULE D'ABORD, avant tout import de `utilities`.
import os
import sys

os.environ.setdefault("PROBE_TIER", "1")   # 0 = éteint, 1 = temps, 2 = + mémoire

if "utilities" in sys.modules:
    print("⚠ `utilities` est déjà importé : le tier est figé à sa valeur du moment.")
    print("  Redémarrez le noyau puis relancez cette cellule en premier.")

import utilities  # noqa: E402
from utilities.probe import PERF, TIER, Probe, Stat, probe, probed, registry, report, reset, to_dicts  # noqa: E402

print("PROBE_TIER =", os.environ["PROBE_TIER"], "-> TIER =", TIER)

# Un arrêt ici n'est pas un bug : c'est la démonstration du gel à l'import.
assert TIER > 0, (
    "TIER vaut 0, rien ne sera mesuré.\n"
    "  - en script  : relancez avec PROBE_TIER=1 python examples/probe/probe_playground.py\n"
    "  - en notebook: redémarrez le noyau, puis lancez CETTE cellule en premier."
)

# %% [markdown]
# ## CPU ou attente ?
#
# `wait = wall - cpu`. C'est la colonne qui décide de la suite des travaux :
# proche de `wall`, on attend une machine d'en face et réécrire du Python ne
# rapportera rien.

# %%
import time

reset()

with probe("cpu.pur"):
    sum(i * i for i in range(2_000_000))

with probe("attente.pure"):
    time.sleep(0.25)

with probe("mixte"):
    time.sleep(0.12)
    sum(i * i for i in range(1_000_000))

print(report(rich=False, sort="wait"))

# %% [markdown]
# ## Temps propre contre temps cumulé
#
# Une fonction qui ne fait que déléguer arrive en tête par `wall` en étant
# innocente. C'est `self` qui donne le vrai classement.

# %%
reset()


@probed("inner")
def inner():
    time.sleep(0.05)


@probed("outer")
def outer():
    for _ in range(3):
        inner()


@probed("travail.propre")
def travail_propre():
    return sum(i * i for i in range(2_000_000))


outer()
travail_propre()

print("--- trié par wall : `outer` domine ---")
print(report(rich=False, sort="wall"))
print("\n--- trié par self : le vrai coupable ---")
print(report(rich=False, sort="self"))

# %% [markdown]
# ## Les formes de restitution

# %%
# 1. texte pur, rien n'est imprimé — c'est ce qu'on met dans un fichier
texte = report(rich=False)
print(type(texte).__name__, "de", len(texte.splitlines()), "lignes")

# %%
# 2. table Rich
report()

# %%
# 3. structuré, pour comparer deux runs ou remplir un DataFrame
import json

print(json.dumps(to_dicts(sort="self")[:2], indent=2))

# %% [markdown]
# ## Le log par appel, via le système du package
#
# Par défaut, rien n'est logué : un `LogRecord` formaté coûte 10 à 30 µs, soit
# dix fois une probe, et sur 10 000 appels on mesurerait surtout sa propre
# instrumentation. Les mesures sont donc agrégées, et la table rendue une fois.
#
# Pour suivre chaque bloc en direct, il suffit d'**écouter** le logger
# `utilities.probe` au niveau `PERF` (15). Le module n'ajoute aucun handler et
# ne touche pas à la configuration de l'hôte : c'est `LoggingConfigurator` qui
# fournit la console, comme pour le reste du package.

# %%
import logging

from utilities import LoggingConfigurator

# 140 et non 120 : une ligne PERF fait ~80 caractères, auxquels RichHandler
# ajoute ~29 de gouttière et ~15 de colonne de chemin. En dessous, elle se
# replie sur deux lignes et devient pénible à lire.
LoggingConfigurator.configure(level="PERF", console_width=140)

reset()
with probe("db.execute"):
    time.sleep(0.05)
with probe("transform"):
    sum(i * i for i in range(500_000))

print("\nNiveau PERF = %d, entre DEBUG (10) et INFO (20) : un run passé en" % PERF)
print("DEBUG fait apparaître les mesures gratuitement, un run en INFO les masque.")

# %%
# Repasser au-dessus de PERF : les mesures continuent, le bruit s'arrête.
logging.getLogger("utilities.probe").setLevel(logging.INFO)

reset()
with probe("silencieux"):
    time.sleep(0.02)
print("mesuré sans rien loguer :", registry["silencieux"])

# %% [markdown]
# ## Agrégation et quantiles
#
# Un log par appel coûterait 10 à 30 µs. Les mesures sont donc **agrégées** par
# label, et la table rendue une fois.

# %%
reset()
for i in range(200):
    with probe("boucle"):
        time.sleep(0.001 if i % 10 else 0.02)   # une itération lente sur dix

s = registry["boucle"]
print("n        =", s.n)
print("moyenne  = %.2f ms" % (s.mean_s * 1e3))
print("p50      = %.2f ms" % (s.quantile(0.5) * 1e3))
print("p95      = %.2f ms" % (s.quantile(0.95) * 1e3))
print("\nLa moyenne cache la queue : c'est le p95 qui montre les lentes.")

# %% [markdown]
# ## Coroutines
#
# Piège de lecture : la somme des `wall` dépasse la durée réelle. C'est de la
# concurrence, pas une erreur de mesure.

# %%
import asyncio
import threading

reset()


@probed("fetch")
async def fetch(n):
    await asyncio.sleep(0.2)
    return n


async def collecte():
    return await asyncio.gather(*(fetch(i) for i in range(3)))


def lancer(coro):
    """Exécute une coroutine dans un script **comme** dans un noyau Jupyter.

    Un noyau fait déjà tourner une boucle : `asyncio.run` y lève, et
    `run_until_complete` aussi. Jupyter accepte un `await` au niveau du
    fichier, mais ce serait une erreur de syntaxe dans un `.py`. Le seul
    moyen d'écrire un code qui marche des deux côtés est de démarrer une
    boucle dans un thread à soi.

    L'attribution des mesures reste juste : `contextvars` est isolé par
    thread, et le registry est protégé par un verrou.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)          # script : aucune boucle en cours

    resultat = {}

    def cible():
        resultat["valeur"] = asyncio.run(coro)

    fil = threading.Thread(target=cible)
    fil.start()
    fil.join()
    return resultat["valeur"]


t0 = time.perf_counter()
resultats = lancer(collecte())
reel = time.perf_counter() - t0

print("résultats :", resultats)
print("durée réelle du programme : %.3f s" % reel)
print(report(rich=False))
print("somme des wall = %.3f s pour %.3f s de temps réel" % (registry["fetch"].wall_s, reel))

# %% [markdown]
# ## Ce que coûte une probe
#
# ~1.4 µs en tier 1. D'où la règle : **n'instrumenter que des blocs ≥ 400 µs**.
# Jamais une itération de boucle — on instrumente la boucle.

# %%
from time import perf_counter


def bench(fn, n, repeats=3):
    best = float("inf")
    for _ in range(repeats):
        t0 = perf_counter()
        for _ in range(n):
            fn()
        best = min(best, perf_counter() - t0)
        reset()
    return best / n * 1e9


def nue():
    return None


decoree = probed("bench")(nue)

nu = bench(nue, 50_000)
deco = bench(decoree, 50_000)
print("appel nu             %8.1f ns" % nu)
print("appel décoré         %8.1f ns" % deco)
print("surcoût              %8.1f ns" % (deco - nu))
print("\nEn tier 0, `probed()` renvoie la fonction inchangée : le surcoût est nul.")
print("Vérifiable avec `PROBE_TIER=0 python examples/probe/demo_02_overhead.py`.")

# %% [markdown]
# ## Tier 2 : la mémoire
#
# À lancer dans un **autre** process, avec `PROBE_TIER=2`. `tracemalloc`
# ralentit tout le process (×10 sur un appel nu), donc on ne conclut jamais sur
# la latence à partir d'un run tier 2.

# %%
import subprocess

code = """
from utilities.probe import probe, report
with probe("retient"):
    garde = [i for i in range(300_000)]
with probe("libere"):
    tmp = [i for i in range(300_000)]
    del tmp
print(report(rich=False))
"""
sortie = subprocess.run(
    [sys.executable, "-c", code],
    env=dict(os.environ, PROBE_TIER="2"),
    capture_output=True, text=True,
)
print(sortie.stdout or sortie.stderr)
print("`retient` garde sa mémoire, `libere` la rend : alloc est un delta NET.")

# %% [markdown]
# ## À la fin du process
#
# Quand le tier est actif, la table est imprimée une fois à la sortie — dans un
# notebook, à l'arrêt du noyau. Un `report()` explicite la remplace, il n'y a
# pas de double affichage.

# %%
reset()
with probe("dernier"):
    time.sleep(0.01)
print("registry :", {k: v.n for k, v in registry.items()})
