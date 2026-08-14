# tests/test_log_plots.py
"""Tests des helpers de graphes.

`plotext` est une dépendance **optionnelle** : ce fichier doit passer sans lui.
Les tests qui ont besoin du vrai moteur sont marqués `importorskip` ; ceux qui
vérifient les garde-fous tournent dans les deux cas — et le plus important
d'entre eux, « rien n'est construit si le niveau est éteint », se prouve
justement mieux quand plotext est absent.
"""

import logging
import os
import re
import sys
import threading

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
sys.path.append(SRC)

from utilities.log import PLOT  # noqa: E402
from utilities.log.plots import (  # noqa: E402
    HEIGHT,
    WIDTH,
    plot_bar,
    plot_hist,
    plot_line,
    plot_scatter,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")

YS = [i * i for i in range(60)]
XS = list(range(60))


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    @property
    def messages(self):
        return [r.getMessage() for r in self.records]


@pytest.fixture
def log():
    lg = logging.getLogger("test.plots.%d" % id(object()))
    lg.handlers = []
    lg.propagate = False
    lg.setLevel(PLOT)
    capture = Capture()
    lg.addHandler(capture)
    lg.capture = capture  # type: ignore[attr-defined]
    yield lg
    lg.handlers = []


# -----------------------
# Garde de niveau — sans plotext
# -----------------------

def test_rien_nest_construit_si_le_niveau_est_eteint(log, monkeypatch):
    """plotext rendu introuvable : si un helper y touche, le test échoue.

    `sys.modules[nom] = None` fait lever `import nom`, ce qui simule l'absence
    du paquet même quand il est installé.
    """
    monkeypatch.setitem(sys.modules, "plotext", None)
    log.setLevel(logging.DEBUG)  # 10, au-dessus de PLOT (6)

    plot_line(log, YS, title="ne doit rien faire")
    plot_scatter(log, XS, YS, title="idem")
    plot_hist(log, YS, title="idem")
    plot_bar(log, ["a", "b"], [1, 2], title="idem")

    assert log.capture.records == []


def test_message_actionnable_si_plotext_absent(log, monkeypatch):
    monkeypatch.setitem(sys.modules, "plotext", None)

    with pytest.raises(RuntimeError) as exc:
        plot_line(log, YS, title="x")

    message = str(exc.value)
    assert "plotext n'est pas installé" in message
    assert "utilities-toolkit[plot]" in message
    assert "spark()" in message, "l'alternative sans dépendance n'est pas proposée"
    assert isinstance(exc.value.__cause__, ImportError)


# -----------------------
# Avec plotext
# -----------------------

def test_les_quatre_helpers_emettent_au_niveau_plot(log):
    pytest.importorskip("plotext")

    plot_line(log, YS, title="ligne")
    plot_scatter(log, XS, YS, title="nuage")
    plot_hist(log, YS, bins=10, title="distribution")
    plot_bar(log, ["a", "b", "c"], [3, 1, 2], title="barres")

    assert len(log.capture.records) == 4
    assert {r.levelno for r in log.capture.records} == {PLOT}
    assert {r.levelname for r in log.capture.records} == {"PLOT"}
    for titre, message in zip(("ligne", "nuage", "distribution", "barres"),
                              log.capture.messages):
        assert message.startswith(titre)
        assert len(message.splitlines()) > 5, "graphe vide"


def test_plot_line_accepte_un_axe_x(log):
    pytest.importorskip("plotext")

    plot_line(log, YS, x=[v / 2 for v in XS], title="avec x")
    assert log.capture.messages[0].startswith("avec x")


def test_la_taille_est_figee_quel_que_soit_le_terminal(log):
    """Sans plotsize() explicite, la sortie dépendrait du terminal détecté."""
    pytest.importorskip("plotext")

    plot_line(log, YS, title="a")
    plot_line(log, [1, 5, 2], title="b")

    tailles = []
    for message in log.capture.messages:
        lignes = ANSI.sub("", message).splitlines()[1:]  # sans la ligne de titre
        tailles.append((len(lignes), max(len(ligne) for ligne in lignes)))

    assert tailles[0] == tailles[1], "la taille varie d'un appel à l'autre"
    assert tailles[0][0] == HEIGHT
    assert tailles[0][1] <= WIDTH + 2


def test_le_titre_vide_reste_lisible(log):
    pytest.importorskip("plotext")

    plot_line(log, YS)
    assert log.capture.messages[0].startswith("(sans titre)")


def test_plots_concurrents_ne_se_melangent_pas(log):
    """plotext travaille sur une figure **globale** : `clf`, `plot` et `build`
    partagent un état unique.

    Aux paramètres ci-dessous, la version sans verrou lève 11 fois sur 72
    (`dictionary changed size during iteration` à l'intérieur de plotext), rend
    des titres appartenant à un autre thread et des graphes tronqués. Un échec
    ici veut dire que le verrou de `utilities.log.plots` a sauté.
    """
    pytest.importorskip("plotext")

    N_THREADS, N_TOURS = 12, 6
    erreurs = []

    def tracer(i):
        try:
            for _ in range(N_TOURS):
                plot_line(log, [v + i for v in YS], title="t%02d" % i)
        except Exception as exc:
            erreurs.append(exc)

    intervalle = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # maximise les changements de thread
    try:
        threads = [threading.Thread(target=tracer, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(intervalle)

    assert erreurs == [], "%d exception(s), la première : %r" % (len(erreurs), erreurs[:1])
    assert len(log.capture.records) == N_THREADS * N_TOURS

    for message in log.capture.messages:
        titre = message.splitlines()[0]
        lignes = ANSI.sub("", message).splitlines()[1:]
        assert re.fullmatch(r"t\d\d", titre), titre
        assert len(lignes) == HEIGHT, "graphe tronqué ou concaténé à un autre"
        # Le titre dessiné dans le cadre doit être celui de cet appel-là.
        assert titre in "".join(lignes), "titre d'un autre thread dans le graphe"
