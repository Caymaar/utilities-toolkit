# `utilities.log` — logging setup, custom levels, helpers

One call configures a project's logging: a Rich console, a daily-rotating text
file, an optional JSONL file, and three custom levels for output that standard
levels cannot express.

```python
from utilities import LoggingConfigurator
LoggingConfigurator.configure(project="my_project", level="INFO")
```

---

## `LoggingConfigurator.configure(...)`

Configures the **root** logger. Idempotent by design: the second call is a no-op,
so importing a module that configures logging twice cannot stack handlers.

```python
LoggingConfigurator.configure(
    *,
    project: str | None = None,
    level: str = "INFO",
    base_dir: str | Path | None = None,
    console: bool = True,
    log_file: bool = True,
    json_file: bool = False,
    retention_days: int = 14,
    backtrace: bool = True,
    show_locals: bool = False,
    date_prefix_files: bool = True,
    strip_ansi: bool = True,
    console_width: int | None = None,
    notebook: bool | None = None,
) -> None
```

| Parameter | Meaning |
|---|---|
| `project` | Names the log files and fills the `%(project)s` field. **If `None`, no file is written** — console only. |
| `level` | Any standard name, **plus `PERF`, `DATAFRAME` and `PLOT`**. |
| `base_dir` | Where the files go. Defaults to `~/utilities/logs/<project>/`. |
| `console` | Rich console handler. |
| `log_file` / `json_file` | Rotating `<project>.log` / `<project>.jsonl`. |
| `retention_days` | Number of archived files kept. |
| `backtrace` / `show_locals` | Install Rich's traceback hook, with or without locals. |
| `date_prefix_files` | Archives named `YYYYMMDD.<project>.log` instead of `<project>.log.YYYYMMDD`. |
| `strip_ansi` | Remove ANSI escapes from messages — see below. |
| `console_width` | Pin the Rich console width — see below. |
| `notebook` | `None` auto-detects a Jupyter kernel — see below. |

### Environment overrides

Read at `configure()` time; they win over the arguments.

| Variable | Overrides |
|---|---|
| `LOG_PROJECT` | `project` |
| `LOG_LEVEL` | `level` — accepts `PERF`, `DATAFRAME`, `PLOT` |
| `LOG_CONSOLE` | `console` |
| `LOG_STRIP_ANSI` | `strip_ansi` |
| `LOG_JSON` | `json_file` |
| `LOG_DIR` | `base_dir` |
| `LOG_RETENTION_DAYS` | `retention_days` |

Booleans accept `1`, `true`, `yes`, `on` (case-insensitive).

### `strip_ansi=True` (default)

Removes ANSI escape sequences from log messages, on **every** handler.

- In a **file** they are noise: no terminal will ever interpret them.
- On the **console** `RichHandler` renders the message as text and escapes
  control characters, so an escape never becomes colour — it becomes a visible
  `[0m` in the middle of your chart.

Nothing is lost either way. Rich *markup* (`[bold]`) is unaffected. Pass
`strip_ansi=False` to keep the raw sequences.

### `console_width`

Pins the Rich console instead of guessing from the terminal. It matters for
block output: a plotext chart is 72 columns wide, and `RichHandler` adds ~29
columns of gutter plus ~15 for the right-hand path column. **Below 116 columns
the chart is wrapped and unreadable**; 120 is a safe value.

### `notebook`

`None` (default) auto-detects a Jupyter kernel; `True` and `False` force it.

Inside a kernel, Rich switches to its Jupyter mode on its own and renders every
record as HTML through `display()`. Each log line then becomes **its own output
block**, with the notebook's margins around it — the log ends up double spaced.
Notebook mode:

- returns Rich to continuous text output on stdout, colours included;
- drops the path column, which in a kernel only shows the cell's temporary
  filename (`3403673953.py:6`);
- defaults the width to `NOTEBOOK_WIDTH` (120), since there is no terminal to
  measure.

Detection costs one `sys.modules` lookup and never imports IPython. A terminal
IPython session answers "not a notebook", which is correct.

---

## `LoggingConfigurator.watch(project, module, level="DEBUG", ...)`

Adds a **dedicated file handler** to one module's logger, without touching the
handlers already configured elsewhere. The module keeps propagating, so its
records still reach the global handlers too.

```python
LoggingConfigurator.watch(project="my_project", module=__name__, level="DEBUG")
```

Files land in `<base_dir>/<module/as/path>/<project>.<module>.log`. Calling it
twice for the same module is a no-op. `level` accepts the custom level names.

## `LoggingConfigurator.get_console() -> Console`

The Rich `Console` shared by the console handler, or `None` if `configure()` has
not run with `console=True`. Reuse it rather than creating your own, so
everything prints through the same object — `utilities.probe.report()` does
exactly that.

## `LoggingConfigurator.log_dir_for(project, base_dir=None) -> Path`

Where the files for a project would go, without configuring anything. Honours
`LOG_DIR`.

---

## Custom levels

Registered in `utilities.log.levels`, once, and nowhere else — a level number is
global to the process, so two modules claiming the same integer would collide.

```
6   PLOT        ~1.7 ms per chart            8   DATAFRAME   ~80 µs to ~340 µs
10  DEBUG                                   15  PERF        ~1.15 µs per probe
20  INFO
```

Ordered by **increasing cost as you go down**: lowering the level means agreeing
to pay more. Registration never overwrites a name another package already claimed
for that number.

Once named, the levels work anywhere `logging` accepts a name:

```python
logger.setLevel("PLOT")
LoggingConfigurator.configure(level="DATAFRAME")
LOG_LEVEL=PLOT python my_script.py
```

### Levels are ordered — namespaces are not

Because `PLOT` (6) sits below `DATAFRAME` (8), a logger set to `PLOT` emits
DataFrames too. **You cannot get charts without frames using the level alone.**

That is what the logger **namespace** is for. Send each family to its own logger
and switch them independently:

```python
data = logging.getLogger("myapp.data")
plot = logging.getLogger("myapp.plot")

logging.getLogger("myapp").setLevel(logging.INFO)   # quiet by default
plot.setLevel(PLOT)                                 # charts only
```

Every helper takes the logger as its first argument precisely so that choice
stays yours. The package never picks a namespace on your behalf, and never adds
a handler.

---

## `AnsiStrippingFormatter(inner: logging.Formatter)`

Wraps another formatter and removes ANSI escapes from the **message**. Installed
automatically by `configure()` and `watch()` when `strip_ansi=True`; use it
directly on a handler you built yourself.

```python
handler.setFormatter(AnsiStrippingFormatter(logging.Formatter("%(message)s")))
```

Two implementation details that matter:

- It cleans the **message**, not the formatted output. `json.dumps` turns `\x1b`
  into ``, so a regex applied after `JsonLineFormatter` would find nothing.
- It always hands the inner formatter a **copy of the record carrying the
  already-rendered message**, so `getMessage()` runs exactly once. Otherwise a
  `Lazy` argument would be computed twice — precisely what `Lazy` exists to
  avoid. The original record is never mutated, so other handlers still see their
  colours.

---

## `Lazy(fn)`

Defers a computation until the message is formatted, which happens only if a
handler actually processes the record.

```python
log.debug("positions: %s", Lazy(lambda: df.describe()))
```

**Only useful when the argument is expensive to produce.** Passing an object you
already hold is *already* lazy: `logging` calls `__str__` only when the record is
processed, so `log.debug("%s", df)` costs nothing when DEBUG is off. `Lazy` is
for `head()`, `describe()`, an aggregation.

Never put an f-string in a logging call: it is evaluated before `logging` even
decides whether to keep the record.

---

## `with_spinner(text, spinner="simpleDotsScrolling")`

Decorator showing a Rich spinner while the function runs. The message is a
format template filled from the function's own arguments:

```python
@with_spinner("Loading {path}...")
def load(path): ...
```

If no console has been configured, the function simply runs without a spinner.

---

## JSON output

`json_file=True` writes one JSON object per line: `ts`, `level`, `logger`, `msg`,
`pathname`, `lineno`, `func`, `process`, `thread`, plus `project` and
`exc_info` when present.

Multi-line records — a DataFrame, a chart — stay **valid single-line JSON**,
because `json.dumps` escapes the newlines. No filtering is needed.

---

## Runnable examples

In [`examples/log/`](../examples/log/).

| Script | Shows |
|---|---|
| `demo_01_levels.py` | Levels and namespaces, five configurations |
| `demo_05_lazy_and_traps.py` | ANSI in files, scoped config, LazyFrames |
| `demo_06_terminal_reading.py` | A nightly batch as it reads over SSH |
| `log_playground.py` / `.ipynb` | Everything, as cells to play with |
