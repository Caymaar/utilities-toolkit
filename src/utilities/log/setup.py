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

import copy
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
import datetime as dt
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Union

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


#: Largeur par défaut dans un notebook, où il n'y a pas de terminal à
#: interroger. Assez pour un graphe plotext (72) plus la gouttière de
#: RichHandler (~29) une fois la colonne de chemin retirée.
NOTEBOOK_WIDTH = 120


def _in_notebook() -> bool:
    """Vrai dans un noyau Jupyter (notebook, Lab, VS Code), faux ailleurs.

    Ne coûte qu'un accès à `sys.modules` quand IPython n'est pas là, et
    n'importe jamais IPython. Une console IPython dans un terminal répond
    faux : c'est bien un terminal, le rendu normal lui convient.
    """
    ipython = sys.modules.get("IPython")
    if ipython is None:
        return False
    try:
        shell = ipython.get_ipython()
    except Exception:  # pragma: no cover - API IPython inattendue
        return False
    return shell is not None and type(shell).__name__ == "ZMQInteractiveShell"


def _level_from_str(level: str) -> int:
    """Résout un nom de niveau, **y compris les niveaux custom du package**.

    `getattr(logging, "PERF")` n'existe pas : seuls les niveaux standard sont
    des attributs du module. `getLevelName` fait la traduction inverse pour tout
    niveau passé par `addLevelName`, donc pour PERF, DATAFRAME et PLOT.
    """
    resolved = logging.getLevelName(level.upper())
    if isinstance(resolved, int):
        return resolved
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
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat() + "Z",
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


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class AnsiStrippingFormatter(logging.Formatter):
    """Enveloppe un formatter et retire les séquences ANSI du **message**.

    `plotext.build()` en émet même sous `theme("clear")` — un `\\x1b[0m` en fin
    de chaque ligne, vérifié. Souhaitable sur un terminal, illisible dans un
    fichier. Ce n'est donc pas à l'émetteur de trancher : c'est une propriété du
    handler, et ce formatter est posé sur les handlers fichier uniquement.

    Le nettoyage porte sur le message et non sur la sortie formatée, parce que
    `json.dumps` transforme `\\x1b` en `\\u001b` : sur la sortie d'un
    `JsonLineFormatter`, la regex ne trouverait plus rien.

    L'enregistrement n'est jamais muté — les autres handlers doivent continuer
    à voir leurs couleurs — mais il est **remplacé par une copie portant le
    message déjà rendu**, y compris quand il n'y a aucune ANSI à retirer. Sans
    ça, `getMessage()` serait appelé deux fois : une fois ici pour chercher les
    séquences, une fois par le formatter interne. Un argument `Lazy` serait
    alors calculé deux fois, ce qui ruinerait exactement ce à quoi il sert.
    """

    def __init__(self, inner: logging.Formatter):
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        propre = copy.copy(record)
        propre.msg = _ANSI.sub("", record.getMessage())
        propre.args = ()
        return self.inner.format(propre)


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
        base_dir: Optional[Union[str, Path]] = None,
        console: bool = True,
        log_file: bool = True,
        json_file: bool = False,
        retention_days: int = 14,
        backtrace: bool = True,
        show_locals: bool = False,
        date_prefix_files: bool = True,
        strip_ansi: bool = True,
        console_width: Optional[int] = None,
        notebook: Optional[bool] = None,
    ) -> None:
        """
        Configure le root logger :
        - console (Rich)
        - fichier texte rotatif (journée)
        - option fichier jsonl rotatif
        Les fichiers archivés prennent le format YYYYMMDD.<project>.<ext>.

        `level` accepte les niveaux custom du package : "PERF", "DATAFRAME",
        "PLOT", en plus des niveaux standard.

        `strip_ansi` retire les séquences ANSI des messages. Sur les fichiers
        parce qu'un flux de fichier n'est pas un terminal ; sur la console
        parce que RichHandler les échappe en texte visible au lieu de les
        interpréter.

        `console_width` fixe la largeur de la console Rich au lieu de la
        déduire du terminal. Nécessaire pour les sorties en bloc : un graphe
        plotext fait 72 colonnes, auxquelles s'ajoutent la gouttière de
        RichHandler (~29) et sa colonne de chemin à droite (~15). **Sous 116
        colonnes, le graphe est replié et devient illisible** ; 120 est une
        valeur sûre.

        `notebook` vaut None (détection automatique), True ou False. Dans un
        noyau Jupyter, Rich rend chaque enregistrement en HTML via `display()`,
        ce qui produit un bloc de sortie par ligne de log — d'où les grands
        espacements. Le mode notebook repasse en sortie texte continue, retire
        la colonne de chemin (qui n'affiche que le fichier temporaire de la
        cellule) et fixe la largeur à NOTEBOOK_WIDTH. Forcer False rend le
        comportement d'origine.
        """
        if cls.configured:
            return

        # -------- Env overrides --------
        project = os.environ.get("LOG_PROJECT", project)

        level = os.environ.get("LOG_LEVEL", level).upper()
        console = _env_bool("LOG_CONSOLE", console)
        strip_ansi = _env_bool("LOG_STRIP_ANSI", strip_ansi)

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
            en_notebook = _in_notebook() if notebook is None else notebook
            largeur = console_width or (NOTEBOOK_WIDTH if en_notebook else None)

            # Dans un noyau, Rich bascule **de lui-même** en mode Jupyter :
            # chaque écriture devient un `display()` HTML, donc un bloc de
            # sortie distinct par enregistrement, que le noyau sépare par ses
            # propres marges. `force_jupyter=False` le renvoie sur stdout en
            # ANSI, que le notebook affiche en un flux continu et compact.
            rich_console = cls._console or Console(
                force_jupyter=False if en_notebook else None,
                force_terminal=True if en_notebook else None,
                width=largeur,
            )
            if largeur:
                rich_console.width = largeur
            cls._console = rich_console  # <-- mémorise pour réutiliser ailleurs

            rich_handler = RichHandler(
                console=rich_console,          # <-- on injecte la même console
                show_time=True,
                show_level=True,
                # Dans un notebook, le chemin est le fichier temporaire de la
                # cellule (« 3403673953.py:6 ») : illisible, inutile, et
                # 15 colonnes de moins pour le message.
                show_path=not en_notebook,
                markup=True,
                rich_tracebacks=True,
                tracebacks_suppress=[logging],
            )
            console_fmt = logging.Formatter("%(message)s")
            # RichHandler rend le message comme du texte et échappe les
            # caractères de contrôle : une séquence ANSI n'y produit aucune
            # couleur, seulement un « [0m » visible au milieu du graphe. La
            # retirer ne perd donc rien et rend la sortie lisible.
            rich_handler.setFormatter(
                AnsiStrippingFormatter(console_fmt) if strip_ansi else console_fmt
            )
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
            file_text.setFormatter(
                AnsiStrippingFormatter(plain_fmt) if strip_ansi else plain_fmt
            )
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
            file_json.setFormatter(
                AnsiStrippingFormatter(json_fmt) if strip_ansi else json_fmt
            )
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
    def log_dir_for(project: str, base_dir: Optional[Union[str, Path]] = None) -> Path:
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
        base_dir: Optional[Union[str, Path]] = None,
        date_prefix_files: bool = True,
        retention_days: int = 14,
        strip_ansi: bool = True,
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
        h.setFormatter(AnsiStrippingFormatter(plain_fmt) if strip_ansi else plain_fmt)
        h.addFilter(project_filter)

        # Attacher au logger du module (et NON au root)
        logger_obj.addHandler(h)
        # Le niveau résolu, pas la chaîne : `setLevel("PERF")` ne marcherait que
        # si le niveau a déjà été nommé, et lèverait sinon.
        logger_obj.setLevel(_level_from_str(level))
        return logger_obj
    
    @classmethod
    def get_console(cls) -> Console:
        """Retourne la Console Rich utilisée par le logger, ou en crée une si absente."""
        return cls._console