# ZERION X — RUNTIME LIFECYCLE FIX REPORT

**Scope:** fix the exact bug where `python main.py` exited immediately after the
initial developmental cycle + scoreboard. No architecture changes, no new
generation, no cloud reintroduction.

---

## 1. Exact root cause

`zerion/cli.py::run_cli()` — the **default (no-flag) CLI path** — performed:

```
INITIALIZE → READINESS → RUN 1 DEVELOPMENTAL CYCLE → PRINT SCOREBOARD → return
```

After printing the scoreboard the CLI coroutine **returned**, so
`asyncio.run()` completed, the event loop shut down, `engine.stop()` ran via
the `finally` block, and the process exited **0** — a normal application
completion, not a crash. A developmental cycle was treated as if it were the
whole runtime lifetime: there was no code path that transitioned into an
ACTIVE / WAITING_FOR_EVENTS state after the cycle.

The runtime subsystems (event bus, pulse driver, voice perception, UI bridge)
were started underneath `engine`, but the CLI never waited on them — the
asyncio loop just drained and exited.

## 2. Exact file and function responsible

| Item | Value |
|---|---|
| File | `zerion/cli.py` |
| Function | `run_cli()` (default branch, previously ~line 273) |
| Missing piece | any post-scoreboard wait on the persistent runtime |

## 3. Exact lifecycle path BEFORE fix

```
main() → asyncio.run(run_cli())
  engine.start()                      # runtime subsystems UP
  print ZERION LOCAL READINESS
  run 1 developmental flywheel cycle  # [GENESIS X10]
  print DEVELOPMENTAL SCOREBOARD
  run_cli() RETURNS                  ← BUG
asyncio.run() completes
engine.stop() via finally
process EXIT 0                       ← premature, though "clean"
```

## 4. Exact lifecycle path AFTER fix

```
main() → asyncio.run(run_cli())
  engine.start()
  print ZERION LOCAL READINESS
  run 1 developmental flywheel cycle
  print DEVELOPMENTAL SCOREBOARD
  _enter_persistent_runtime(engine, shutdown_event)   ← FIX
    install SIGINT/SIGTERM → shutdown_event handlers (before ACTIVE print)
    print ZERION RUNTIME: ACTIVE / LIFECYCLE: PERSISTENT / STATE: WAITING_FOR_EVENTS
    await shutdown_event.wait()       # fully event-driven, zero idle CPU
  (Ctrl-C / SIGINT / SIGTERM → event set)
  run_cli() returns → engine.stop() via finally
  process EXIT 0                       ← explicit shutdown only
```

The wait is a single `asyncio.Event.wait()` — no polling loop, no CPU burn.
On platforms without asyncio signal handlers it falls back to a 1 s periodic
wakeup (still event-driven, bounded CPU).

## 5. Files changed

| File | Change |
|---|---|
| `zerion/cli.py` | Added `_enter_persistent_runtime()` seam (signal handlers + event-driven wait, ACTIVE state banner); default path calls it after the scoreboard |
| `tests/test_runtime_lifecycle.py` | **New** — 3 lifecycle regression tests (wait blocks / event-driven; fallback loop; cycle completion never stops the runtime) |
| `tests/test_local_model_execution.py` | Replaced the one-shot flywheel subprocess test with a persistent-runtime test: bare `main.py` stays alive after cycle+scoreboard, then exits 0 on SIGINT |

## 6. Tests added

- `tests/test_runtime_lifecycle.py::TestPersistentRuntimeWait`
  - `test_wait_blocks_until_shutdown_event_event_driven` — wait task stays
    pending while idle, engine never stopped, releases on shutdown event
  - `test_wait_fallback_loop_without_signal_support` — non-UNIX fallback still
    blocks and releases cleanly
  - `test_cycle_completion_does_not_stop_runtime` — a completed developmental
    cycle does NOT stop the runtime; only the CLI `finally` (explicit
    shutdown) stops it
- `tests/test_local_model_execution.py::TestMainPyCanonicalEntrypoint`
  - `test_default_python_main_py_enters_active_runtime_and_stays_alive` —
    real subprocess `python main.py`: asserts readiness, flywheel cycle,
    `ZERION RUNTIME: ACTIVE` + `STATE: WAITING_FOR_EVENTS`, **process still
    alive after the scoreboard**, then clean exit 0 on SIGINT

## 7. Full test result

```
python3 -m compileall -q zerion tests main.py     → clean
python3 -m pytest -q                              → 854 passed, 2 skipped
python3 -m pytest tests/test_architectural_invariants.py -q → 89 passed
```

- Previous baseline: 851 passed, 2 skipped → **+3 lifecycle tests**
- Invariants unchanged: **89/89**
- New lifecycle tests pass under `IsolatedAsyncioTestCase` (genuinely awaited,
  no silent no-ops)

## 8. Actual process exit behavior BEFORE fix

Verified against the prior wiring: `python main.py` printed readiness →
flywheel cycle → scoreboard → the CLI coroutine returned → `asyncio.run`
completed → process exited **0** immediately, shell prompt returned. Exit
code 0 confirmed this was a normal early completion, not a crash.

## 9. Actual process persistence AFTER fix

Real run, keys unset (`-u OPENAI_API_KEY -u GEMINI_API_KEY`), bare
`python main.py`:

```
12: [GENESIS X10] Executing 1 autonomous developmental flywheel cycle(s)...
17: ZERION-X ASCENDANT DEVELOPMENTAL SCOREBOARD
35: ZERION RUNTIME: ACTIVE
    LIFECYCLE: PERSISTENT
    STATE: WAITING_FOR_EVENTS
    Ctrl-C to shut down cleanly.
--- ALIVE AFTER 7s: YES
--- (SIGINT sent)
EXIT=0
```

The process remained resident past the cycle + scoreboard (observed alive at
+7 s, previously dead at ~1 s), then shut down cleanly on explicit SIGINT with
exit code 0. Ordering proof: cycle → scoreboard → ACTIVE, all real output.

## 10. Android/Termux findings

**Not an Android problem.** The bug is an application lifecycle bug and is
fixed and proven at the application layer: bare `python main.py` now stays
alive indefinitely in a normal environment. Any subsequent Termux/Android
killing of a *resident* process would be an OS-level lifecycle issue
(foreground-service/`termux-wake-lock` territory) and is out of scope for
this fix — the app no longer exits on its own.

## 11. Remaining limitations

- Physical microphone/voice event injection was not exercised in this
  headless container (unchanged from the STT pass); the lifecycle fix keeps
  the process resident so those events can be processed when hardware exists.
- The SIGINT/SIGTERM wiring uses `asyncio` signal handlers (UNIX). On Windows
  the fallback periodic-wakeup wait applies — same behavior, slightly higher
  (still negligible) wake frequency.
- No debug instrumentation was left behind; the only new prints are the four
  permanent ACTIVE-state lines, which are the spec-required lifecycle banner.

---

## Acceptance checklist

- [x] `python main.py` is unchanged as the canonical startup command
- [x] Starts the real Zerion X runtime (readiness block, GENESIS X10 flywheel)
- [x] Developmental cycle completion does NOT terminate the runtime
- [x] Scoreboard prints, then runtime enters ACTIVE / WAITING_FOR_EVENTS
- [x] Process stays resident (observed alive after the cycle; shell does not return)
- [x] Fully event-driven wait — no busy loop, no CPU burn
- [x] Exits only on explicit shutdown (Ctrl-C / SIGINT / SIGTERM) with code 0
- [x] Architectural invariants intact (89/89)
- [x] Full regression green (854 passed, 2 skipped)
