# `utilities.probe` — latency and memory instrumentation

Answers three questions without reaching for a profiler: **where does the time
go**, **is it CPU or waiting**, and **what allocates**. Designed to be left in
production code, because when it is off it costs nothing at all.

```python
from utilities import probed
from utilities.probe import probe, report
```

> `probe` (the context manager) is imported from `utilities.probe`, not from
> `utilities`. It shares its name with the subpackage, and re-exporting it at
> package level would overwrite the `utilities.probe` module attribute and break
> `import utilities.probe.render`.

---

## Two rules before anything else

**1. Only instrument blocks of 400 µs or more.** A probe costs ~1.15 µs when
enabled. Instrument the loop, never the iteration — otherwise you are measuring
your own instrumentation.

**2. Never draw latency conclusions from a tier 2 run.** `tracemalloc` slows the
*whole process* down, not just the measured blocks: a bare function call goes
from 14 ns to 158 ns, a factor of 11. Tier 1 answers "how long", tier 2 answers
"how much memory". Not both in the same run.

---

## Activation

The tier is read **once, at import time**, from the environment:

| `PROBE_TIER` | Tier | Effect |
|---|---|---|
| `0`, `off`, `false`, `no`, empty, unset | 0 | Nothing is measured, no wrapper is installed |
| `1`, `time`, `on`, `true`, `yes` | 1 | Wall-clock, CPU and allocation-free timing |
| `2`, `mem`, `memory`, `full` | 2 | Tier 1 plus `tracemalloc` |

```bash
PROBE_TIER=1 python my_script.py
```

**The tier is frozen at import and cannot be changed afterwards.** That is the
direct counterpart of the zero-cost guarantee: at tier 0 `probed()` returns your
function unchanged, so there is no wrapper to wake up later.

```python
import utilities                    # <- the tier is read HERE
os.environ["PROBE_TIER"] = "1"      # <- no effect, too late
```

There is deliberately no function to enable measurement from code: a flag
re-read on every call would cost 200–400 ns per probe, including when nobody is
measuring.

In a notebook, set the variable in the very first cell, **before** importing
`utilities`, and restart the kernel if the package is already imported.

---

## Measuring

### `probe(label: str) -> ContextManager[Probe]`

Measures a block. Returns the `Probe` itself, so you can read the numbers on the
spot.

```python
with probe("cursor.execute") as p:
    cursor.execute(sql)
print(p.wall_s, p.wait_s)
```

At tier 0 this returns a shared no-op singleton: no allocation, ~81 ns for the
`with` statement itself.

### `probed(label: str | None = None) -> Callable[[F], F]`

Decorator, for both sync functions and coroutines. The default label is
`module.qualname`.

```python
@probed()
def fetch_rows(cursor, sql):
    cursor.execute(sql)
    return cursor.fetchall()

@probed("api.fetch")
async def fetch(session, url):
    return await session.get(url)
```

**At tier 0 it returns the function unchanged** — `probed()(f) is f` — so there
is no wrapper, no extra frame, and no per-call test. Measured overhead at tier 0:
0.0 ns.

Decorators already applied are unwrapped through `__wrapped__` to detect
coroutines, so stacking `@probed()` with `functools.wraps`-based decorators works
in either order.

---

## Reading the numbers

### `Probe`

One measured block.

| Attribute | Meaning |
|---|---|
| `label: str` | The name it was measured under |
| `wall_s: float` | Elapsed time, wall clock |
| `cpu_s: float` | **Thread** CPU time (user + system) |
| `self_s: float` | `wall_s` minus the time of nested probes |
| `alloc_kib: float` | Tier 2 only: **net retained** allocation |
| `wait_s` (property) | `wall_s - cpu_s` |

**`wait_s` is the metric that decides what to do next.** Close to `wall_s`, you
are waiting on a database, a network share or a disk, and rewriting Python will
gain you nothing. Close to zero, the code itself is the problem.

`cpu_s` is *thread* CPU time, not process CPU time. With process time, a block
that sleeps while two other threads compute would report `wait ≈ 0` — the exact
opposite of the truth. Work handed to other threads is therefore not charged to
the block that waits on it.

`alloc_kib` is a **net retained** delta, not the total volume allocated. A block
that allocates 1 GiB and frees it reports ~0.

### `Stat`

Aggregate of every call sharing a label.

| Member | Meaning |
|---|---|
| `label`, `n` | Name and call count |
| `wall_s`, `cpu_s`, `self_s`, `alloc_kib` | Sums over all calls |
| `wait_s`, `mean_s` (properties) | `wall_s - cpu_s`, `wall_s / n` |
| `quantile(q: float) -> float` | Nearest-rank quantile of `wall_s` |

Up to 20 000 samples per label are kept for quantiles; past that, totals keep
accumulating but the sample reservoir stops growing.

### `registry: dict[str, Stat]` and `snapshot() -> list[Stat]`

`registry` maps labels to their aggregate. **Use `snapshot()` to iterate it** in
any program with threads: iterating the dict directly while another thread
measures raises `RuntimeError: dictionary changed size during iteration`.
`snapshot()` takes the lock and returns a list.

---

## Reporting

### `report(stream=None, *, sort="wall", rich=None) -> str`

Always returns the plain-text table. What it *prints* depends on the arguments:

| Call | Behaviour |
|---|---|
| `report()` | Rich table on the logger's shared console, or stderr |
| `report(stream=sys.stdout)` | Plain text to that stream, `rich` ignored |
| `report(rich=False)` | Prints nothing, only returns the text |

`sort` is `"wall"`, `"self"`, `"wait"` or `"n"`; anything else raises
`ValueError`.

```
label                                  n       wall       self       wait        mean         p95
-------------------------------------------------------------------------------------------------
db.execute                             4     4.310s     4.310s     4.290s   1077.50ms   1131.02ms
transform                              1     0.412s     0.412s     0.001s    412.30ms    412.30ms
```

- **`sort="wait"`** answers "am I waiting on someone else's machine?"
- **`sort="self"`** gives the real ranking. `self = wall - children`, the
  equivalent of cProfile's `tottime`: a function that only delegates tops the
  `wall` ranking while being entirely innocent.

> **`sort="self"` is not readable under `asyncio.gather`.** Each Task gets a copy
> of the context, so a child running in another Task never subtracts from its
> parent: parent and children both claim the same time, and the sum of `self`
> exceeds the program's duration. On concurrent code, read `wall` and `wait`.

### `to_dicts(*, sort="wall") -> list[dict]`

Serialisable rows — JSON, CSV, or a DataFrame in the consuming project. Keys:
`label`, `n`, `wall_s`, `cpu_s`, `self_s`, `wait_s`, `mean_s`, `p95_s`,
`alloc_kib`. The module adds no dependency for this.

### `reset() -> None`

Empties the registry. Also clears the "already reported" marker, so the
end-of-process table still prints afterwards.

### Automatic report

When the tier is active, the table is printed **once** as the process exits. An
explicit `report()` replaces it — there is no double printing. In a notebook this
fires when the kernel shuts down.

---

## Per-call logging

Nothing is logged by default: a formatted `LogRecord` costs 10–30 µs, ten times a
probe, so on 10 000 calls you would be measuring your own logging. Measurements
are aggregated instead.

To follow each block live, listen to the `utilities.probe` logger at level
`PERF` (15):

```python
from utilities import LoggingConfigurator
LoggingConfigurator.configure(level="PERF", console_width=140)
```

```
PERF  db.execute       wall=  0.060s cpu=  0.000s wait=  0.060s self=  0.060s
```

`PERF` sits between `DEBUG` (10) and `INFO` (20), so a run turned down to DEBUG
shows measurements for free while an INFO run hides them. Each record carries the
`Probe` object in `record.probe`.

**The module never adds a handler and never touches the host's logging
configuration.**

---

## Constants

| Name | Value |
|---|---|
| `TIER` | `0`, `1` or `2`, frozen at import |
| `ENABLED` | `TIER > 0` |
| `PERF` | `15` |

---

## Measured costs

On CPython 3.13, Apple Silicon — reproduce them with
`python examples/probe/demo_02_overhead.py`.

| | bare call | `@probed` overhead | `with probe(...)` overhead |
|---|---|---|---|
| Tier 0 | 14.3 ns | **0.0 ns** | 80.9 ns |
| Tier 1 | 13.7 ns | 1 150 ns | 1 119 ns |
| Tier 2 | **157.6 ns** | 8 075 ns | 7 939 ns |

The tier 2 "bare call" column is the point of rule 2: code you never
instrumented is 11× slower under `tracemalloc`.

Import cost of the module itself: **685 µs**. (`import utilities` as a whole
costs ~45 ms, dominated by `rich` — that is pre-existing and unrelated.)

The registry lock adds ~69 ns per measurement. It is not optional: `n += 1` is a
non-atomic LOAD/ADD/STORE even under the GIL, so two threads measuring the same
label would silently lose increments.

---

## Known limits

- **No hot switching.** The tier is frozen at import. This is a deliberate
  trade, documented above.
- **Async `self_s`.** Children in other Tasks do not decrement their parent. Read
  `wall` and `wait` on concurrent code.
- **Async `cpu_s`.** Coroutines share a thread, so two probes that overlap in
  time both count the same CPU.
- **Not a profiler.** No sampling, no flame graph, no stack. `probe` tells you
  *which* block costs; to find out *why*, inside that block, use a real profiler:

  ```bash
  uv run --with pyinstrument pyinstrument my_script.py
  ```

---

## Runnable examples

In [`examples/probe/`](../examples/probe/) — each runs on its own with no
arguments.

| Script | Shows |
|---|---|
| `demo_01_tiers.py` | The same workload under all three tiers |
| `demo_02_overhead.py` | The cost table above, on your machine |
| `demo_03_io_vs_cpu.py` | `wait` telling I/O from CPU |
| `demo_04_nesting.py` | `wall` ranking vs `self` ranking |
| `demo_05_async.py` | Attribution under `gather`, and its traps |
| `demo_06_render.py` | Every output format |
| `probe_playground.py` / `.ipynb` | Everything, as cells to play with |
