"""La question qui décide de la suite des travaux : CPU ou attente ?

    python examples/probe/demo_03_io_vs_cpu.py

`wait = wall - cpu`. C'est tout, et c'est la métrique centrale du module.

Le cas d'usage : un pipeline ODBC/Access ou Postgres passe 42 s dans
`cursor.execute`. Un cProfile s'arrête là et vous laisse avec « 42 s dans
execute ». Ici, en trois lignes :
  - si `wait ≈ wall`, ces 42 s sont passées à attendre le SGBD ou le réseau —
    optimiser le code Python ne rapportera rien, il faut regarder la requête,
    l'index, le partage SMB ;
  - si `wait ≈ 0`, c'est du CPU Python — matérialisation des lignes, conversion
    de types — et là oui, le code est en cause.

Ce qu'il faut regarder : `wait ≈ 0` sur le bloc CPU, `wait ≈ wall` sur le bloc
d'attente, et le mixte entre les deux.
"""

import os
import subprocess
import sys
import time

if os.environ.get("PROBE_TIER") is None:
    # Le tier est figé à l'import : on se relance avec la bonne env var plutôt
    # que d'exiger de l'utilisateur qu'il la positionne.
    raise SystemExit(subprocess.run(
        [sys.executable, __file__], env=dict(os.environ, PROBE_TIER="1")
    ).returncode)

from utilities.probe import probe, report  # noqa: E402


def main():
    with probe("cpu.pur"):
        sum(i * i for i in range(2_000_000))

    with probe("attente.pure"):
        time.sleep(0.30)

    with probe("mixte"):
        time.sleep(0.15)
        sum(i * i for i in range(1_000_000))

    print(report(rich=False, sort="wait"))
    print("\nTrié par wait. En haut, ce qui attend une machine d'en face ;")
    print("en bas, ce qui consomme réellement du CPU.")


if __name__ == "__main__":
    main()
