# tests/test_log_frames.py
"""Tests des niveaux custom, de spark(), de log_frame() et du nettoyage ANSI.

Contrainte structurante : **tout ce fichier doit passer sans polars installé**.
Le duck-typing et les plafonds se testent sur un FakeFrame ; ce qui exige un
vrai moteur est marqué `importorskip`.
"""

import io
import logging
import os
import re
import sys

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
sys.path.append(SRC)

from utilities.log import (  # noqa: E402
    DATAFRAME,
    PERF,
    PLOT,
    AnsiStrippingFormatter,
    Lazy,
    log_frame,
    spark,
)
from utilities.log.setup import JsonLineFormatter, _level_from_str  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")


# -----------------------
# Fixtures
# -----------------------

class Capture(logging.Handler):
    """Handler qui garde les enregistrements, sans rien formater."""

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
    """Un logger isolé, réglé sur DATAFRAME, nettoyé après le test."""
    lg = logging.getLogger("test.frames.%d" % id(object()))
    lg.handlers = []
    lg.propagate = False
    lg.setLevel(DATAFRAME)
    capture = Capture()
    lg.addHandler(capture)
    lg.capture = capture  # type: ignore[attr-defined]
    yield lg
    lg.handlers = []


class FakeFrame:
    """Le contrat minimal attendu par log_frame, sans polars ni pandas."""

    def __init__(self, rows=1000, cols=3):
        self.shape = (rows, cols)
        self.columns = ["c%d" % i for i in range(cols)]
        self.appels = []

    def head(self, n):
        self.appels.append(("head", n))
        return _Rendu("HEAD(%d)" % n)

    def tail(self, n):
        self.appels.append(("tail", n))
        return _Rendu("TAIL(%d)" % n)

    def describe(self):
        self.appels.append(("describe",))
        return _Rendu("DESCRIBE")


class _Rendu:
    def __init__(self, texte):
        self.texte = texte

    def __str__(self):
        return self.texte


# -----------------------
# Niveaux
# -----------------------

def test_les_niveaux_sont_enregistres_et_resolus():
    assert (PLOT, DATAFRAME, PERF) == (6, 8, 15)
    assert logging.getLevelName(6) == "PLOT"
    assert logging.getLevelName(8) == "DATAFRAME"
    assert logging.getLevelName(15) == "PERF"
    # Résolution dans l'autre sens : c'est ce qui fait marcher setLevel("PLOT")
    assert logging.getLevelName("PLOT") == 6
    assert logging.getLevelName("DATAFRAME") == 8


def test_les_niveaux_sont_ordonnes_par_cout_croissant():
    assert PLOT < DATAFRAME < logging.DEBUG < PERF < logging.INFO


def test_setlevel_par_nom_et_level_from_str():
    lg = logging.getLogger("test.setlevel")
    lg.setLevel("DATAFRAME")
    assert lg.level == 8
    lg.setLevel("PLOT")
    assert lg.level == 6

    # _level_from_str alimente watch() : sans la résolution par getLevelName,
    # il retombait silencieusement sur INFO pour tout niveau custom.
    assert _level_from_str("PERF") == 15
    assert _level_from_str("DATAFRAME") == 8
    assert _level_from_str("plot") == 6
    assert _level_from_str("DEBUG") == 10
    assert _level_from_str("NIVEAU_INCONNU") == logging.INFO


def test_aucun_handler_ajoute_par_les_modules():
    for nom in ("utilities", "utilities.log", "utilities.log.frames",
                "utilities.log.plots"):
        lg = logging.getLogger(nom)
        assert lg.handlers == [], "%s porte un handler" % nom
        assert lg.level == logging.NOTSET, "%s a un niveau posé" % nom


# -----------------------
# spark
# -----------------------

def test_spark_longueur_exacte_et_sous_echantillonnage():
    assert len(spark(list(range(1000)), n=24)) == 24
    assert len(spark(list(range(1000)), n=8)) == 8
    assert len(spark([1, 2, 3])) == 3  # plus court que n : rendu tel quel


def test_spark_monotone_sur_entree_croissante():
    out = spark(list(range(100)), n=20)
    blocs = "▁▂▃▄▅▆▇█"
    indices = [blocs.index(c) for c in out]
    assert indices == sorted(indices), out
    assert out[0] == "▁" and out[-1] == "█"


def test_spark_conserve_les_deux_extremites():
    """Un pas fixe perdrait la queue dès que la longueur n'est pas multiple de n."""
    vals = [0.0] * 40 + [100.0]  # le pic est le tout dernier point
    assert spark(vals, n=8).endswith("█")


def test_spark_cas_degeneres():
    assert spark([]) == ""
    assert spark([42]) == "▁"
    assert spark([7, 7, 7, 7]) == "▁▁▁▁"  # série constante
    assert spark([1, 2, 3], n=0) == ""


def test_spark_ignore_les_valeurs_non_finies():
    assert spark([None, 1.0, float("nan"), 2.0, float("inf"), "x"]) == spark([1.0, 2.0])
    assert spark([None, None]) == ""


# -----------------------
# Lazy
# -----------------------

def test_lazy_nevalue_pas_si_le_niveau_est_eteint(log):
    def explose():
        raise AssertionError("évalué alors que le niveau est éteint")

    log.setLevel(logging.INFO)
    log.debug("%s", Lazy(explose))
    assert log.capture.records == []


def test_lazy_evalue_une_fois_traite(log):
    log.setLevel(logging.DEBUG)
    log.debug("valeur=%s", Lazy(lambda: 6 * 7))
    assert log.capture.messages == ["valeur=42"]


# -----------------------
# log_frame — garde de niveau
# -----------------------

def test_log_frame_ne_construit_rien_si_le_niveau_est_eteint(log):
    class Explose:
        shape = (10, 2)

        def __getattr__(self, nom):
            raise AssertionError("%s touché alors que le niveau est éteint" % nom)

    log.setLevel(logging.INFO)
    log_frame(log, Explose(), mode="describe")
    log_frame(log, Explose(), mode="full")
    assert log.capture.records == []


def test_log_frame_rejette_un_mode_inconnu(log):
    with pytest.raises(ValueError, match="mode='ohlc'"):
        log_frame(log, FakeFrame(), mode="ohlc")


# -----------------------
# log_frame — duck-typing sur FakeFrame
# -----------------------

def test_log_frame_head_et_tail_respectent_n(log):
    df = FakeFrame()
    log_frame(log, df, mode="head", n=7, label="f")
    log_frame(log, df, mode="tail", n=3, label="f")

    assert df.appels == [("head", 7), ("tail", 3)]
    assert "HEAD(7)" in log.capture.messages[0]
    assert "TAIL(3)" in log.capture.messages[1]
    assert "n=7" in log.capture.messages[0]


def test_log_frame_full_plafonne_et_signale_la_troncature(log):
    df = FakeFrame(rows=500_000, cols=3)
    log_frame(log, df, mode="full", label="gros", max_rows=200)

    assert df.appels == [("head", 200)], "full n'a pas borné sa tranche"
    message = log.capture.messages[0]
    assert "499800 lignes omises sur 500000" in message
    assert "max_rows=200" in message


def test_log_frame_full_ne_signale_rien_si_tout_tient(log):
    log_frame(log, FakeFrame(rows=12), mode="full", label="petit", max_rows=200)
    assert "omises" not in log.capture.messages[0]


def test_log_frame_signale_les_colonnes_omises(log):
    log_frame(log, FakeFrame(rows=5, cols=120), mode="head", max_cols=40)
    assert "80 colonnes omises sur 120" in log.capture.messages[0]


def test_log_frame_entete_porte_la_forme_et_le_label(log):
    log_frame(log, FakeFrame(rows=42, cols=3), mode="describe", label="positions")
    entete = log.capture.messages[0].splitlines()[0]
    assert entete.startswith("positions | 42 x 3 | mode=describe")


# -----------------------
# log_frame — LazyFrame
# -----------------------

class FakeLazy:
    """A `collect` et `explain` : c'est la signature d'un LazyFrame."""

    def __init__(self):
        self.collect_appele = False

    def collect(self):
        self.collect_appele = True
        raise AssertionError("collect() déclenché depuis un log")

    def explain(self):
        return "FILTER [(col('a')) > (10)]\nFROM\n  DF"


def test_log_frame_ne_materialise_jamais_un_lazyframe(log):
    lz = FakeLazy()
    for mode in ("head", "tail", "full", "describe"):
        log_frame(log, lz, mode=mode)

    assert lz.collect_appele is False
    assert len(log.capture.messages) == 4
    for message in log.capture.messages:
        assert "LazyFrame non matérialisé" in message
        assert "FILTER" in message


def test_log_frame_survit_a_un_explain_indisponible(log):
    class LazyCassee:
        def collect(self):
            raise AssertionError("collect() déclenché depuis un log")

        def explain(self):
            raise RuntimeError("plan indisponible")

    log_frame(log, LazyCassee())
    assert "explain() indisponible" in log.capture.messages[0]
    assert "RuntimeError" in log.capture.messages[0]


# -----------------------
# ANSI
# -----------------------

SEQUENCE = "\x1b[38;5;2mvert\x1b[0m et \x1b[1mgras\x1b[0m"


def _formate(formatter, message):
    record = logging.LogRecord("t", DATAFRAME, "p", 1, message, None, None)
    return formatter.format(record)


def test_ansi_retirees_du_texte_et_gardees_sans_le_formatter():
    brut = logging.Formatter("%(message)s")
    assert ANSI.findall(_formate(brut, SEQUENCE))
    assert not ANSI.findall(_formate(AnsiStrippingFormatter(brut), SEQUENCE))
    assert _formate(AnsiStrippingFormatter(brut), SEQUENCE) == "vert et gras"


def test_ansi_retirees_avant_le_dump_json():
    """json.dumps échappe \\x1b en \\u001b : nettoyer après coup ne marcherait pas."""
    sortie = _formate(AnsiStrippingFormatter(JsonLineFormatter()), SEQUENCE)

    assert "\\u001b" not in sortie, "les ANSI ont survécu sous forme échappée"
    assert not ANSI.findall(sortie)
    assert len(sortie.splitlines()) == 1


def test_ansi_le_record_nest_pas_mute():
    """Les autres handlers doivent continuer à voir leurs couleurs."""
    record = logging.LogRecord("t", DATAFRAME, "p", 1, SEQUENCE, None, None)
    AnsiStrippingFormatter(logging.Formatter("%(message)s")).format(record)
    assert record.getMessage() == SEQUENCE


def test_ansi_message_multiligne_reste_une_ligne_json():
    sortie = _formate(JsonLineFormatter(), "ligne1\nligne2\nligne3")
    import json

    assert len(sortie.splitlines()) == 1
    assert json.loads(sortie)["msg"] == "ligne1\nligne2\nligne3"


def test_configure_pose_le_formatter_sur_tous_les_handlers(tmp_path):
    """Fichier **et** console.

    Sur un fichier, une séquence ANSI est du bruit. Sur la console, RichHandler
    rend le message comme du texte et échappe les caractères de contrôle : la
    séquence n'y produit aucune couleur, seulement un « [0m » visible au milieu
    du graphe. La retirer des deux côtés ne perd donc rien.
    """
    from utilities.log.setup import LoggingConfigurator

    racine = logging.getLogger()
    handlers_avant = list(racine.handlers)
    niveau_avant = racine.level
    try:
        racine.handlers = []
        LoggingConfigurator.configured = False
        LoggingConfigurator.configure(
            project="essai_ansi", level="DATAFRAME", base_dir=tmp_path,
            console=True, log_file=True,
        )
        fichiers = [h for h in racine.handlers if hasattr(h, "baseFilename")]
        consoles = [h for h in racine.handlers if not hasattr(h, "baseFilename")]

        assert fichiers and consoles
        assert all(isinstance(h.formatter, AnsiStrippingFormatter)
                   for h in fichiers + consoles)
    finally:
        for h in racine.handlers:
            h.close()
        racine.handlers = handlers_avant
        racine.setLevel(niveau_avant)
        LoggingConfigurator.configured = False
        LoggingConfigurator._console = None


# -----------------------
# Avec polars (sauté s'il est absent)
# -----------------------

def test_polars_head_rend_le_repr_natif(log):
    pl = pytest.importorskip("polars")
    df = pl.DataFrame({"a": [1, 2, 3], "b": [0.5, 1.5, 2.5]})
    log_frame(log, df, mode="head", n=2, label="p")

    message = log.capture.messages[0]
    assert "shape: (2, 2)" in message
    assert "┌" in message, "le repr natif de polars n'a pas été utilisé"


def test_polars_lazyframe_non_materialise(log, monkeypatch):
    pl = pytest.importorskip("polars")
    df = pl.DataFrame({"a": list(range(100)), "b": list(range(100))})
    lz = df.lazy().filter(pl.col("a") > 10)

    def interdit(*a, **k):
        raise AssertionError("collect() déclenché depuis un log")

    monkeypatch.setattr(type(lz), "collect", interdit)
    log_frame(log, lz, label="plan")

    assert "LazyFrame non matérialisé" in log.capture.messages[0]
    assert "FILTER" in log.capture.messages[0]


def test_polars_config_restauree_meme_sur_exception(log):
    pl = pytest.importorskip("polars")

    reference = str(pl.DataFrame({"x": list(range(60))}))

    class RenduCasse:
        shape = (3, 1)
        columns = ["x"]

        def head(self, n):
            return self

        def __str__(self):
            raise RuntimeError("rendu cassé")

    with pytest.raises(RuntimeError, match="rendu cassé"):
        log_frame(log, RenduCasse(), mode="full", label="cassé")

    assert str(pl.DataFrame({"x": list(range(60))})) == reference


def test_polars_rich_rend_une_table(log):
    pytest.importorskip("polars")
    import polars as pl

    df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    log_frame(log, df, mode="head", n=2, label="p", rich=True)

    message = log.capture.messages[0]
    assert "┃" in message or "┏" in message, "pas de table Rich"
    assert not ANSI.findall(message), "la table Rich a été colorée"


def test_strip_ansi_false_laisse_les_formatters_nus(tmp_path):
    """L'échappatoire reste ouverte pour qui veut ses ANSI intactes."""
    from utilities.log.setup import LoggingConfigurator

    racine = logging.getLogger()
    handlers_avant = list(racine.handlers)
    niveau_avant = racine.level
    try:
        racine.handlers = []
        LoggingConfigurator.configured = False
        LoggingConfigurator.configure(
            project="essai_brut", level="DATAFRAME", base_dir=tmp_path,
            console=True, log_file=True, strip_ansi=False,
        )
        assert not any(isinstance(h.formatter, AnsiStrippingFormatter)
                       for h in racine.handlers)
    finally:
        for h in racine.handlers:
            h.close()
        racine.handlers = handlers_avant
        racine.setLevel(niveau_avant)
        LoggingConfigurator.configured = False
        LoggingConfigurator._console = None


def test_le_formatter_ne_rend_le_message_quune_seule_fois():
    """Un argument coûteux ne doit pas être calculé deux fois.

    Le formatter appelle `getMessage()` pour chercher les ANSI ; si le
    formatter interne le rappelait, un `Lazy` serait évalué deux fois — soit
    exactement ce à quoi il sert à ne pas faire.
    """
    from utilities.log.utils import Lazy

    appels = []

    def cher():
        appels.append(1)
        return "valeur"

    flux = io.StringIO()
    handler = logging.StreamHandler(flux)
    handler.setFormatter(AnsiStrippingFormatter(logging.Formatter("%(message)s")))

    log = logging.getLogger("essai.rendu.unique")
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.DEBUG)

    log.debug("x=%s", Lazy(cher))

    assert len(appels) == 1, "message rendu %d fois" % len(appels)
    assert flux.getvalue().strip() == "x=valeur"


def test_le_formatter_ne_mute_pas_l_enregistrement():
    """Un second handler doit continuer à voir le message d'origine."""
    propre, brut = io.StringIO(), io.StringIO()
    h_propre = logging.StreamHandler(propre)
    h_propre.setFormatter(AnsiStrippingFormatter(logging.Formatter("%(message)s")))
    h_brut = logging.StreamHandler(brut)
    h_brut.setFormatter(logging.Formatter("%(message)s"))

    log = logging.getLogger("essai.non.mute")
    log.handlers = [h_propre, h_brut]
    log.propagate = False
    log.setLevel(logging.DEBUG)

    log.debug("couleur \x1b[31mrouge\x1b[0m")

    assert "\x1b[" not in propre.getvalue()
    assert propre.getvalue().strip() == "couleur rouge"
    assert brut.getvalue().count("\x1b[") == 2


# -----------------------
# Mode notebook
# -----------------------

def _configure_isolee(**kwargs):
    """Configure sur un root vierge, et rend de quoi tout remettre en place."""
    from utilities.log.setup import LoggingConfigurator

    racine = logging.getLogger()
    etat = (list(racine.handlers), racine.level)
    racine.handlers = []
    LoggingConfigurator.configured = False
    LoggingConfigurator._console = None
    LoggingConfigurator.configure(**kwargs)
    return LoggingConfigurator, etat


def _restaurer(configurateur, etat):
    racine = logging.getLogger()
    for h in racine.handlers:
        h.close()
    racine.handlers, _ = etat
    racine.setLevel(etat[1])
    configurateur.configured = False
    configurateur._console = None


def test_in_notebook_est_faux_hors_dun_noyau():
    from utilities.log.setup import _in_notebook

    assert _in_notebook() is False


def test_mode_notebook_sort_du_rendu_html_de_rich():
    """Le cœur du problème : en mode Jupyter, Rich émet un display() HTML par
    enregistrement, donc un bloc de sortie par ligne de log."""
    from utilities.log.setup import NOTEBOOK_WIDTH

    conf, etat = _configure_isolee(level="INFO", console=True, notebook=True)
    try:
        console = conf.get_console()
        assert console.is_jupyter is False, "Rich rendrait en HTML bloc par bloc"
        assert console.is_terminal is True, "sans ça, plus aucune couleur"
        assert console.width == NOTEBOOK_WIDTH
    finally:
        _restaurer(conf, etat)


def test_mode_notebook_retire_la_colonne_de_chemin():
    """Dans un noyau, le chemin est le fichier temporaire de la cellule."""
    conf, etat = _configure_isolee(level="INFO", console=True, notebook=True)
    try:
        flux = io.StringIO()
        conf.get_console().file = flux
        logging.getLogger("essai.notebook").info("un message")
        sortie = flux.getvalue()
        assert "un message" in sortie
        assert "test_log_frames" not in sortie
    finally:
        _restaurer(conf, etat)


def test_hors_notebook_la_colonne_de_chemin_reste():
    conf, etat = _configure_isolee(level="INFO", console=True, notebook=False)
    try:
        flux = io.StringIO()
        conf.get_console().file = flux
        logging.getLogger("essai.terminal").info("un message")
        sortie = flux.getvalue()
        assert "un message" in sortie
        assert "test_log_frames" in sortie
    finally:
        _restaurer(conf, etat)


def test_console_width_explicite_gagne_sur_le_defaut_notebook():
    conf, etat = _configure_isolee(
        level="INFO", console=True, notebook=True, console_width=95
    )
    try:
        assert conf.get_console().width == 95
    finally:
        _restaurer(conf, etat)


def test_rich_table_ecrit_dans_son_tampon_et_naffiche_rien(log):
    """Rich bascule en mode Jupyter même avec un `file=`, et `print()` appelle
    alors `display()` sans rien écrire dans le tampon : la table s'afficherait
    hors du log et l'enregistrement partirait vide."""
    pl = pytest.importorskip("polars")

    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    log_frame(log, df, mode="head", n=2, label="t", rich=True)

    corps = log.capture.messages[0].split("\n", 1)[1]
    assert corps.strip(), "corps vide : le rendu Rich est parti ailleurs"
    assert "┏" in corps and "a" in corps and "b" in corps


def test_log_frame_retombe_sur_le_natif_si_le_rendu_rich_est_vide(log, monkeypatch):
    from utilities.log import frames

    monkeypatch.setattr(frames, "_rich_table", lambda *a, **k: "")
    log_frame(log, FakeFrame(), mode="head", n=2, label="t", rich=True)

    assert "HEAD(2)" in log.capture.messages[0]


# -----------------------
# Correctifs de revue
# -----------------------

def test_markup_desactive_sur_le_contenu_des_frames(log):
    """Une cellule vaut `[/bold]` : avec markup=True, la ligne de log lèverait."""
    log_frame(log, FakeFrame(), mode="head", n=2, label="f")
    assert log.capture.records[-1].markup is False


def test_un_richhandler_en_markup_ne_leve_pas_sur_du_contenu_de_frame():
    from rich.console import Console
    from rich.logging import RichHandler

    flux = io.StringIO()
    handler = RichHandler(
        console=Console(file=flux, width=120, force_terminal=True,
                        force_jupyter=False),
        markup=True,
    )
    lg = logging.getLogger("essai.markup")
    lg.handlers = [handler]
    lg.propagate = False
    lg.setLevel(DATAFRAME)

    class Piege(FakeFrame):
        def head(self, n):
            return _Rendu("cellule [/bold] et colonne ret[bps]")

    log_frame(lg, Piege(), mode="head", n=1, label="piege")   # ne doit pas lever

    sortie = ANSI.sub("", flux.getvalue())
    assert "[/bold]" in sortie, "le markup a mangé le contenu"
    assert "ret[bps]" in sortie


def test_describe_nest_pas_tronque_par_la_hauteur_de_la_source(log):
    """Le plafond de lignes suit la tranche rendue, pas le frame d'origine :
    un describe de 8 lignes sur un frame de 3 lignes était coupé à 3."""
    pl = pytest.importorskip("polars")

    df = pl.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    log_frame(log, df, mode="describe", label="petit")

    corps = log.capture.messages[0]
    for statistique in ("count", "mean", "std", "min", "max"):
        assert statistique in corps, "%s manquant : describe tronqué" % statistique


def test_describe_pandas_garde_ses_libelles_en_rich(log):
    """`itertuples(index=False)` perdait l'index, donc les libellés de
    statistiques : la table Rich n'était qu'une colonne de nombres."""
    pd = pytest.importorskip("pandas")

    df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    log_frame(log, df, mode="describe", label="petit", rich=True)

    corps = log.capture.messages[0]
    for statistique in ("count", "mean", "min", "max"):
        assert statistique in corps, "%s manquant" % statistique


def test_max_cols_sapplique_aussi_au_rendu_rich(log):
    pl = pytest.importorskip("polars")

    df = pl.DataFrame({"c%02d" % i: [i] for i in range(60)})
    log_frame(log, df, mode="head", n=1, label="large", max_cols=10, rich=True)

    corps = log.capture.messages[0]
    assert "c09" in corps
    assert "c10" not in corps, "les 60 colonnes ont été rendues"
    assert "50 colonnes omises sur 60" in corps
