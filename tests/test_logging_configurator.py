# tests/test_logging_configurator_basic.py
from __future__ import annotations
import json
import logging
import os
import re
from pathlib import Path
import time
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from utilities import LoggingConfigurator


# -----------------------
# Fixtures utilitaires
# -----------------------

@pytest.fixture(autouse=True)
def reset_logging_state():
    """
    Remet l'état du logging et du configurateur à zéro entre les tests.
    - Vide les handlers du root
    - Réinitialise les attributs de la classe LoggingConfigurator
    """
    # Avant test
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.WARNING)

    # Reset état interne de ta classe
    LoggingConfigurator.configured = False
    LoggingConfigurator._project = None
    LoggingConfigurator._log_dir = None
    LoggingConfigurator._console = None

    yield

    # Après test
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.WARNING)
    LoggingConfigurator.configured = False
    LoggingConfigurator._project = None
    LoggingConfigurator._log_dir = None
    LoggingConfigurator._console = None


# -----------------------
# Tests
# -----------------------

def test_config_creates_text_and_json_files(tmp_path: Path):
    LoggingConfigurator.configure(
        project="nav",
        level="DEBUG",
        base_dir=tmp_path,
        console=False,
        log_file=True,
        json_file=True,
        date_prefix_files=True,
    )

    log = logging.getLogger(__name__)
    log.debug("hello debug")
    log.info("hello info")

    text_file = tmp_path / "nav.log"
    json_file = tmp_path / "nav.jsonl"

    assert text_file.exists(), "Le fichier texte principal doit être créé"
    assert json_file.exists(), "Le fichier JSONL principal doit être créé"

    # contenu texte non vide
    txt = text_file.read_text(encoding="utf-8")
    assert "hello info" in txt or "hello debug" in txt

    # JSON valide
    lines = [l for l in json_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 1
    first = json.loads(lines[0])
    assert first["level"] in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert first["logger"]  # présent


def test_idempotent_no_duplicate_file_handlers(tmp_path: Path):
    LoggingConfigurator.configure(
        project="nav",
        level="INFO",
        base_dir=tmp_path,
        console=False,
        log_file=True,
        json_file=True,
    )
    root = logging.getLogger()

    def key(h):
        # clé d'unicité pour handler fichier rotatif
        return getattr(h, "baseFilename", None), h.__class__.__name__

    file_handlers_before = {key(h) for h in root.handlers if hasattr(h, "baseFilename")}

    # Re-configure : ne doit pas dupliquer
    LoggingConfigurator.configure(
        project="nav",
        level="DEBUG",
        base_dir=tmp_path,
        console=False,
        log_file=True,
        json_file=True,
    )
    root = logging.getLogger()
    file_handlers_after = {key(h) for h in root.handlers if hasattr(h, "baseFilename")}

    assert file_handlers_before == file_handlers_after, "La configuration doit être idempotente (pas de doublons)"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LOG_PROJECT", "envproj")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_JSON", "1")
    monkeypatch.setenv("LOG_CONSOLE", "0")

    # project=None car on force tout via ENV
    LoggingConfigurator.configure(project=None)

    root = logging.getLogger()
    assert root.level == logging.WARNING

    assert (tmp_path / "envproj.log").exists()
    assert (tmp_path / "envproj.jsonl").exists()


def test_watch_creates_module_file_and_writes(tmp_path: Path, capsys):
    # Pas besoin d'appeler configure() pour tester watch()
    LoggingConfigurator.watch(
        project="nav",
        module="nav.module.sub",
        level="DEBUG",
        base_dir=tmp_path,
        date_prefix_files=True,
        retention_days=7,
    )

    # Fichier attendu : <base_dir>/nav/module/sub/nav.nav.module.sub.log
    mod_dir = tmp_path / "nav" / "module" / "sub"
    mod_file = mod_dir / "nav.nav.module.sub.log"
    assert mod_file.exists(), f"Le fichier dédié du module doit exister: {mod_file}"

    # Écritures
    log = logging.getLogger("nav.module.sub")
    log.debug("trace fine")
    log.info("info sub")

    content = mod_file.read_text(encoding="utf-8")
    assert "trace fine" in content and "info sub" in content

    # Le print interne "Création du répertoire..." ne doit pas gêner, mais on capture au cas où
    _ = capsys.readouterr()


def test_rotation_namer_prefixes_date(tmp_path: Path):
    # Configure avec rotation + date_prefix_files=True pour le fichier principal
    LoggingConfigurator.configure(
        project="nav",
        level="INFO",
        base_dir=tmp_path,
        console=False,
        log_file=True,
        json_file=False,
        date_prefix_files=True,
    )

    root = logging.getLogger()
    # Récupère le handler fichier principal
    from logging.handlers import TimedRotatingFileHandler
    handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
    assert handlers, "Handler de fichier rotatif attendu"
    file_h = None
    for h in handlers:
        if Path(getattr(h, "baseFilename", "")).name == "nav.log":
            file_h = h
            break
    assert file_h is not None, "Handler rotatif principal 'nav.log' non trouvé"

    # Force un rollover (création d'une archive datée)
    file_h.doRollover()

    # Écrit un nouveau log pour s'assurer que nav.log se recrée
    logging.getLogger(__name__).info("post-rollover")
    time.sleep(0.01)

    # Cherche un fichier du type YYYYMMDD.nav.log
    pattern = re.compile(r"^\d{8}\.nav\.log$")
    archives = [p.name for p in tmp_path.iterdir() if p.is_file() and pattern.match(p.name)]
    assert archives, f"Aucune archive datée trouvée dans {tmp_path} (attendu: YYYYMMDD.nav.log)"


def test_json_formatter_strips_is_valid(tmp_path: Path):
    # On vérifie que le formatter JSONL donne du JSON valide même si message contient quotes/newlines
    LoggingConfigurator.configure(
        project="nav",
        level="INFO",
        base_dir=tmp_path,
        console=False,
        log_file=False,
        json_file=True,
    )

    log = logging.getLogger("nav.json.test")
    log.info('message "avec" des\nsauts de ligne')

    lines = [l for l in (tmp_path / "nav.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "Aucune ligne JSON produite"
    payload = json.loads(lines[-1])
    assert payload["msg"].startswith('message "avec" des')


def test_get_console_returns_console(tmp_path: Path):
    LoggingConfigurator.configure(
        project="nav",
        level="INFO",
        base_dir=tmp_path,
        console=True,
        log_file=False,
        json_file=False,
    )
    console = LoggingConfigurator.get_console()
    # Test minimal : l'objet existe et a une méthode print
    assert console is not None and hasattr(console, "print")
