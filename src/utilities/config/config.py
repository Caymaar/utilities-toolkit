from utilities.config.vault import VaultMeta
from utilities.constant import CONFIG_PATH

import configparser
import os

class Config(metaclass=VaultMeta):
    path = CONFIG_PATH

    @staticmethod
    def ensure_initialized(project, config):
        config_path = os.path.join(CONFIG_PATH, project.lower().replace(" ", "_") + ".ini")
        if not os.path.exists(config_path):
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.optionxform = str

            for k, v in config.items():
                cfg[k] = v

            with open(config_path, "w", encoding="utf-8") as configfile:
                cfg.write(configfile)
