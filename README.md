# Utilities

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
![Version](https://img.shields.io/github/v/tag/Caymaar/utilities-toolkit?label=version)
[![Downloads](https://pepy.tech/badge/utilities-toolkit)](https://pepy.tech/project/utilities-toolkit)

A lightweight toolkit for the plumbing every project rewrites: where settings
live, how logs are set up, what a batch shows while it runs, and where the time
goes. Four independent areas, one shared folder on the machine.

```bash
pip install utilities-toolkit
# or
uv add utilities-toolkit
```

Charts need an extra: `pip install "utilities-toolkit[plot]"`.

---

## What is in it

| | |
|---|---|
| **[Configuration](docs/config.md)** | INI, JSON, YAML and Python settings under one root, reached by attribute access. |
| **[Logging](docs/logging.md)** | One call sets up a Rich console, rotating files, and three custom levels. |
| **[Frames & sparklines](docs/frames.md)** | Put a distribution or a DataFrame *in the log*, readable over SSH. |
| **[Terminal charts](docs/plots.md)** | plotext charts at their own log level. No image, no artefact. |
| **[Probing](docs/probe.md)** | Latency and memory instrumentation that costs **nothing** when off. |

Full API index and cost tables: **[docs/](docs/README.md)**.

---

## Configuration

```python
from utilities import Config

Config.ensure_initialized("my_project", {"PATHS": {"DATA": "/mnt/data"}})

value = Config.my_project.PATHS.DATA        # case-insensitive throughout
```

Files live in `~/utilities/config/` (`C:/utilities/config` on Windows), so
several projects on the same machine share one place instead of scattering
dotfiles. INI, JSON, YAML and `.py` are all read the same way.
→ **[docs/config.md](docs/config.md)**

## Logging

```python
from utilities import LoggingConfigurator

LoggingConfigurator.configure(project="my_project", level="INFO")
```

Rich console, a daily-rotating `my_project.log`, optional JSONL, Rich tracebacks.
Idempotent: calling it twice cannot stack handlers. Overridable from the
environment (`LOG_LEVEL`, `LOG_DIR`, `LOG_JSON`…), and it understands the custom
level names below.

```python
LoggingConfigurator.watch(project="my_project", module=__name__, level="DEBUG")
```

adds a dedicated file for one module without disturbing anything else.
→ **[docs/logging.md](docs/logging.md)**

## Three custom levels

```
6   PLOT        ~1.7 ms per chart
8   DATAFRAME   ~80 µs to ~340 µs
10  DEBUG
15  PERF        ~1.15 µs per probe
20  INFO
```

Ordered by increasing cost as you go down: lowering the level means agreeing to
pay more. Because levels are ordered, `PLOT` also emits DataFrames — to get one
without the other, use logger **namespaces** (`myapp.data`, `myapp.plot`). Every
helper takes the logger as its first argument so that choice stays yours.

The package never adds a handler and never touches the host's logging
configuration.

## Sparklines and DataFrames in the log

**Start with `spark()`.** ~12 µs for 300 points, no dependency, one line, and
still greppable — 145× cheaper than a chart.

```python
from utilities import spark, log_frame

log.info("nav n=%d %s [%.2f, %.2f]", len(nav), spark(nav), min(nav), max(nav))
```

```
nav n=300 ▂▂▂▂▂▂▁▂▃▃▃▅▅▄▅▆▆▆▇██▇▆▆ [96.32, 120.61]
```

```python
log_frame(data_logger, positions, mode="describe", label="positions")
```

Four modes — `head`, `tail`, `full`, `describe` — with a hard row cap on `full`,
scoped display settings, and a `LazyFrame` guard that logs the query plan instead
of ever calling `collect()`. polars and pandas are supported but never imported.

A multi-line record is no longer greppable — that trade-off is the reason
`spark()` comes first.
→ **[docs/frames.md](docs/frames.md)**

## Terminal charts

```python
from utilities.log.plots import plot_line
plot_line(plot_logger, nav, title="NAV")
```

```
                                     NAV
     ┌─────────────────────────────────────────────────────────────────┐
120.6┤                                                    ▐▙  ▄▖▄      │
     │                                                ▄▟  ▌▐▙▞▀▜ ▛▖    │
```

For a nightly batch whose log is read over SSH from a phone: no image, no
artefact to fetch, the log is the only surface. Needs `console_width=120` to
avoid being wrapped — [why](docs/plots.md#console-width).
→ **[docs/plots.md](docs/plots.md)**

## Probing

```python
from utilities import probed
from utilities.probe import probe, report

@probed()
def fetch_rows(cursor, sql):
    cursor.execute(sql)
    return cursor.fetchall()

with probe("materialize"):
    rows = [dict(r) for r in raw]
```

```bash
PROBE_TIER=1 python my_script.py
```

```
label                                  n       wall       self       wait        mean         p95
-------------------------------------------------------------------------------------------------
db.execute                             4     4.310s     4.310s     4.290s   1077.50ms   1131.02ms
transform                              1     0.412s     0.412s     0.001s    412.30ms    412.30ms
```

- **`wait = wall - cpu`** — the column that decides what to do next. Close to
  `wall`, you are waiting on a database or a network share and rewriting Python
  will gain you nothing. Close to zero, the code is the problem.
- **`self = wall - children`** — cProfile's `tottime`. A function that only
  delegates tops the `wall` ranking while being innocent.

**Zero cost when off**: at `PROBE_TIER=0`, `probed()` returns your function
unchanged — 0.0 ns measured, no wrapper, not even a flag test. That is what makes
it safe to leave in production code. The tier is read once at import and cannot
be changed at runtime; that is the price of the guarantee.

Only instrument blocks of **400 µs or more**, and never read latency from a
`PROBE_TIER=2` run — `tracemalloc` slows the whole process 11×.
→ **[docs/probe.md](docs/probe.md)**

`probe` tells you *which* block costs. To find out *why*, inside it:

```bash
uv run --with pyinstrument pyinstrument my_script.py
```

---

## Examples

Every script in [`examples/`](examples/) runs on its own with no arguments.

- [`examples/probe/`](examples/probe/) — the three tiers side by side, the
  overhead measured on your machine, CPU vs I/O, nesting, asyncio, output formats
- [`examples/log/`](examples/log/) — levels and namespaces, the four frame modes,
  the four charts, costs, three traps, and a batch as it reads in a `tail -f`

Two playgrounds exist as both a notebook and a `# %%`-cell script:
[`log_playground`](examples/log/log_playground.py) and
[`probe_playground`](examples/probe/probe_playground.py).

## Structure

```
src/utilities/
├── config/      configuration store
├── log/         setup, levels, frames, plots, helpers
├── probe/       latency and memory instrumentation
└── utils/       folder helpers
docs/            full documentation
examples/        runnable demos and notebooks
tests/           test suite
```
