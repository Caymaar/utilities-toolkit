import os
import configparser
import json
import importlib.util

import logging

logger = logging.getLogger(__name__)

def _clean_value(value):
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value

def _clean_values(values: dict):
    for k, v in values.items():
        values[k] = _clean_value(v)
    return values

class _IniSectionProxy(dict):
    """
    Proxy d'une section INI exposée comme un dict ET en attributs.
    - Hérite de dict pour supporter les affectations `self[k] = ...`.
    - Accès insensible à la casse via __getattr__ / __setattr__.
    """

    @property
    def __class__(self):
        return dict
    
    def __init__(self, section_name: str, sections_dict: dict):
        super().__init__()
        self._section_name = section_name
        self._sections_dict = sections_dict
        # Remplit le dict avec les paires clé/valeur nettoyées
        for k, v in self._sections_dict[self._section_name].items():
            super().__setitem__(k, _clean_value(v))

class _IniSectionProxy(dict):
    def __call__(self):
        return self._sections_dict[self._section_name]

    def __init__(self, section_name: str, sections_dict: dict):
        super().__init__()
        self._section_name = section_name
        self._sections_dict = sections_dict
        # Remplit le dict avec les paires clé/valeur nettoyées
        for k, v in self._sections_dict[self._section_name].items():
            super().__setitem__(k, _clean_value(v))
    
    def __getattr__(self, key: str):
        # Mapping insensible à la casse des clés de la section
        key_map = {k.upper(): k for k in self._sections_dict[self._section_name].keys()}
        real = key_map.get(key.upper())
        if real is not None:
            return self[real]
        raise AttributeError(f"{key!r} not found in section {self._section_name!r}")

    def __setattr__(self, key: str, value):
        # Préserve les attributs internes
        if key in {"_section_name", "_sections_dict"}:
            return super().__setattr__(key, value)
        key_map = {k.upper(): k for k in self._sections_dict[self._section_name].keys()}
        real = key_map.get(key.upper(), key)
        self[real] = value

class _FileProxy(dict):
    """
    Proxy de fichier de config (ini/json/py), *eager*:
      - Charge le fichier dans __init__ (pas de lazy, pas de reload).
      - INI : chaque section est exposée comme un _IniSectionProxy (dict-like).
      - JSON/PY : les clés top-level sont copiées dans le dict.
      - Accès par attributs :
          * INI  : file.SECTION -> _IniSectionProxy
          * JSON : file.key
          * PY   : file.key
      - Écritures :
          * JSON/PY : autorisées au top-level (dict normal)
          * INI     : interdites au top-level ; passer par file.SECTION.key = ...
    """
    @property
    def __class__(self):
        return dict

    def __call__(self):
        """
        Retourne la structure brute telle que chargée du fichier.
        - INI  : dict(section -> dict(key->value))
        - JSON : dict complet
        - PY   : dict complet
        """
        return self._raw

    def __init__(self, file_path: str, file_type: str):
        super().__init__()
        self._file_path = file_path
        self._file_type = file_type.lower()
        self._raw: dict | None = None  # copie brute si utile
        self._load_eager()

    # --------- Chargement immédiat ----------
    def _load_eager(self) -> None:
        if self._file_type == 'ini':
            config = configparser.ConfigParser()
            config._interpolation = configparser.Interpolation()
            config.optionxform = str  # conserver la casse
            if not config.read(self._file_path):
                raise FileNotFoundError(f"INI not found: {self._file_path}")

            sections = {s: dict(_clean_values(config[s])) for s in config.sections()}
            self._raw = sections
            # Expose chaque section comme un proxy dict-like
            for s in sections:
                super().__setitem__(s, _IniSectionProxy(s, sections))

        elif self._file_type == 'json':
            with open(self._file_path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise TypeError("Top-level JSON must be an object")
            self._raw = data
            super().update(data)

        elif self._file_type == 'py':
            spec = importlib.util.spec_from_file_location("locker_module", self._file_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot import {self._file_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            data = {k: v for k, v in vars(module).items() if not k.startswith('_')}
            self._raw = data
            super().update(data)

        else:
            raise ValueError(f"Unsupported file type: {self._file_type}")

    # --------- Accès par attributs ----------
    def __getattr__(self, key: str):
        logger.debug("Accessing key '%s' in file '%s'", key, os.path.basename(self._file_path))

        if self._file_type == 'ini':
            # Sections insensibles à la casse
            section_map = {s.upper(): s for s in self.keys()}
            real = section_map.get(key.upper())
            if real:
                return super().__getitem__(real)  # _IniSectionProxy
            # fallback: méthodes de dict si besoin
            if key in dir(dict):
                return getattr(self, key)
            raise AttributeError(f"Section '{key}' not found in '{os.path.basename(self._file_path)}'.")

        # JSON / PY : clés insensibles à la casse
        key_map = {k.upper(): k for k in self.keys()}
        real = key_map.get(key.upper())
        if real is None:
            raise AttributeError(f"Key '{key}' not found in '{os.path.basename(self._file_path)}'.")
        return _clean_value(super().__getitem__(real))

    def __setattr__(self, key: str, value):
        if key in {"__dict__", "_file_path", "_file_type", "_raw"}:
            return super().__setattr__(key, value)

        if self._file_type in ("json", "py"):
            # autoriser l’affectation par attribut
            key_map = {k.upper(): k for k in self.keys()}
            real = key_map.get(key.upper(), key)
            super().__setitem__(real, value)
            if isinstance(self._raw, dict):
                self._raw[real] = value
            return

        if self._file_type == "ini":
            # écriture top-level interdite → passer par la section
            raise AttributeError("For INI, assign through a section (file.SECTION.key = value).")

    # --------- Garde-fous écriture INI top-level ----------
    def __setitem__(self, key, value):
        if self._file_type == 'ini':
            raise TypeError("Cannot set INI at file level; use file.SECTION[...]")
        super().__setitem__(key, value)
        if isinstance(self._raw, dict):
            self._raw[key] = value

    def update(self, *args, **kwargs):
        if self._file_type == 'ini':
            raise TypeError("Cannot update INI at file level; update sections instead.")
        super().update(*args, **kwargs)
        if isinstance(self._raw, dict):
            self._raw.update(*args, **kwargs)

class VaultMeta(type):
    

    def __call__(cls):
        return _FileProxy(cls.path, os.path.splitext(cls.path)[1][1:]).__call__()

    def __getattr__(cls, name):
        if os.path.isfile(cls.path):
            return _FileProxy(cls.path, os.path.splitext(cls.path)[1][1:]).__getattr__(name)
        elif os.path.isdir(cls.path):
            files = os.listdir(cls.path)
            # Remplace les tirets par des underscores pour le mapping
            file_map = {os.path.splitext(f)[0].replace('-', '_').lower(): f for f in files}
            file_name = file_map.get(name.lower())
            if not file_name:
                raise FileNotFoundError(f"File '{name}' not found in Locker.")
            file_path = os.path.join(cls.path, file_name)
            ext = os.path.splitext(file_name)[1].lower()
            if ext == '.ini':
                file_type = 'ini'
            elif ext == '.json':
                file_type = 'json'
            elif ext == '.py':
                file_type = 'py'
            else:
                raise AttributeError(f"Unsupported file type: {ext}")
            return _FileProxy(file_path, file_type)
        else:
            raise FileNotFoundError(f"File '{name}' not found in Locker.")