"""Un batch nocturne tel qu'il apparaît dans un `tail -f` en SSH.

    python examples/log/demo_06_terminal_reading.py

C'est le cas d'usage qui justifie tout le module : un VPS, un batch de nuit, et
un log lu depuis un téléphone. Pas de HTML à ouvrir, pas d'artefact à
rapatrier — le log est la seule surface.

Ce qu'il faut voir : la marche courante tient en lignes `INFO` compactes avec
sparklines, greppables et lisibles sur un écran de 40 colonnes. Le DataFrame et
le graphe n'apparaissent qu'aux étapes qui le méritent, et seulement si on a
demandé ce niveau.

Relancez avec `LOG_LEVEL=INFO` pour voir ce que donne le même batch en régime
normal : uniquement les lignes compactes.
"""

import logging
import os
import random
import tempfile
import time
from pathlib import Path

from utilities import LoggingConfigurator
from utilities.log import log_frame, spark
from utilities.log.plots import plot_line

random.seed(42)

# Un dossier jetable : en production, on omet `base_dir` et le configurateur
# écrit dans ~/utilities/logs/<project>/.
DOSSIER = Path(tempfile.mkdtemp(prefix="demo_batch_"))


def configurer():
    """Exactement ce qu'un vrai batch appelle au démarrage.

    `level` accepte les noms custom du package — PLOT, DATAFRAME, PERF — au
    même titre que DEBUG ou INFO, et `LOG_LEVEL` dans l'environnement le
    surcharge. C'est le configurateur qui pose la console Rich, le fichier
    rotatif, et le nettoyage des ANSI côté fichier.
    """
    niveau = os.environ.get("LOG_LEVEL", "PLOT").upper()
    LoggingConfigurator.configure(
        project="demo_batch",
        level=niveau,
        base_dir=DOSSIER,
        log_file=True,
        console_width=120,
    )
    return niveau


def main():
    niveau = configurer()
    print("--- batch lancé avec LOG_LEVEL=%s ---\n" % niveau)

    log = logging.getLogger("batch")
    data = logging.getLogger("batch.data")
    plot = logging.getLogger("batch.plot")

    log.info("démarrage du batch de valorisation")

    positions = []
    for jour in range(1, 6):
        time.sleep(0.05)
        prix = [round(random.uniform(20, 300), 2) for _ in range(400)]
        positions.append(prix)
        log.info("j%02d chargé n=%d %s [%.1f, %.1f]",
                 jour, len(prix), spark(prix), min(prix), max(prix))

    nav = [100.0]
    for _ in range(120):
        nav.append(nav[-1] * (1 + random.gauss(0.0005, 0.004)))
    log.info("nav calculée n=%d %s [%.2f, %.2f]",
             len(nav), spark(nav), min(nav), max(nav))

    derive = (nav[-1] / nav[0] - 1) * 100
    if abs(derive) > 3:
        log.warning("dérive de %.2f%% sur la période — à regarder", derive)

    try:
        import polars as pl
        df = pl.DataFrame({"jour": list(range(len(nav))), "nav": nav})
        log_frame(data, df, mode="describe", label="nav")
    except ImportError:
        log.info("polars absent : pas de describe (le module, lui, s'en passe)")

    plot_line(plot, nav, title="NAV du run")
    log.info("batch terminé")

    for h in logging.getLogger().handlers:
        h.flush()
    fichier = DOSSIER / "demo_batch.log"
    print("\n--- le même run, tel qu'il est écrit dans %s ---" % fichier)
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    print("\n".join(lignes[:8]))
    print("... %d lignes au total, sans une seule séquence ANSI." % len(lignes))


if __name__ == "__main__":
    main()
