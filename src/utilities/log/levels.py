"""Niveaux de log custom du package.

Un niveau de log est **global au process** : deux modules qui revendiquent le
même entier se marchent dessus. Ils sont donc tous enregistrés ici, et nulle
part ailleurs.

Ordonnés par **coût croissant vers le bas de l'échelle** : descendre le niveau,
c'est accepter de payer plus cher.

    6   PLOT        ~1.7 ms par graphe plotext
    8   DATAFRAME   ~80 us (head) a ~340 us (describe sur 5k lignes)
    10  DEBUG
    15  PERF        ~1.4 us par probe
    20  INFO

Un niveau est **ordonné**, donc régler un logger sur ``DATAFRAME`` (8) n'émet
pas les graphes, alors que le régler sur ``PLOT`` (6) émet les deux. Pour avoir
les graphes **sans** les DataFrames, c'est le namespace du logger qui sert
d'interrupteur, pas le niveau — voir le README.
"""

import logging

__all__ = ["PERF", "DATAFRAME", "PLOT"]

#: Niveau des mesures d'instrumentation émises par :mod:`utilities.probe`.
PERF = 15

#: Niveau du rendu de DataFrames par :func:`utilities.log.frames.log_frame`.
DATAFRAME = 8

#: Niveau des graphes terminal de :mod:`utilities.log.plots`. Le plus verbeux
#: et le plus cher.
PLOT = 6


def _register(level: int, name: str) -> None:
    """Nomme un niveau sans écraser un nom déjà revendiqué par un autre paquet.

    Une fois nommé, le niveau est utilisable partout où ``logging`` accepte un
    nom : ``logger.setLevel("PLOT")``, ``LoggingConfigurator.configure(
    level="DATAFRAME")``, ou ``LOG_LEVEL=PLOT`` dans l'environnement.
    """
    if logging.getLevelName(level).startswith("Level "):
        logging.addLevelName(level, name)


_register(PERF, "PERF")
_register(DATAFRAME, "DATAFRAME")
_register(PLOT, "PLOT")
