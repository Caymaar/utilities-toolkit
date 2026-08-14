"""Trois pièges, chacun montré cassé puis rattrapé par un garde-fou.

    python examples/log/demo_05_lazy_and_traps.py

1. **Un LazyFrame logué.** Naïvement, afficher un LazyFrame demande de le
   matérialiser : un plan d'exécution complet lancé pour montrer dix lignes,
   depuis du code qu'on croit passif. `log_frame` logue le plan à la place, et
   n'appelle jamais `collect()`.

2. **Les ANSI dans un fichier.** plotext en émet même sous `theme("clear")`.
   `LoggingConfigurator` les retire de ses handlers fichier ; un handler posé
   à la main, non. On compare les deux sur le vrai fichier de log écrit par le
   configurateur.

3. **La configuration d'affichage.** Élargir un DataFrame pour le loguer, c'est
   toucher une configuration **globale** : les `print` de l'appelant s'en
   trouveraient changés. `log_frame` scope la configuration et la restaure,
   y compris quand le rendu lève.
"""

import logging
import re
import tempfile
from pathlib import Path

from utilities import LoggingConfigurator
from utilities.log import DATAFRAME, PLOT, log_frame
from utilities.log.plots import plot_line

try:
    import polars as pl
except ImportError:
    raise SystemExit("Cette démo a besoin de polars : uv sync --group dev")

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Un dossier jetable plutôt que ~/utilities/logs : une démo n'a pas à laisser
# de traces. En vrai, on omet `base_dir` et le configurateur choisit lui-même.
DOSSIER = Path(tempfile.mkdtemp(prefix="demo_log_"))
LoggingConfigurator.configure(
    project="demo_traps",
    level="PLOT",
    base_dir=DOSSIER,
    log_file=True,
    console_width=120,
)
FICHIER = DOSSIER / "demo_traps.log"


def piege_1_lazyframe():
    print("\n" + "=" * 78)
    print("1. LazyFrame — le plan, jamais les données")
    print("=" * 78)

    log = logging.getLogger("app.data")
    log.setLevel(DATAFRAME)

    df = pl.DataFrame({"a": list(range(100_000)), "b": [i % 7 for i in range(100_000)]})
    lz = df.lazy().filter(pl.col("b") > 3).group_by("b").agg(pl.col("a").sum())

    # On piège `collect` pour compter les appels : s'il y en a un seul, le
    # garde-fou de log_frame a sauté.
    appels = []
    vrai_collect = type(lz).collect
    type(lz).collect = lambda self, *a, **k: (appels.append(1), vrai_collect(self, *a, **k))[1]
    try:
        log_frame(log, lz, label="agrégation")
    finally:
        type(lz).collect = vrai_collect

    print("\n-> collect() appelé %d fois. Le plan suffisait." % len(appels))


def piege_2_ansi():
    print("\n" + "=" * 78)
    print("2. ANSI — retirées par LoggingConfigurator, gardées par un handler brut")
    print("=" * 78)

    log = logging.getLogger("app.plot")
    log.setLevel(PLOT)

    # Un handler ajouté à la main, sans le formatter du configurateur.
    brut = DOSSIER / "brut.log"
    h_brut = logging.FileHandler(brut, encoding="utf-8")
    h_brut.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h_brut)

    plot_line(log, [i * i for i in range(30)], title="quadratique")

    for h in logging.getLogger().handlers + log.handlers:
        h.flush()
    log.removeHandler(h_brut)
    h_brut.close()

    propre = FICHIER.read_text(encoding="utf-8")
    sale = brut.read_text(encoding="utf-8")
    print("  handler brut               : %2d séquences ANSI" % len(ANSI.findall(sale)))
    print("  fichier de LoggingConfigurator : %2d séquences ANSI" % len(ANSI.findall(propre)))
    print("\n  fichier écrit : %s" % FICHIER)
    print("-> c'est le handler qui tranche, pas l'émetteur.")


def piege_3_config():
    print("\n" + "=" * 78)
    print("3. Configuration d'affichage — scopée, restaurée même sur exception")
    print("=" * 78)

    log = logging.getLogger("app.data")
    df = pl.DataFrame({"c%d" % i: [1, 2, 3] for i in range(5)})

    avant = str(pl.DataFrame({"x": list(range(50))}))
    log_frame(log, df, mode="full", label="petit", max_rows=3)

    class Explose:
        """Un frame dont le rendu lève : la config doit quand même être rendue."""

        shape = (3, 5)

        def head(self, n):
            return self

        def __str__(self):
            raise RuntimeError("rendu cassé")

    try:
        log_frame(log, Explose(), mode="full", label="cassé")
    except RuntimeError as e:
        print("  exception propagée telle quelle : %s" % e)

    apres = str(pl.DataFrame({"x": list(range(50))}))
    print("  rendu global identique avant/après : %s" % (avant == apres))
    print("\n-> vos propres print() ne changent pas parce que vous avez logué.")


if __name__ == "__main__":
    piege_1_lazyframe()
    piege_2_ansi()
    piege_3_config()
