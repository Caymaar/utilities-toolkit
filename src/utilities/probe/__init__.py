"""Instrumentation de latence et de mémoire, à coût nul quand désactivée.

Trois questions, sans sortir l'artillerie d'un profiler : où passe le temps,
est-ce du CPU ou de l'attente, et qu'est-ce qui alloue.

**Règle de granularité** — une probe coûte ~1.4 µs en tier 1, mesuré. On
n'instrumente que des blocs de **400 µs ou plus** (marge ×280). Jamais une
itération de boucle : on instrumente la boucle, pas l'enregistrement. Sinon on
mesure sa propre instrumentation.

**Avertissement tier 2** — ``tracemalloc`` ralentit le process *globalement*,
pas seulement les blocs mesurés. On ne conclut **jamais** sur la latence à
partir d'un run tier 2, ni sur la mémoire à partir d'un run tier 1.

Activation, lue une seule fois à l'import :

    PROBE_TIER=0 | off | (vide)    tier 0, aucun wrapper posé (défaut)
    PROBE_TIER=1 | time | on       tier 1, chronométrage
    PROBE_TIER=2 | mem | full      tier 2, + tracemalloc

**Le tier est figé à l'import et ne peut pas être changé ensuite.** C'est la
contrepartie directe du coût nul : en tier 0, ``probed()`` renvoie la fonction
inchangée, il n'y a aucun wrapper à réveiller plus tard. Concrètement :

    import utilities                      # <- le tier est lu ICI
    os.environ["PROBE_TIER"] = "1"        # <- sans effet, trop tard

La variable se positionne **avant de lancer le process** :

    PROBE_TIER=1 python mon_script.py

Il n'y a pas de fonction pour activer les mesures depuis le code, et c'est
volontaire : un flag relu à chaque appel coûterait 200-400 ns par probe, y
compris quand personne ne mesure.

Deux surfaces d'API :

    from utilities import probed
    from utilities.probe import probe

    @probed()                       # décorateur, sync ou async
    def fetch(...): ...

    with probe("cursor.execute"):    # context manager
        cur.execute(sql)

``probe`` s'importe depuis ce module et non depuis ``utilities`` : il porte le
même nom que le sous-paquet, et le réexporter au niveau du paquet écraserait
l'attribut ``utilities.probe`` — ``import utilities.probe.render`` cesserait de
fonctionner.

Les mesures sont **agrégées** — un log par appel coûterait 10-30 µs — et la
table est rendue une fois à la sortie du process. Pour la voir plus tôt, ou
sous un autre tri :

    from utilities.probe import report
    report(sort="self")     # le vrai classement des coupables
    report(sort="wait")     # ce qui attend le réseau ou le SGBD

Le log par appel n'est émis que si le logger ``utilities.probe`` est
explicitement écouté au niveau ``PERF`` (15). Le module n'ajoute aucun handler
et ne touche pas à la configuration logging de l'hôte.
"""

import atexit

from utilities.probe.core import (
    ENABLED,
    PERF,
    TIER,
    Probe,
    Stat,
    probe,
    probed,
    registry,
    reset,
    snapshot,
)
from utilities.probe.render import _report_at_exit, report, to_dicts

__all__ = [
    "PERF",
    "TIER",
    "ENABLED",
    "Probe",
    "Stat",
    "probe",
    "probed",
    "registry",
    "snapshot",
    "report",
    "reset",
    "to_dicts",
]

if ENABLED:
    atexit.register(_report_at_exit)
