# Utilities

> A lightweight utilities package for managing configuration and logging across multiple projects. It provides a simple interface to create and access configuration files in various formats, along with a straightforward logging system that can optionally centralize logs and configs in a single location.

![Latest Version](https://img.shields.io/github/v/tag/Caymaar/utilities-toolkit?label=version)
![Python Version](https://img.shields.io/pypi/pyversions/utilities-toolkit)

## Installation

You can install the package via pip from git:
```bash
pip install utilities-toolkit
```
Or with uv:
```bash
uv add utilities-toolkit
```

## Main Features
- **Dynamic configuration access**: Read and write INI, JSON, and Python files for centralized settings.
- **Advanced logging**: Flexible logging setup, Rich formatting for readable and colored logs.
- **File copy with progress**: Copy files with Rich progress bars and automatic backup of existing files.
- **Utility functions**: Folder creation, path manipulation, and more.

## Exported Functions & Classes

### Config
Configuration manager for your projects. Example:
```python
from utilities import Config
Config.ensure_initialized("my_project", {"Section": {"Key": "Value"}})

# Then access it like this:
value = Config.my_project.Section.Key
```

It will create an ini config file in a project-specific folder in utilities folder at the root of your user directory.

Making it useful for storing project-specific settings.

### LoggingConfigurator
Flexible logging setup with Rich formatting. Example:
```python
from utilities import LoggingConfigurator
LoggingConfigurator.configure(project="my_project", level="DEBUG", console=True, log_file=True)
```

Useful to centralize logging configuration, but especially log files in a project-specific folder in utilities folder at the root of your user directory.

### with_spinner
Context manager to display a Rich spinner during long operations. Example:
```python
from utilities import with_spinner
with with_spinner("Processing..."):
    # your code
```

### utilities_specific_folder
Returns the path to a project-specific folder, creating it if necessary. Example:
```python
from utilities import utilities_specific_folder
folder = utilities_specific_folder("my_folder")
```

Useful for storing files related to your project in a dedicated folder within the utilities directory.

## Structure

- `src/utilities/` : main source code
- `src/utilities/config/` : configuration management
- `src/utilities/log/` : logging and utilities
- `tests/` : unit tests
