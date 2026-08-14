# tests/test_probe.py
"""Tests du module utilities.probe.

Le tier est **figé à l'import** : c'est ce qui permet à `probed()` de ne poser
aucun wrapper en tier 0. Il ne peut donc pas être basculé dans un process déjà
démarré, et monkeypatcher `ENABLED` testerait autre chose que le comportement
réel. Tout ce qui dépend du tier tourne donc en sous-process, avec PROBE_TIER
dans l'environnement.
"""

import os
import subprocess
import sys
import textwrap

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
sys.path.append(SRC)

from utilities.probe import Probe, Stat  # noqa: E402
from utilities.probe.render import _text_table  # noqa: E402


# -----------------------
# Sous-process
# -----------------------

def run_probe(code, tier="1"):
    """Exécute `code` dans un process neuf avec le tier demandé.

    Le code enfant porte ses propres assertions : un échec remonte ici sous
    forme de returncode non nul, avec la traceback de l'enfant.
    """
    preamble = "import sys; sys.path.insert(0, %r)\n" % SRC
    res = subprocess.run(
        [sys.executable, "-c", preamble + textwrap.dedent(code)],
        env=dict(os.environ, PROBE_TIER=tier),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        "enfant (PROBE_TIER=%s) sorti en %d\n--- stdout ---\n%s\n--- stderr ---\n%s"
        % (tier, res.returncode, res.stdout, res.stderr)
    )
    return res.stdout


# -----------------------
# Tier 0 : coût nul
# -----------------------

def test_tier0_decorateur_renvoie_la_fonction_inchangee():
    """Identité stricte : pas d'équivalence, le même objet."""
    out = run_probe(
        """
        from utilities.probe import ENABLED, TIER, probed

        assert TIER == 0 and not ENABLED

        def f(a, b=2):
            return a + b

        assert probed()(f) is f, "un wrapper a été posé en tier 0"
        assert probed("label")(f) is f
        print("OK")
        """,
        tier="0",
    )
    assert "OK" in out


def test_tier0_context_manager_nalloue_pas():
    """Le chemin désactivé est un singleton, pas une Probe par entrée."""
    out = run_probe(
        """
        from utilities.probe import probe, registry

        with probe("a") as p1:
            pass
        with probe("b") as p2:
            pass

        assert p1 is p2, "une Probe est allouée par entrée en tier 0"
        assert probe("a") is probe("b"), "le no-op n'est pas un singleton"
        assert registry == {}, "le tier 0 a enregistré des mesures"
        print("OK")
        """,
        tier="0",
    )
    assert "OK" in out


def test_tier0_ne_rend_rien():
    out = run_probe(
        """
        from utilities.probe import probe, report

        with probe("rien"):
            pass
        assert report(rich=False) == ""
        print("OK")
        """,
        tier="0",
    )
    assert "OK" in out


# -----------------------
# Tier 1 : temps
# -----------------------

def test_tier1_wall_coherent_avec_un_sleep_connu():
    run_probe(
        """
        import time
        from utilities.probe import probe, registry

        with probe("dodo"):
            time.sleep(0.20)

        s = registry["dodo"]
        assert s.n == 1
        assert 0.14 <= s.wall_s <= 0.26, s.wall_s
        """
    )


def test_tier1_wait_discrimine_io_et_cpu():
    run_probe(
        """
        import time
        from utilities.probe import probe, registry

        with probe("io"):
            time.sleep(0.20)
        with probe("cpu"):
            sum(i * i for i in range(3_000_000))

        io, cpu = registry["io"], registry["cpu"]

        # Sur du sleep, tout le temps est de l'attente.
        assert io.wait_s > 0.9 * io.wall_s, (io.wait_s, io.wall_s)
        # Sur du calcul, il y en a peu. Tolérance large et assumée : `cpu_s`
        # est du temps CPU **du thread**, donc une machine chargée qui
        # déprogramme le thread gonfle `wall` sans gonfler `cpu`. Ce qui
        # compte ici est l'écart entre les deux blocs, pas la valeur absolue.
        assert cpu.wait_s < 0.6 * cpu.wall_s, (cpu.wait_s, cpu.wall_s)
        assert io.wait_s / io.wall_s > 2 * (cpu.wait_s / cpu.wall_s) or cpu.wait_s <= 0
        """
    )


def test_tier1_imbrication_self_egale_wall_moins_enfants():
    run_probe(
        """
        import time
        from utilities.probe import probe, registry

        with probe("parent"):
            for _ in range(3):
                with probe("enfant"):
                    time.sleep(0.05)
            time.sleep(0.05)

        parent, enfant = registry["parent"], registry["enfant"]
        assert enfant.n == 3

        attendu = parent.wall_s - enfant.wall_s
        assert abs(parent.self_s - attendu) < 0.01, (parent.self_s, attendu)
        # Le parent ne fait pas que déléguer : il lui reste son propre sleep.
        assert 0.03 < parent.self_s < 0.08, parent.self_s
        """
    )


def test_tier1_pure_delegation_donne_un_self_nul():
    run_probe(
        """
        import time
        from utilities.probe import probed, registry

        @probed("inner")
        def inner():
            time.sleep(0.05)

        @probed("outer")
        def outer():
            for _ in range(3):
                inner()

        outer()

        outer_s = registry["outer"]
        assert outer_s.wall_s > 0.13, outer_s.wall_s
        assert outer_s.self_s < 0.01, outer_s.self_s
        """
    )


def test_tier1_registry_agrege_sur_n_appels():
    run_probe(
        """
        import time
        from utilities.probe import probe, registry

        for _ in range(5):
            with probe("boucle"):
                time.sleep(0.01)

        s = registry["boucle"]
        assert len(registry) == 1
        assert s.n == 5
        assert 0.04 < s.wall_s < 0.12, s.wall_s
        assert abs(s.mean_s - s.wall_s / 5) < 1e-12
        """
    )


def test_tier1_exception_mesuree_et_propagee_intacte():
    run_probe(
        """
        import time
        from utilities.probe import probe, registry

        class Boum(Exception):
            pass

        sentinelle = Boum("message intact")
        try:
            with probe("qui.leve"):
                time.sleep(0.02)
                raise sentinelle
        except Boum as e:
            assert e is sentinelle, "l'exception a été remplacée"
        else:
            raise AssertionError("l'exception a été avalée par le probe")

        s = registry["qui.leve"]
        assert s.n == 1, "la mesure n'a pas été enregistrée"
        assert s.wall_s > 0.01, s.wall_s
        """
    )


def test_tier1_reset_vide_le_registry():
    run_probe(
        """
        from utilities.probe import probe, registry, reset

        with probe("a"):
            pass
        assert registry
        reset()
        assert registry == {}

        with probe("b"):
            pass
        assert list(registry) == ["b"]
        """
    )


# -----------------------
# Concurrence
# -----------------------

def test_tier1_async_attribution_sous_gather():
    run_probe(
        """
        import asyncio, time
        from utilities.probe import probed, registry

        @probed("fetch")
        async def fetch(n):
            await asyncio.sleep(0.15)
            return n

        async def main():
            return await asyncio.gather(*(fetch(i) for i in range(3)))

        t0 = time.perf_counter()
        assert asyncio.run(main()) == [0, 1, 2], "le résultat a été altéré"
        reel = time.perf_counter() - t0

        s = registry["fetch"]
        assert s.n == 3
        # Chaque coroutine mesure bien sa propre durée...
        assert 0.12 < s.mean_s < 0.25, s.mean_s
        # ...et la somme dépasse le temps réel : c'est de la concurrence.
        assert s.wall_s > reel * 2, (s.wall_s, reel)
        """
    )


def test_tier1_aucun_increment_perdu_entre_threads():
    """`n += 1` est un LOAD/ADD/STORE : sans verrou, les mesures s'écrasent.

    Aux paramètres ci-dessous, la version non verrouillée perd ~45 % des
    incréments. Un échec ici veut dire que le verrou du registry a sauté.
    """
    run_probe(
        """
        import sys, threading
        from utilities.probe import probe, registry

        sys.setswitchinterval(1e-6)  # maximise les changements de thread

        N_THREADS, N_TOURS = 6, 1500

        def travail():
            for _ in range(N_TOURS):
                with probe("chaud"):
                    pass

        ts = [threading.Thread(target=travail) for _ in range(N_THREADS)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        attendu = N_THREADS * N_TOURS
        s = registry["chaud"]
        assert s.n == attendu, "%d incréments perdus sur %d" % (attendu - s.n, attendu)
        assert len(registry) == 1, "plusieurs Stat créés pour le même label"
        """
    )


def test_tier1_rendu_concurrent_dune_mesure_en_cours():
    """Itérer sur le registry pendant qu'un thread y insère ne doit pas lever.

    Sans instantané sous verrou : « dictionary changed size during iteration ».
    """
    run_probe(
        """
        import threading
        from utilities.probe import probe, report, to_dicts

        N_LABELS = 1500

        def mesure():
            for i in range(N_LABELS):
                with probe("label.%04d" % i):  # une clé neuve à chaque tour
                    pass

        t = threading.Thread(target=mesure)
        t.start()
        try:
            for _ in range(40):
                report(rich=False)
                to_dicts()
        finally:
            t.join()
        """
    )


def test_tier1_recursion_instances_distinctes_et_self_juste():
    run_probe(
        """
        import time
        from utilities.probe import probe, registry

        vus = []

        def recursif(niveau):
            with probe("recursif") as p:
                vus.append(id(p))
                time.sleep(0.05)
                if niveau:
                    recursif(niveau - 1)

        recursif(2)  # trois niveaux imbriqués

        assert len(set(vus)) == 3, "une Probe a été réutilisée entre deux niveaux"

        s = registry["recursif"]
        assert s.n == 3
        # wall compte chaque niveau, donc le temps imbriqué plusieurs fois :
        # 0.15 (externe) + 0.10 + 0.05 = 0.30
        assert 0.25 < s.wall_s < 0.42, s.wall_s
        # self ne compte chaque instant qu'une fois : 3 x 0.05 = 0.15
        assert 0.12 < s.self_s < 0.22, s.self_s
        """
    )


def test_tier1_recursion_sur_fonction_decoree():
    run_probe(
        """
        import time
        from utilities.probe import probed, registry

        @probed("fact")
        def fact(n):
            time.sleep(0.02)
            return 1 if n <= 1 else n * fact(n - 1)

        assert fact(4) == 24, "le résultat a été altéré par le décorateur"

        s = registry["fact"]
        assert s.n == 4
        assert 0.06 < s.self_s < 0.16, s.self_s
        """
    )


def test_tier1_threads_pas_de_fuite_de_contexte():
    run_probe(
        """
        import threading, time
        from utilities.probe import probe, registry

        def avec_enfant():
            with probe("t1.parent"):
                with probe("t1.enfant"):
                    time.sleep(0.15)

        def sans_enfant():
            with probe("t2.seul"):
                time.sleep(0.15)

        ts = [threading.Thread(target=avec_enfant), threading.Thread(target=sans_enfant)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        seul = registry["t2.seul"]
        parent = registry["t1.parent"]

        # Le thread sans enfant ne doit rien s'être fait retirer par l'autre.
        assert abs(seul.self_s - seul.wall_s) < 0.01, (seul.self_s, seul.wall_s)
        # Celui qui en a un voit bien son self tomber à zéro.
        assert parent.self_s < 0.01, parent.self_s
        """
    )


# -----------------------
# Logging
# -----------------------

def test_aucun_record_emis_si_le_niveau_perf_nest_pas_ecoute():
    run_probe(
        """
        import logging
        from utilities.probe import PERF, probe

        class Compteur(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records = []
            def emit(self, record):
                self.records.append(record)

        assert PERF == 15
        log = logging.getLogger("utilities.probe")
        assert log.handlers == [], "le module a posé un handler sur son logger"

        compteur = Compteur()
        log.addHandler(compteur)

        # Niveau au-dessus de PERF : rien ne doit être émis.
        log.setLevel(logging.INFO)
        assert not log.isEnabledFor(PERF)
        with probe("muet"):
            pass
        assert compteur.records == [], "un LogRecord a été émis à tort"

        # Niveau PERF : la mesure est loguée.
        log.setLevel(PERF)
        with probe("bavard"):
            pass
        assert len(compteur.records) == 1
        rec = compteur.records[0]
        assert rec.levelname == "PERF"
        assert "bavard" in rec.getMessage()
        assert rec.probe.label == "bavard"
        """
    )


def test_le_module_ne_configure_pas_le_logging_de_lhote():
    """Une bibliothèque enregistre un niveau ; elle ne configure pas son hôte."""
    run_probe(
        """
        import logging
        root_avant = list(logging.getLogger().handlers)
        niveau_avant = logging.getLogger().level

        appels = []
        vrai_basic_config = logging.basicConfig
        logging.basicConfig = lambda *a, **k: appels.append(("basicConfig", a, k))

        import utilities.probe  # noqa: F401
        import utilities.log.levels  # noqa: F401

        logging.basicConfig = vrai_basic_config

        assert appels == [], "basicConfig a été appelé : %r" % (appels,)

        root = logging.getLogger()
        assert list(root.handlers) == root_avant, "un handler a été ajouté au root"
        assert root.level == niveau_avant, "le niveau du root a été modifié"

        for nom in ("utilities", "utilities.probe", "utilities.log"):
            log = logging.getLogger(nom)
            assert log.handlers == [], "%s porte un handler : %r" % (nom, log.handlers)
            assert log.level == logging.NOTSET, "%s a un niveau posé" % nom
        """
    )


def test_levels_enregistre_le_nom_sans_ecraser_un_niveau_existant():
    run_probe(
        """
        import logging

        # Un autre paquet a déjà revendiqué 15 avant nous.
        logging.addLevelName(15, "AUTRE_PAQUET")

        from utilities.log.levels import PERF

        assert PERF == 15
        assert logging.getLevelName(15) == "AUTRE_PAQUET", (
            "utilities.log.levels a écrasé le nom d'un autre paquet"
        )
        """
    )


# -----------------------
# Tier 2 : mémoire
# -----------------------

def test_tier2_alloc_kib_positif_sur_une_allocation_retenue():
    run_probe(
        """
        import tracemalloc
        from utilities.probe import TIER, probe, registry

        assert TIER == 2
        assert tracemalloc.is_tracing(), "tracemalloc n'a pas été démarré"

        with probe("retient") as p:
            garde = [i for i in range(300_000)]

        # ~8 Mio pour 300k entiers : on se contente d'un ordre de grandeur.
        assert p.alloc_kib > 1000, p.alloc_kib
        assert registry["retient"].alloc_kib == p.alloc_kib
        del garde
        """,
        tier="2",
    )


def test_tier2_colonne_alloc_presente_dans_la_table():
    out = run_probe(
        """
        from utilities.probe import probe, report

        with probe("x"):
            pass
        print(report(rich=False))
        """,
        tier="2",
    )
    assert "alloc" in out

    out_tier1 = run_probe(
        """
        from utilities.probe import probe, report

        with probe("x"):
            pass
        print(report(rich=False))
        """
    )
    assert "alloc" not in out_tier1


# -----------------------
# Modèle et rendu — purs, testables en process
# -----------------------

def test_quantile_sur_une_distribution_connue():
    s = Stat("q")
    for v in range(1, 101):  # 1..100 ms
        s.add(Probe("q", wall_s=v / 1000.0))

    assert s.n == 100
    assert s.quantile(0.95) == pytest.approx(0.095)
    assert s.quantile(0.5) == pytest.approx(0.050)
    assert s.quantile(1.0) == pytest.approx(0.100)
    assert s.quantile(0.0) == pytest.approx(0.001)


def test_quantile_sur_registry_vide():
    assert Stat("vide").quantile(0.95) == 0.0
    assert Stat("vide").mean_s == 0.0


def test_stat_agrege_les_champs():
    s = Stat("agg")
    s.add(Probe("agg", wall_s=1.0, cpu_s=0.4, self_s=0.9, alloc_kib=10.0))
    s.add(Probe("agg", wall_s=3.0, cpu_s=1.0, self_s=2.0, alloc_kib=5.0))

    assert (s.n, s.wall_s, s.cpu_s, s.self_s, s.alloc_kib) == (2, 4.0, 1.4, 2.9, 15.0)
    assert s.wait_s == pytest.approx(2.6)
    assert s.mean_s == pytest.approx(2.0)


def test_probe_wait_est_wall_moins_cpu():
    p = Probe("w", wall_s=1.0, cpu_s=0.25)
    assert p.wait_s == pytest.approx(0.75)


def test_report_rejette_un_tri_inconnu():
    from utilities.probe import report

    with pytest.raises(ValueError, match="sort='cpu'"):
        report(sort="cpu", rich=False)


def test_text_table_aligne_et_tronque_les_labels():
    s = Stat("x" * 60)
    s.add(Probe("x" * 60, wall_s=1.5, cpu_s=0.5, self_s=1.5))
    lignes = _text_table([s], mem=False).splitlines()

    assert len(lignes) == 3  # en-tête, séparateur, une ligne
    assert len(lignes[0]) == len(lignes[2]), "colonnes désalignées"
    assert lignes[2].startswith("x" * 34 + " ")


def test_report_sans_stream_ni_rich_nimprime_rien(capsys):
    from utilities.probe import report, reset

    reset()  # au cas où PROBE_TIER serait positionné dans l'environnement
    assert report(rich=False) == ""
    assert capsys.readouterr().out == ""


# -----------------------
# Coût d'import
# -----------------------

def test_import_du_module_reste_leger():
    """Le coût propre de utilities.probe, hors dépendances déjà chargées.

    `import utilities` coûte ~0.5 s à lui seul (rich, création des dossiers de
    config) : c'est préexistant et hors du périmètre de ce module. Ce qu'on
    vérifie ici, c'est que `probe` n'y ajoute rien de significatif.
    """
    res = subprocess.run(
        [sys.executable, "-X", "importtime", "-c",
         "import sys; sys.path.insert(0, %r); import utilities.probe" % SRC],
        env=dict(os.environ, PROBE_TIER="0"),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr

    propre_us = 0
    for ligne in res.stderr.splitlines():
        # "import time:  self [us] | cumulative | imported package"
        champs = ligne.split("|")
        if len(champs) == 3 and champs[2].strip() in (
            "utilities.probe", "utilities.probe.core",
            "utilities.probe.render", "utilities.log.levels",
        ):
            propre_us += int(champs[0].split(":")[1].strip())

    assert propre_us > 0, "aucune ligne importtime trouvée:\n%s" % res.stderr
    assert propre_us < 5000, "coût propre de utilities.probe : %d us" % propre_us


# -----------------------
# Correctifs de revue
# -----------------------

def test_le_sous_module_probe_nest_pas_masque_par_la_fonction():
    """`from utilities.probe import probe` dans le __init__ du paquet lierait
    la fonction sur l'attribut `utilities.probe`, détruisant le module."""
    import types

    import utilities
    import utilities.probe.render

    assert isinstance(utilities.probe, types.ModuleType)
    assert utilities.probe.render.report is not None
    assert "probe" not in utilities.__all__, "le CM masquerait le sous-module"
    assert {"probed", "report"} <= set(utilities.__all__)


def test_cpu_est_compte_par_thread_et_non_par_process():
    """Avec `process_time`, un bloc qui dort pendant que d'autres threads
    calculent affiche wait ≈ 0 : l'inverse exact du diagnostic."""
    run_probe(
        """
        import threading, time
        from utilities.probe import probe, registry

        stop = threading.Event()

        def brule():
            while not stop.is_set():
                sum(i * i for i in range(10_000))

        fils = [threading.Thread(target=brule) for _ in range(2)]
        for f in fils:
            f.start()
        try:
            with probe("je.dors"):
                time.sleep(0.30)
        finally:
            stop.set()
            for f in fils:
                f.join()

        s = registry["je.dors"]
        # Le CPU brûlé par les autres threads ne doit pas m'être imputé.
        assert s.cpu_s < 0.05, "cpu du process compté : %.3f" % s.cpu_s
        assert s.wait_s > 0.9 * s.wall_s, (s.wait_s, s.wall_s)
        """
    )


def test_reset_permet_de_reimprimer_le_meme_nombre_dappels():
    run_probe(
        """
        import io, time
        from utilities.probe import probe, report, reset
        from utilities.probe.render import _report_at_exit

        with probe("a"):
            time.sleep(0.01)
        report(rich=False)          # mémorise « 1 appel déjà rendu »

        reset()
        with probe("b"):            # exactement 1 appel, à nouveau
            time.sleep(0.01)

        flux = io.StringIO()
        import sys
        vrai = sys.stderr
        sys.stderr = flux
        try:
            _report_at_exit()
        finally:
            sys.stderr = vrai

        assert "b" in flux.getvalue(), "le rendu de fin de process a été avalé"
        """
    )
