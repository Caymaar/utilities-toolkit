"""Le même registry rendu dans tous les formats disponibles.

    python examples/probe/demo_06_render.py

Pour choisir celui qu'on veut par défaut :

  - `report(rich=False)` renvoie le texte pur sans rien imprimer. C'est ce
    qu'on met dans un fichier de log ou ce qu'on compare entre deux runs ;
  - `report(stream=...)` écrit ce même texte dans un flux ;
  - `report()` imprime une table Rich sur la console — celle du logger si
    l'application en a configuré une via LoggingConfigurator, sinon stderr ;
  - `to_dicts()` renvoie des lignes sérialisables : JSON, CSV, ou un DataFrame
    si le projet consommateur en a un. Le module n'ajoute aucune dépendance
    pour ça.

Rendu automatique : quand le tier est actif, la table est imprimée une fois à
la sortie du process. Un appel explicite à `report()` la remplace, il n'y a pas
de double affichage.
"""

import json
import os
import subprocess
import sys
import time

if os.environ.get("PROBE_TIER") is None:
    raise SystemExit(subprocess.run(
        [sys.executable, __file__], env=dict(os.environ, PROBE_TIER="1")
    ).returncode)

from utilities.probe import probe, report, to_dicts  # noqa: E402


def workload():
    for _ in range(4):
        with probe("db.execute"):
            time.sleep(0.02)
    with probe("transform"):
        sum(i * i for i in range(500_000))


def main():
    workload()

    print("=" * 60)
    print("1. texte pur — report(rich=False)")
    print("=" * 60)
    print(report(rich=False))

    print("\n" + "=" * 60)
    print("2. dans un flux — report(stream=sys.stdout)")
    print("=" * 60)
    report(stream=sys.stdout, sort="self")

    print("\n" + "=" * 60)
    print("3. table Rich — report()")
    print("=" * 60)
    sys.stdout.flush()
    report()

    print("\n" + "=" * 60)
    print("4. structuré — to_dicts()")
    print("=" * 60)
    print(json.dumps(to_dicts(), indent=2))


if __name__ == "__main__":
    main()
