"""Coroutines concurrentes : l'attribution reste juste, la lecture change.

    python examples/probe/demo_05_async.py

Deux pièges de lecture, à connaître avant d'interpréter une table produite sous
asyncio :

1. **La somme des `wall` dépasse la durée réelle du programme.** C'est normal :
   trois coroutines qui dorment 0,2 s en parallèle totalisent 0,6 s de `wall`
   pour 0,2 s de temps réel. Le `wall` d'un bloc est son temps écoulé, pas sa
   part du temps du programme.

2. **`self` et `cpu` ne sont pas fiables entre tâches concurrentes.** Chaque
   `Task` asyncio travaille sur une copie du contexte : le temps d'une probe
   enfant lancée dans une autre tâche ne remonte pas à son parent, donc le
   `self` d'un parent qui fait un `gather` reste égal à son `wall`. Et `cpu`
   est mesuré au niveau du process : deux probes qui se recouvrent comptent
   toutes les deux le même CPU.

   L'imbrication reste exacte à l'intérieur d'une même tâche — c'est le cas
   courant. Pour comparer des coroutines entre elles, lire `wall` et `wait`.

Ce qu'il faut regarder : `fetch` compte 3 appels d'environ 0,2 s chacun alors
que le programme entier dure ~0,2 s, et `wait ≈ wall` partout puisque tout le
monde attend.
"""

import asyncio
import os
import subprocess
import sys
import time

if os.environ.get("PROBE_TIER") is None:
    raise SystemExit(subprocess.run(
        [sys.executable, __file__], env=dict(os.environ, PROBE_TIER="2")
    ).returncode)

from utilities.probe import probed, report  # noqa: E402

from utilities import LoggingConfigurator

LoggingConfigurator.configure(level="DEBUG")

@probed("fetch")
async def fetch(n):
    """Simule un appel réseau concurrent."""
    await asyncio.sleep(0.2)
    return n


@probed("collecte")
async def collecte():
    return await asyncio.gather(*(fetch(i) for i in range(3)))


def main():
    t0 = time.perf_counter()
    resultats = asyncio.run(collecte())
    reel = time.perf_counter() - t0

    # print("résultats : %s" % (resultats,))
    # print("durée réelle du programme : %.3fs\n" % reel)
    # print(report(rich=False))
    # print("\nSomme des wall de `fetch` ≈ 0.6s pour %.3fs de temps réel :" % reel)
    # print("c'est de la concurrence, pas une erreur de mesure.")


if __name__ == "__main__":
    main()
