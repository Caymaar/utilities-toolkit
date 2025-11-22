"""
Logging universel avec Rich + fichiers rotatifs.
Objectif: simplicité, pas de QueueHandler/Listener.

Usage global (root du projet) :
    from log_setup import LoggingConfigurator
    LoggingConfigurator.configure(project="trs_tools", level="INFO")

Surveiller un module/fichier spécifique (sans altérer le reste) :
    # Au tout début du fichier à surveiller
    from log_setup import LoggingConfigurator
    LoggingConfigurator.watch(project="trs_tools", module=__name__, level="DEBUG")

- `watch()` ajoute un handler dédié à *ce module* dans un sous-dossier
  de logs, sans toucher aux handlers déjà configurés (root, autres).
- Le logger du module continue à propager (propagate=True) donc ses
  messages suivent aussi les handlers globaux si existants.
- Les fichiers archivés sont préfixés par la date: YYYYMMDD.<base>.log|jsonl
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from rich.logging import RichHandler
    from rich.console import Console
    from rich.traceback import install as rich_traceback_install
except Exception as e:  # pragma: no cover
    raise ImportError("Installe 'rich' : pip install rich") from e

from utilities.constant import LOGS_PATH


# --------- Utilitaires de chemins ---------

def _default_log_root(project: str) -> Path:
    return Path(LOGS_PATH) / project


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _level_from_str(level: str) -> int:
    try:
        return getattr(logging, level.upper())
    except Exception:
        return logging.INFO


def _make_dated_namer(base_path: Path):
    """
    Renomme '.../<base>.log.YYYYMMDD' -> '.../YYYYMMDD.<base>.log'
    et '.../<base>.jsonl.YYYYMMDD' -> '.../YYYYMMDD.<base>.jsonl'.
    """
    base_dir = base_path.parent
    base_name = base_path.name  # ex: "trs_tools.log" ou "trs_tools.jsonl"

    def namer(default_name: str) -> str:
        # default_name ressemble à: "<base_path>.<YYYYMMDD>"
        default = Path(default_name)
        date_part = default.suffix.lstrip(".")  # "YYYYMMDD"
        return str(base_dir / f"{date_part}.{base_name}")

    return namer


# --------- Formatters ---------

class JsonLineFormatter(logging.Formatter):
    def __init__(self, *, static_fields: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.static_fields = static_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "pathname": record.pathname,
            "lineno": record.lineno,
            "func": record.funcName,
            "process": record.process,
            "thread": record.thread,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        payload.update(self.static_fields)
        return json.dumps(payload, ensure_ascii=False)


class ContextFilter(logging.Filter):
    def __init__(self, project: str):
        super().__init__()
        self.project = project

    def filter(self, record: logging.LogRecord) -> bool:
        record.project = self.project
        return True


# --------- Configurateur sans Queue ---------

@dataclass
class LoggingConfigurator:
    configured: bool = False
    _project: Optional[str] = None
    _log_dir: Optional[Path] = None
    _console: Optional[Console] = None

    @classmethod
    def configure(
        cls,
        *,
        project: Optional[str] = None,
        level: str = "INFO",
        base_dir: Optional[str | Path] = None,
        console: bool = True,
        log_file: bool = True,
        json_file: bool = False,
        retention_days: int = 14,
        backtrace: bool = True,
        show_locals: bool = False,
        date_prefix_files: bool = True,
    ) -> None:
        """
        Configure le root logger :
        - console (Rich)
        - fichier texte rotatif (journée)
        - option fichier jsonl rotatif
        Les fichiers archivés prennent le format YYYYMMDD.<project>.<ext>.
        """
        if cls.configured:
            return

        # -------- Env overrides --------
        project = os.environ.get("LOG_PROJECT", project)

        level = os.environ.get("LOG_LEVEL", level).upper()
        console = _env_bool("LOG_CONSOLE", console)

        if project is not None:
            json_file = _env_bool("LOG_JSON", json_file)
            retention_days = int(os.environ.get("LOG_RETENTION_DAYS", retention_days))

            base_dir_env = os.environ.get("LOG_DIR")
            if base_dir_env:
                base_dir = Path(base_dir_env)
            elif base_dir is None:
                base_dir = _default_log_root(project)
            else:
                base_dir = Path(base_dir)

            log_dir = Path(base_dir)
            _ensure_dir(log_dir)
        else:
            log_dir = Path(".")
            log_file = False
            json_file = False
            

            

        if backtrace:
            rich_traceback_install(show_locals=show_locals, width=None)

        # -------- Formatters / Filter partagés --------
        project_filter = ContextFilter(project or "unknown")
        plain_fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(project)s | %(name)s:%(lineno)d — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        json_fmt = JsonLineFormatter(static_fields={"project": project or "unknown"})

        # -------- Handlers concrets --------
        handlers: list[logging.Handler] = []

        if console:
            # utilise la console fournie ou en crée une
            rich_console =  cls._console or Console()
            cls._console = rich_console  # <-- mémorise pour réutiliser ailleurs

            rich_handler = RichHandler(
                console=rich_console,          # <-- on injecte la même console
                show_time=True,
                show_level=True,
                show_path=True,
                markup=True,
                rich_tracebacks=True,
                tracebacks_suppress=[logging],
            )
            rich_handler.setFormatter(logging.Formatter("%(message)s"))
            rich_handler.setLevel(level)
            rich_handler.addFilter(project_filter)
            handlers.append(rich_handler)

        # Fichier texte principal (actif: <project>.log ; archives: YYYYMMDD.<project>.log)
        if log_file:
            main_text_base = log_dir / f"{project}.log"
            file_text = TimedRotatingFileHandler(
                filename=str(main_text_base),
                when="midnight",
                backupCount=retention_days,
                encoding="utf-8",
                utc=True,
            )
            if date_prefix_files:
                file_text.suffix = "%Y%m%d"
                file_text.namer = _make_dated_namer(main_text_base)
            file_text.setLevel(level)
            file_text.setFormatter(plain_fmt)
            file_text.addFilter(project_filter)
            handlers.append(file_text)

        # Fichier JSONL principal (optionnel)
        if json_file:
            main_json_base = log_dir / f"{project}.jsonl"
            file_json = TimedRotatingFileHandler(
                filename=str(main_json_base),
                when="midnight",
                backupCount=retention_days,
                encoding="utf-8",
                utc=True,
            )
            if date_prefix_files:
                file_json.suffix = "%Y%m%d"
                file_json.namer = _make_dated_namer(main_json_base)
            file_json.setLevel(level)
            file_json.setFormatter(json_fmt)
            file_json.addFilter(project_filter)
            handlers.append(file_json)

        # ---- Root ----
        root = logging.getLogger()
        root.setLevel(level)
        for h in handlers:
            root.addHandler(h)

        cls._project = project
        cls._log_dir = log_dir
        cls.configured = True

    @staticmethod
    def log_dir_for(project: str, base_dir: Optional[str | Path] = None) -> Path:
        base_dir_env = os.environ.get("LOG_DIR")
        if base_dir_env:
            return Path(base_dir_env)
        if base_dir:
            return Path(base_dir)
        return _default_log_root(project)

    @classmethod
    def watch(
        cls,
        project: str,
        module: str,
        level: str = "DEBUG",
        *,
        base_dir: Optional[str | Path] = None,
        date_prefix_files: bool = True,
        retention_days: int = 14,
    ) -> None:
        """
        Ajoute un handler *dédié* (fichier) au logger `module`.
        - N'altère pas les handlers déjà présents sur le root (configure()).
        - Le logger du module reste propagate=True : ses messages suivent
          aussi les handlers globaux si présents.
        - Fichier dédié : logs/<project>/<module/en/arborescence>/ (actif)
            <project>.<module>.log
          Archives (rotation minuit) : YYYYMMDD.<project>.<module>.log
        """
        # Racine logs
        if base_dir is None:
            base_dir = LoggingConfigurator.log_dir_for(project)
        base_dir = Path(base_dir)
        # Répertoire dédié au module (arborescence selon nom de logger)
        mod_dir = base_dir / module.replace(".", "/")
        print(f"Création du répertoire de logs: {mod_dir}")
        _ensure_dir(mod_dir)

        # Chemin fichier
        mod_base_name = f"{project}.{module}.log"
        mod_file_base = mod_dir / mod_base_name

        # Formatter et filtre
        project_filter = ContextFilter(project)
        plain_fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(project)s | %(name)s:%(lineno)d — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Eviter d'ajouter plusieurs fois le *même* handler (multi-imports)
        logger_obj = logging.getLogger(module)
        target_filename = str(mod_file_base)
        for h in logger_obj.handlers:
            if isinstance(h, TimedRotatingFileHandler) and Path(getattr(h, "baseFilename", "")) == mod_file_base:
                # déjà présent
                return

        # Créer le handler dédié
        h = TimedRotatingFileHandler(
            filename=target_filename,
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
            utc=True,
        )
        if date_prefix_files:
            h.suffix = "%Y%m%d"
            h.namer = _make_dated_namer(mod_file_base)
        h.setLevel(_level_from_str(level))
        h.setFormatter(plain_fmt)
        h.addFilter(project_filter)

        # Attacher au logger du module (et NON au root)
        logger_obj.addHandler(h)
        # desired = _level_from_str(level)
        # current = logger_obj.level if logger_obj.level != logging.NOTSET else desired
        # if current > desired:
        logger_obj.setLevel(level)
        return logger_obj
    
    @classmethod
    def get_console(cls) -> Console:
        """Retourne la Console Rich utilisée par le logger, ou en crée une si absente."""
        return cls._console