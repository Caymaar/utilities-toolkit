# Documentation

Four areas, independent of each other.

| Page | Covers |
|---|---|
| [config.md](config.md) | `Config`, the shared `~/utilities` tree, `utilities_specific_folder` |
| [logging.md](logging.md) | `LoggingConfigurator`, the custom levels, `AnsiStrippingFormatter`, `Lazy`, `with_spinner` |
| [frames.md](frames.md) | `spark`, `log_frame` |
| [plots.md](plots.md) | `plot_line`, `plot_scatter`, `plot_hist`, `plot_bar` |
| [probe.md](probe.md) | `probe`, `probed`, `report`, and the tier system |

---

## Full API index

### `utilities` (top level)

| Name | Signature |
|---|---|
| `Config` | `ensure_initialized(project, config)`, plus attribute access |
| `LoggingConfigurator` | `configure(...)`, `watch(...)`, `get_console()`, `log_dir_for(...)` |
| `with_spinner` | `(text, spinner="simpleDotsScrolling")` |
| `Lazy` | `(fn)` |
| `spark` | `(values, n=24) -> str` |
| `log_frame` | `(log, df, *, mode="head", n=10, label=None, max_rows=200, max_cols=40, width=200, rich=False)` |
| `probed` | `(label=None) -> Callable[[F], F]` |
| `report` | `(stream=None, *, sort="wall", rich=None) -> str` |
| `utilities_specific_folder` | `(name) -> str` |

`probe` — the context manager — is **not** exported at top level, because it
shares its name with the `utilities.probe` subpackage. Import it from its
module: `from utilities.probe import probe`.

### `utilities.log`

`LoggingConfigurator`, `AnsiStrippingFormatter`, `Lazy`, `with_spinner`,
`spark`, `log_frame`, and the levels `PERF` (15), `DATAFRAME` (8), `PLOT` (6).

### `utilities.log.frames`

`spark`, `log_frame`, `MODES`.

### `utilities.log.plots`

`plot_line`, `plot_scatter`, `plot_hist`, `plot_bar`. Needs the `[plot]` extra.

### `utilities.probe`

`probe`, `probed`, `Probe`, `Stat`, `registry`, `snapshot`, `report`,
`to_dicts`, `reset`, and the constants `TIER`, `ENABLED`, `PERF`.

### `utilities.constant`

`UTILITIES_PATH`, `CONFIG_PATH`, `LOGS_PATH`, `SPECIFIC_PATH`.

---

## Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `PROBE_TIER` | `utilities.probe`, **at import** | `0` off, `1` timing, `2` timing + memory |
| `LOG_LEVEL` | `configure()` | Level, custom names included |
| `LOG_PROJECT` | `configure()` | Project name |
| `LOG_DIR` | `configure()`, `watch()` | Log directory |
| `LOG_CONSOLE` | `configure()` | Console handler on/off |
| `LOG_JSON` | `configure()` | JSONL file on/off |
| `LOG_STRIP_ANSI` | `configure()` | ANSI stripping on/off |
| `LOG_RETENTION_DAYS` | `configure()` | Archives kept |

---

## Levels at a glance

```
6   PLOT        ~1.7 ms per chart
8   DATAFRAME   ~80 µs (head) to ~340 µs (describe)
10  DEBUG
15  PERF        ~1.15 µs per probe
20  INFO
```

Ordered by increasing cost as you go down: lowering the level means agreeing to
pay more. Levels are ordered, so `PLOT` also emits DataFrames — use logger
**namespaces** when you want one without the other.

---

## Cost summary

Measured on CPython 3.13, Apple Silicon. Reproduce with
`examples/probe/demo_02_overhead.py` and `examples/log/demo_04_cost.py`.

| Operation | Off | On |
|---|---|---|
| `@probed` function call | **0.0 ns** | ~1 150 ns |
| `with probe(...)` | ~81 ns | ~1 119 ns |
| `spark()`, 300 points | — | ~12 µs |
| `log_frame(mode="head")` | ~0.3 µs | ~82 µs |
| `plot_line()`, 300 points | ~0.3 µs | ~1.7 ms |

Under `PROBE_TIER=2`, a bare uninstrumented call goes from 14 ns to 158 ns:
`tracemalloc` slows the whole process, which is why latency and memory are never
read from the same run.

---

## Requirements

Python 3.9+. Runtime dependencies: `pyyaml`, `rich`. Optional: `plotext` via the
`[plot]` extra. `polars` and `pandas` are supported but never imported — they are
detected on the object you pass.
