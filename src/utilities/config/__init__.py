import os
from pathlib import Path
from utilities.config.config import Config
from ..constant import CONFIG_PATH, LOGS_PATH, SPECIFIC_PATH

HOME = Path.home()

UTILS_CONFIG_DICT = {
    "PATHS": {
        "CONFIG": CONFIG_PATH,
        "LOGS": LOGS_PATH,
        "SPECIFIC": SPECIFIC_PATH
    }
}

os.makedirs(CONFIG_PATH, exist_ok=True)
os.makedirs(LOGS_PATH, exist_ok=True)

Config.ensure_initialized("TEST", UTILS_CONFIG_DICT)

__all__ = ["Config"]