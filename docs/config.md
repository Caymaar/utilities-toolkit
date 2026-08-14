# `utilities.config` — centralised configuration

Read and write project settings from a single place on the machine, in INI,
JSON, YAML or Python, reached by plain attribute access.

```python
from utilities import Config
```

---

## Where things live

Everything sits under one root, created on import:

| Constant (`utilities.constant`) | Path (POSIX) | Path (Windows) |
|---|---|---|
| `UTILITIES_PATH` | `~/utilities` | `C:/utilities` |
| `CONFIG_PATH` | `~/utilities/config` | `C:/utilities/config` |
| `LOGS_PATH` | `~/utilities/logs` | `C:/utilities/logs` |
| `SPECIFIC_PATH` | `~/utilities/specific` | `C:/utilities/specific` |

The point is that several projects on the same machine share one place for
their settings and logs, instead of scattering dotfiles.

> `CONFIG_PATH` and `LOGS_PATH` are created when `utilities` is imported. On a
> read-only filesystem or in a container without write access to `$HOME`, that
> import fails.

---

## `Config.ensure_initialized(project, config)`

Creates `<CONFIG_PATH>/<project>.ini` from a nested dict, **only if it does not
already exist**. An existing file is never overwritten, so this is safe to call
at every start-up.

```python
Config.ensure_initialized("my_project", {
    "PATHS": {"DATA": "/mnt/data", "OUT": "/mnt/out"},
    "DB":    {"HOST": "db.internal", "PORT": "5432"},
})
```

The project name is lower-cased and its spaces become underscores:
`"My Project"` → `my_project.ini`. Key case is preserved.

---

## Reading

`Config` is backed by a metaclass, so attribute access on the class walks the
config directory:

```python
Config.my_project.PATHS.DATA      # -> "/mnt/data"
Config.MY_PROJECT.paths.data      # same thing, case-insensitive throughout
```

- **First level** — the file. `my_project` finds `my_project.ini`. Hyphens in
  filenames map to underscores, so `mod-name.py` is reached as
  `Config.mod_name`.
- **Second level** — for INI, the section; for JSON, YAML and Python, a
  top-level key.
- **Third level** — for INI, the key inside the section.

Both file names and keys are matched case-insensitively.

| Extension | Second level | Notes |
|---|---|---|
| `.ini` | Section, then key | Values wrapped in `"` are unquoted. Everything is a string. |
| `.json` | Top-level key | Nested objects come back as plain dicts. |
| `.yaml` | Top-level key | Must be a mapping at the top level. |
| `.py` | Module-level name | Names starting with `_` are skipped. The file **is executed**. |

Files are loaded **eagerly on each access** — there is no cache, so a file edited
on disk is picked up by the next read, and reading in a loop re-parses every
time.

Calling a file proxy returns the raw structure:

```python
Config.my_project()          # {'PATHS': {'DATA': '/mnt/data'}, 'DB': {...}}
Config.my_project.PATHS()     # the section as a plain dict
```

A missing file raises `FileNotFoundError`; a missing section or key raises
`AttributeError`, listing what *is* available.

---

## Writing

In memory, on the proxy:

```python
cfg = Config.settings          # a .json file
cfg.timeout = 30               # allowed on JSON and Python files
```

INI files refuse top-level assignment — go through the section:

```python
Config.my_project.PATHS.DATA = "/mnt/other"     # allowed
Config.my_project.PATHS = {...}                 # AttributeError
```

> These writes update the in-memory proxy. Persisting is up to you; there is no
> automatic write-back.

---

## `Config.path`

The directory scanned by the metaclass, `CONFIG_PATH` by default. Point a
subclass elsewhere to read another tree:

```python
from utilities.config.vault import VaultMeta

class Vault(metaclass=VaultMeta):
    path = "/mnt/secrets"      # a directory, or a single file

Vault.credentials.DB.PASSWORD
```

When `path` names a **file** rather than a directory, the first attribute level
is the section or key directly.

---

## `utilities_specific_folder(name) -> str`

Creates and returns `<SPECIFIC_PATH>/<name>`, for files that belong to a project
but are neither config nor logs.

```python
from utilities import utilities_specific_folder
exports = utilities_specific_folder("my_project")   # ~/utilities/specific/my_project
```
