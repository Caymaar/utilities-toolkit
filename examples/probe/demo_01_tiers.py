"""Le même travail rendu sous les trois tiers, pour voir la différence.

    python examples/probe/demo_01_tiers.py

Le script se relance lui-même en sous-process avec la bonne valeur de
PROBE_TIER : le tier est figé à l'import, on ne peut pas le changer en cours de
route.

Ce qu'il faut regarder :
  - tier 0 : la table est **vide**. Aucun wrapper n'a été posé, rien n'a été
    mesuré, et le code d'instrumentation n'a rien coûté ;
  - tier 1 : les temps ;
  - tier 2 : la colonne `alloc` apparaît, et les temps sont visiblement gonflés
    par tracemalloc. C'est pour ça qu'on ne conclut jamais sur la latence à
    partir d'un run tier 2.
"""

import os
import subprocess
import sys
import time

from utilities.probe import TIER, probe, probed, report

CHILD_FLAG = "--child"


@probed("inner.cpu")
def cpu_block():
    return sum(i * i for i in range(300_000))


@probed("inner.io")
def io_block():
    time.sleep(0.03)


@probed("inner.alloc")
def alloc_block():
    """Retient sa mémoire : c'est ce que mesure la colonne `alloc`."""
    return [i for i in range(400_000)]


@probed("outer")
def outer():
    """Ne fait que déléguer : son `self` doit être proche de zéro."""
    cpu_block()
    for _ in range(3):
        io_block()


def child():
    garde = alloc_block()  # gardé en vie : sinon le delta net retombe à zéro
    outer()
    with probe("bloc.manuel"):
        time.sleep(0.02)
    del garde

    text = report(rich=False)
    print(text if text else "(registry vide — rien n'a été mesuré)")


def parent():
    for tier, titre in (("0", "désactivé"), ("1", "temps"), ("2", "temps + mémoire")):
        print("\n" + "=" * 81)
        print("PROBE_TIER=%s  (%s)" % (tier, titre))
        print("=" * 81)
        sys.stdout.flush()
        env = dict(os.environ, PROBE_TIER=tier)
        subprocess.run([sys.executable, __file__, CHILD_FLAG], env=env, check=True)


if __name__ == "__main__":
    if CHILD_FLAG in sys.argv:
        child()
    else:
        if TIER:
            print("PROBE_TIER est déjà positionné ; le parent l'ignore et "
                  "impose 0, 1 puis 2 à ses enfants.")
        parent()
