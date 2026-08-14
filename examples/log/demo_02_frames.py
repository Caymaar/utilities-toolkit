"""Les quatre modes de `log_frame`, et le plafond du mode `full`.

    python examples/log/demo_02_frames.py

Ce qu'il faut voir : ce que rend chaque mode, et surtout que `full` **tronque**
en annonçant combien de lignes il a laissées de côté. La seconde passe, sur
500 000 lignes, rend la chose indiscutable : sans plafond, ce log ferait des
mégaoctets.

Le repr natif de polars tronque déjà de lui-même. Le mode `full` est justement
celui qui lève ce garde-fou pour montrer plus de lignes — c'est donc à nous d'en
remettre un, et il n'est pas désactivable.
"""

import logging
import random

from utilities import LoggingConfigurator
from utilities.log import DATAFRAME, log_frame

try:
    import pandas as pd
    import polars as pl
except ImportError:
    raise SystemExit(
        "Cette démo a besoin de polars et pandas : uv sync --group dev\n"
        "(le package, lui, ne les importe jamais — il les détecte sur l'objet reçu)"
    )

random.seed(3)


def configurer():
    """Le logging du package. Aucun handler posé à la main."""
    LoggingConfigurator.configure(level="DATAFRAME", console_width=120)
    log = logging.getLogger("app.data")
    log.setLevel(DATAFRAME)
    return log


def main():
    log = configurer()

    n = 5_000
    df = pd.DataFrame({
        "ticker": [random.choice(["AAPL", "MSFT", "SAN", "BNP"]) for _ in range(n)],
        "quantite": [random.randint(-500, 500) for _ in range(n)],
        "prix": [round(random.uniform(10, 400), 2) for _ in range(n)],
    })

    for mode in ("head", "tail", "describe"):
        print("\n" + "=" * 78)
        print("mode=%s" % mode)
        print("=" * 78)
        log_frame(log, df, mode=mode, n=5, label="positions")

    print("\n" + "=" * 78)
    print("mode=full sur 5 000 lignes, plafond abaissé à 6 pour la démo")
    print("=" * 78)
    log_frame(log, df, mode="full", label="positions", max_rows=6)

    print("\n" + "=" * 78)
    print("mode=full sur 500 000 lignes, plafond par défaut (200)")
    print("=" * 78)
    gros = pl.DataFrame({
        "i": list(range(500_000)),
        "x": [i * 0.001 for i in range(500_000)],
    })
    log_frame(log, gros, mode="full", label="gros")

    print("\n" + "=" * 78)
    print("rich=True : la même tranche, rendue en table Rich")
    print("=" * 78)
    log_frame(log, df, mode="head", n=4, label="positions", rich=True)


if __name__ == "__main__":
    main()
