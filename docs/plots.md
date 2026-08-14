# `utilities.log.plots` — terminal charts in the log

Charts drawn in terminal characters, logged at level `PLOT` (6). For a batch
whose log is read over SSH: no image, no file, no matplotlib — 2.6 s of import
time, and an image cannot be read in a `tail -f` anyway.

```python
from utilities.log.plots import plot_line, plot_scatter, plot_hist, plot_bar
```

---

## Look at `spark()` first

On 300 points a sparkline costs ~12 µs against ~1.7 ms for a plotext chart —
**145× less** — fits on one line, and stays greppable. It answers the question
you actually have nine times out of ten. plotext is the second reflex, for when
you need to see a *shape*.

Rule of thumb: **a sparkline per loop iteration, a chart once per run.**

---

## Optional dependency

`plotext` is not a runtime dependency:

```bash
pip install "utilities-toolkit[plot]"
```

Without it, the helpers raise a `RuntimeError` carrying the install command and
a pointer to `spark()` — not a bare `ImportError`.

---

## The four helpers

All take the logger as their first argument, and all return `None`.

```python
plot_line(log, ys, *, title="", x=None)
plot_scatter(log, xs, ys, *, title="")
plot_hist(log, values, *, bins=30, title="")
plot_bar(log, labels, values, *, title="")
```

| Helper | For |
|---|---|
| `plot_line` | Time series. NAV, cumulated volume, a queue depth over time. |
| `plot_scatter` | Two variables against each other. Residuals vs fitted, a beta. |
| `plot_hist` | A distribution — what `spark()` hints at, in readable form. |
| `plot_bar` | Categories. Exposure per sector, counts per status. |

```python
plot_line(logging.getLogger("myapp.plot"), nav, title="NAV")
```

```
                                     NAV
     ┌─────────────────────────────────────────────────────────────────┐
120.6┤                                                    ▐▙  ▄▖▄      │
     │                                                ▄▟  ▌▐▙▞▀▜ ▛▖    │
...
```

---

## Behaviour

**Nothing is built when the level is off.** The level check comes first: no
import of plotext, no figure, no string. Measured cost: ~0.3 µs.

**The size is fixed at 72×15.** Otherwise plotext measures the terminal, and the
same code renders differently depending on whether you are looking at a console
or a log file. The theme is `clear`.

**Rendering is locked.** plotext is a **globally stateful** module: `clf()`,
`plot()` and `build()` all work on one shared figure. Two threads plotting at the
same time would produce one scrambled chart. A module-level lock wraps the
prepare-and-build pair.

**Markup is disabled per record.** A chart is full of brackets — axis bounds, a
title containing `[%]` — and a `markup=True` `RichHandler` would interpret them
and raise on the first one that looks like a tag.

**ANSI escapes.** plotext emits them even under `theme("clear")`: 15 sequences
for a 16-line chart, all of them bare resets. `LoggingConfigurator` strips them
from every handler by default, so both your file and your console stay clean.
See [logging.md](logging.md#stripansitrue-default).

---

## Console width

A chart is 72 columns wide, and `RichHandler` adds ~29 columns of gutter plus ~15
for its right-hand path column. **Below 116 columns the chart is folded and
becomes unreadable.**

```python
LoggingConfigurator.configure(level="PLOT", console_width=120)
```

In a notebook the path column is dropped automatically and the width defaults to
120, so charts render correctly with no extra argument.

---

## Measured costs

| | Cost |
|---|---|
| Level off | ~0.3 µs |
| `plot_line`, 300 points | ~1.7 ms |
| `spark`, 300 points | ~12 µs |
| `import plotext` | ~15 ms warm, ~50 ms cold |

---

## Runnable examples

`examples/log/demo_03_plots.py` shows all four on data with recognisable shapes —
a trending random walk, a visible correlation, a bimodal law, seven categories —
and where 72×15 stops being enough. `examples/log/demo_04_cost.py` reproduces the
cost table on your machine.
