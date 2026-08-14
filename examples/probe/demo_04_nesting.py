"""Temps propre contre temps cumulé : qui est vraiment coupable ?

    python examples/probe/demo_04_nesting.py

`outer` ne fait que déléguer à trois `inner`. Triée par `wall`, elle arrive en
tête du classement et donne l'impression d'être le problème. Son `self` — le
temps qui lui revient une fois retiré celui de ses enfants — est proche de
zéro : elle est innocente.

C'est l'équivalent du couple tottime/cumtime de cProfile. Sans cette colonne,
on passe une heure à optimiser une fonction qui ne fait qu'appeler les autres.

Ce qu'il faut regarder : les deux tris successifs. Le second, par `self`, donne
le vrai classement.
"""

import os
import subprocess
import sys
import time

if os.environ.get("PROBE_TIER") is None:
    raise SystemExit(subprocess.run(
        [sys.executable, __file__], env=dict(os.environ, PROBE_TIER="2")
    ).returncode)

from utilities.probe import probed, report  # noqa: E402


@probed("inner")
def inner():
    time.sleep(0.10)


@probed("outer")
def outer():
    """Pure délégation : aucun travail propre."""
    for _ in range(3):
        inner()


@probed("travail.propre")
def travail_propre():
    """Celui-là fait vraiment quelque chose."""
    return sum(i * i for i in range(2_000_000))


def main():
    outer()
    travail_propre()

    # print("--- trié par wall : `outer` domine, mais elle ne fait que déléguer")
    # print(report(rich=False, sort="wall"))

    # print("\n--- trié par self : le vrai classement")
    # print(report(rich=False, sort="self"))
    # print("\n`outer` a un self proche de zéro : tout son temps est celui de ses")
    # print("enfants. Le temps réellement dépensé est ailleurs.")


if __name__ == "__main__":
    main()
