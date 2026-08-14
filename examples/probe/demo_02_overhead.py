"""Ce que coûte l'instrumentation, mesuré sur cette machine.

    python examples/probe/demo_02_overhead.py

Trois mesures par tier : une fonction nue, la même décorée, et le context
manager. Le script se relance en sous-process pour chaque tier.

Ce qu'il faut regarder : en tier 0 le surcoût du décorateur est de l'ordre du
**nanoseconde** — c'est la même fonction, `probed()` l'a renvoyée telle quelle.
En tier 1 il passe à ~1.4 µs. D'où la règle de granularité : n'instrumenter que
des blocs d'au moins **400 µs**, soit une marge de ×280 sur le chiffre que ce
script imprime pour votre machine.

Le script échoue bruyamment si le surcoût tier 0 dépasse 50 ns : cela voudrait
dire que le chemin désactivé a régressé et qu'on paie l'instrumentation en
production.
"""

import os
import subprocess
import sys
from time import perf_counter

from utilities.probe import TIER, probe, probed, reset

CHILD_FLAG = "--child"
SEUIL_TIER0_NS = 50.0


def target():
    return None


decorated = probed("bench.decorated")(target)


def loop_bare(n, f=target):
    for _ in range(n):
        f()


def loop_decorated(n, f=decorated):
    for _ in range(n):
        f()


def loop_empty(n):
    for _ in range(n):
        pass


def loop_cm(n, p=probe):
    for _ in range(n):
        with p("bench.cm"):
            pass


def bench(fn, n, repeats=5):
    """ns par itération, meilleur run — le bruit ne fait qu'ajouter du temps."""
    best = float("inf")
    for _ in range(repeats):
        t0 = perf_counter()
        fn(n)
        best = min(best, perf_counter() - t0)
        reset()
    return best / n * 1e9


def child():
    n = {0: 300_000, 1: 50_000, 2: 20_000}[TIER]

    bare = bench(loop_bare, n)
    deco = bench(loop_decorated, n)
    empty = bench(loop_empty, n)
    cm = bench(loop_cm, n)

    print("  n=%d itérations par run, meilleur de 5" % n)
    print("  appel nu                  %8.1f ns" % bare)
    print("  appel décoré              %8.1f ns" % deco)
    print("  → surcoût décorateur      %8.1f ns" % (deco - bare))
    print("  boucle vide               %8.1f ns" % empty)
    print("  context manager           %8.1f ns" % cm)
    print("  → surcoût context manager %8.1f ns" % (cm - empty))

    if TIER == 0:
        surcout = deco - bare
        if surcout > SEUIL_TIER0_NS:
            print("\n  ALERTE : %.1f ns de surcoût en tier 0 (seuil %.0f ns)."
                  % (surcout, SEUIL_TIER0_NS))
            print("  Le chemin désactivé a régressé : probed() ne renvoie plus"
                  " la fonction inchangée.")
            return 1
        print("\n  OK : surcoût tier 0 sous les %.0f ns." % SEUIL_TIER0_NS)
    return 0


def parent():
    for tier in ("0", "1", "2"):
        print("\n" + "=" * 60)
        print("PROBE_TIER=%s" % tier)
        print("=" * 60)
        sys.stdout.flush()
        env = dict(os.environ, PROBE_TIER=tier)
        subprocess.run([sys.executable, __file__, CHILD_FLAG], env=env, check=True)


if __name__ == "__main__":
    if CHILD_FLAG in sys.argv:
        raise SystemExit(child())
    parent()
