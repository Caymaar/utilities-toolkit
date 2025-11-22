# tests/test_vaultmeta.py
import os
import json
import configparser
import textwrap
import types
import importlib.util
import pytest
import sys

# --- On importe ici les symboles depuis ton module réel ---
# Ajuste ce chemin d'import selon ton projet :
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from utilities.config.vault import VaultMeta  # <- supposé disponible dans ton projet


# --- Helpers ---------------------------------------------------------------

def write_ini(path, sections: dict[str, dict[str, str]]):
    """Écrit un INI en conservant la casse des clés."""
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str  # conserve la casse U/V/X etc.
    for sec, mapping in sections.items():
        cfg[sec] = mapping
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)


# --- Tests quand path pointe vers un FICHIER .ini --------------------------

def test_vaultmeta_with_ini_file(tmp_path):
    ini_path = tmp_path / "config.ini"
    write_ini(
        ini_path, {"PATH": {
                    "NETWORK_SUPPORT": "V:/FF/Gestion Quantitative/Thematic/SUPPORT",
                    "LOCAL_SUPPORT": "C:/Users/John/Documents/SUPPORT",
                },
                "DISK": {
                    "U": "\\\\smb.gicm.net\\dfs\\structure\\",
                    "V": "\\\\smb.gicm.net\\dfs\\structure\\FF\\",
                    "X": "\\\\smb.gicm.net\\dfs\\transverse\\"
                }
        }
            )

    class Cfg(metaclass=VaultMeta):
        path = str(ini_path)

    # __getattr__ sur la metaclass renvoie un _FileProxy(...).__getattr__(name)
    # Pour INI: Cfg.DISK -> _IniSectionProxy ; puis accès attribut clé insensible à la casse
    assert Cfg.DISK.U == "\\\\smb.gicm.net\\dfs\\structure\\"
    assert Cfg.DISK.u == "\\\\smb.gicm.net\\dfs\\structure\\"
    assert Cfg.PATH.NETWORK_SUPPORT == "V:/FF/Gestion Quantitative/Thematic/SUPPORT"

    # __call__ sur la metaclass renvoie le "raw" (dict sections -> dict clés/valeurs)
    raw = Cfg()
    assert isinstance(raw, dict)
    assert "DISK" in raw and "PATH" in raw
    assert raw["DISK"]["V"] == "\\\\smb.gicm.net\\dfs\\structure\\FF\\"

    # L'accès à une section inexistante doit lever AttributeError
    with pytest.raises(AttributeError):
        _ = Cfg.MISSING_SECTION


# --- Tests quand path pointe vers un FICHIER .json -------------------------

def test_vaultmeta_with_json_file(tmp_path):
    json_path = tmp_path / "config.json"
    data = {
        "PATH": {
            "NETWORK_SUPPORT": "V:/FF/Gestion Quantitative/Thematic/SUPPORT",
            "LOCAL_SUPPORT": "C:/Users/John/Documents/SUPPORT",
        },
        "FLAGS": {
            "DEBUG": True,
        },
        "TIMEOUT": 30,
    }
    json_path.write_text(json.dumps(data), encoding="utf-8")

    class JCfg(metaclass=VaultMeta):
        path = str(json_path)

    # Pour JSON, l'attribut top-level renvoie la valeur nettoyée (dict/str/bool/int)
    # Ici PATH est un dict -> on indexe par clé (pas d'accès attribut sur dict standard)
    assert isinstance(JCfg.PATH, dict)
    assert JCfg.PATH["NETWORK_SUPPORT"] == "V:/FF/Gestion Quantitative/Thematic/SUPPORT"

    # Accès direct à TIMEOUT (clé scalaire)
    assert JCfg.TIMEOUT == 30

    # __call__ renvoie le dict brut complet
    raw = JCfg()
    assert raw["FLAGS"]["DEBUG"] is True

    with pytest.raises(AttributeError):
        _ = JCfg.NOT_A_KEY


# --- Tests quand path pointe vers un FICHIER .py ---------------------------

def test_vaultmeta_with_py_file(tmp_path):
    py_path = tmp_path / "settings.py"
    py_path.write_text(
        textwrap.dedent(
            """
            FOO = 123
            BAR = "baz"
            _PRIVATE = "hidden"
            """
        ),
        encoding="utf-8",
    )

    class PCfg(metaclass=VaultMeta):
        path = str(py_path)

    # Expose seulement les symboles non _privés
    assert PCfg.FOO == 123
    assert PCfg.BAR == "baz"
    with pytest.raises(AttributeError):
        _ = PCfg._PRIVATE

    # __call__ renvoie le dict complet
    raw = PCfg()
    assert raw == {"FOO": 123, "BAR": "baz"}


# --- Tests quand path pointe vers un DOSSIER -------------------------------

def test_vaultmeta_with_directory_mapping(tmp_path):
    # Dossier avec fichiers de config
    dir_path = tmp_path / "locker"
    dir_path.mkdir()

    # 1) INI : nom avec tiret -> doit devenir attribut avec underscore (et insensible à la casse)
    ini_file = dir_path / "global-config.ini"
    write_ini(
        ini_file,
        {
            "DISK": {
                "U": "\\\\smb.gicm.net\\dfs\\structure\\",
            }
        },
    )

    # 2) JSON simple
    json_file = dir_path / "settings.json"
    json_file.write_text(json.dumps({"ENV": "prod"}), encoding="utf-8")

    # 3) PY simple
    py_file = dir_path / "feature_flags.py"
    py_file.write_text("ENABLED = True\n", encoding="utf-8")

    class Vault(metaclass=VaultMeta):
        path = str(dir_path)

    # Mapping du nom de fichier -> attribut (tirets -> underscores, case-insensitive)
    # global-config.ini -> .global_config
    assert Vault.global_config.DISK.U == "\\\\smb.gicm.net\\dfs\\structure\\"

    # settings.json -> .settings (et .ENV est une clé top-level -> valeur scalaire)
    assert Vault.settings.ENV == "prod"

    # feature_flags.py -> .feature_flags
    assert Vault.feature_flags.ENABLED is True

    # Accès à un faux fichier doit lever AttributeError
    with pytest.raises(FileNotFoundError):
        _ = Vault.unknown_file

    # Extension non supportée -> lève AttributeError (via mapping des ext)
    # On crée un .txt pour vérifier
    bad = dir_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    with pytest.raises(AttributeError):
        _ = Vault.notes


# --- Robustesse: path inexistant / mauvais type ----------------------------

def test_vaultmeta_invalid_path(tmp_path):
    class Bad(metaclass=VaultMeta):
        path = str(tmp_path / "missing.ini")

    # Accéder à un attribut déclenche l'ouverture -> FileNotFoundError via _FileProxy
    try:
        _ = Bad.SOMETHING
    except Exception as e:
        print(e)

    with pytest.raises(FileNotFoundError):
        _ = Bad.SOMETHING

    # Appeler la classe (.__call__) déclenche aussi l'ouverture -> FileNotFoundError
    with pytest.raises(FileNotFoundError):
        _ = Bad()