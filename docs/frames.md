# `utilities.log.frames` — sparklines and DataFrames in the log

Two tools, in the order you should reach for them.

```python
from utilities import spark, log_frame
```

Neither polars nor pandas is ever imported by this module: they are detected on
the object you hand it. If you are holding a DataFrame, the package that built it
is already loaded.

---

## `spark(values, n=24) -> str`

A one-line sparkline in Unicode blocks. **~12 µs for 300 points**, no
dependency, greppable, and it fits on a phone screen — 145× cheaper than a
plotext chart.

This is the first reflex. Nine times out of ten, the question you actually ask
while reading a pipeline log is "does this distribution look normal?", and a
sparkline answers it.

```python
log.info("nav n=%d %s [%.2f, %.2f]", len(nav), spark(nav), min(nav), max(nav))
```

```
nav n=300 ▂▂▂▂▂▂▁▂▃▃▃▅▅▄▅▆▆▆▇██▇▆▆ [96.32, 120.61]
```

| Behaviour | Detail |
|---|---|
| Downsampling | Longer series are sampled across their full length, **both ends kept**. A fixed stride would lose the tail whenever the length is not a multiple of `n`. |
| Non-numeric values | `None`, `NaN`, `inf` and anything that will not convert to `float` are ignored. |
| Constant series | Renders `▁▁▁`. The sparkline alone cannot say at what height it is flat — hence the recommended `[min, max]` framing above. |
| Empty input | Returns `""`. Also for `n < 1`. |
| Monotonicity | An increasing series always renders as non-decreasing blocks. |

Recognisable shapes:

```
increasing     ▁▁▂▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▆▇▇▇██
bell           ▁▁▁▁▁▁▂▃▄▅▇██▇▆▅▃▂▂▁▁▁▁▁
bimodal        ▁▂▂▂▂▂▂▃▃▃▃▃▆▆▆▆▆▇▇▇▇▇▇█
```

---

## `log_frame(log, df, *, mode="head", n=10, label=None, max_rows=200, max_cols=40, width=200, rich=False)`

Logs a polars or pandas DataFrame at level `DATAFRAME` (8).

```python
log_frame(data_logger, positions, mode="head", n=10, label="positions")
```

```
DATAFRAME  positions | 5000 x 3 | mode=head n=10
shape: (10, 3)
┌────────┬──────────┬────────┐
│ ticker ┆ quantite ┆ prix   │
...
```

| Parameter | Meaning |
|---|---|
| `log` | The logger. **Explicit on purpose** — the module never picks a namespace for you. Convention: `<yourapp>.data`. |
| `df` | polars or pandas `DataFrame`, a `LazyFrame`, or anything with `shape`, `columns`, `head`, `tail` and `describe`. |
| `mode` | `"head"`, `"tail"`, `"full"` or `"describe"`. Anything else raises `ValueError`. |
| `n` | Row count — applies to `head` and `tail` only. |
| `label` | Header name. Defaults to the type name. |
| `max_rows` | Hard cap for `full`. **Cannot be disabled.** |
| `max_cols` | Column cap, honoured by both the native and the Rich rendering. |
| `width` | Rendering width handed to the display config. |
| `rich` | Render as a `rich.table.Table` instead of the engine's own repr. |

### Nothing is built when the level is off

The level check comes first, before any slicing or formatting. Measured cost when
off: **~0.3 µs**, the level test and nothing else. That is what makes these calls
safe to leave in production code.

### `full` is capped, and says so

polars' own repr already truncates — 500 000 rows render as 18 lines of text.
`full` is precisely the mode that lifts that guard, so it installs another one:
the slice is bounded to `min(max_rows, height)`, never unlimited, and the omitted
count is appended.

```
... 499800 lignes omises sur 500000 (plafond max_rows=200)
```

Columns get the same treatment against `max_cols`, in both rendering paths.

### A `LazyFrame` is never materialised

Detected by having both `collect` and `explain` (a `DataFrame` has neither).
`log_frame` logs the **execution plan** instead — often more informative than the
data — and calls `collect()` in no mode whatsoever. Triggering a full query from
a logging call would be the worst possible defect in this module.

```
DATAFRAME  aggregation | LazyFrame non matérialisé — plan d'exécution :
AGGREGATE ... FILTER col("b") > 3 FROM DF ["a", "b"]
```

### Display configuration is scoped

Widening a frame to log it touches a **global** setting: your own `print` calls
would change. `log_frame` uses `pl.Config` / `pd.option_context` as context
managers, restored on exit **including when the rendering raises**.

### `rich=True`

Renders the already-truncated slice as a Rich table, colourless, into a string.
For pandas the index is re-inserted when it is not a plain `RangeIndex` —
otherwise a `describe` would come out as anonymous columns of numbers.

If the Rich rendering is impossible or comes back empty, it falls back to the
engine's native repr.

### Markup is disabled per record

Frame content is *data*: a cell holding `[/bold]` would make a `markup=True`
`RichHandler` raise `MarkupError` at the logging call, and a column named
`ret[bps]` would render truncated. Every record emitted here carries
`markup=False`, without touching the host's global setting — your own messages
can still use `[bold]`.

---

## `MODES`

`("head", "tail", "full", "describe")`.

---

## Measured costs

| Operation | Cost |
|---|---|
| `spark()`, 300 points | ~12 µs |
| `log_frame(mode="head")`, 5 000 rows | ~82 µs |
| `log_frame(mode="describe")`, 5 000 rows | ~341 µs |
| Any of them, level off | ~0.3 µs |

`describe` is cheaper than it looks — 850 µs on 500 000 rows in polars — so there
is no automatic guard on it, only this note. Unlike `full`, its output is
*bounded*; only its compute cost varies, and paying it is a legitimate choice.

---

## Multi-line records: the trade-off

A 19-line record is no longer a line: **`grep` will not find it**, and a
formatter prefix only applies to the first line. That is acceptable for a log you
*read*, not for a log you *filter* — which is exactly why `spark()` exists and
comes first.

---

## Runnable examples

`examples/log/demo_02_frames.py` (all four modes, plus the cap on 500 000 rows),
`examples/log/demo_05_lazy_and_traps.py` (LazyFrame, ANSI, scoped config), and
the playground.
