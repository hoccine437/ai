"""
ZERION-X — GENESIS X10 Command-Line Interface
Implements full CLI interrogation, status monitoring, benchmark execution, and UI server controls.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
from zerion.engine import AscendantEngine
from zerion.runtime.evidence import collect_runtime_evidence
from zerion.runtime.reality_audit import run_reality_audit


async def _enter_persistent_runtime(engine: AscendantEngine,
                                    shutdown_event: asyncio.Event) -> None:
    """Transition the CLI process into the ACTIVE runtime state and wait.

    The runtime itself (event bus, CognitivePulse driver, voice perception,
    UI bridge) is already running underneath ``engine``; this only keeps the
    asyncio loop alive so the process stays resident and processes real
    events (voice, UI, pulse, cognition) until an explicit shutdown signal
    (Ctrl-C / SIGINT / SIGTERM, or a set ``shutdown_event``) arrives.

    Fully event-driven: zero idle CPU while waiting. The completion of a
    developmental cycle is ONE operation inside the runtime and must never
    terminate it — this wait is what keeps the runtime alive after the
    initial cycle and scoreboard (spec §3, §10, §15).
    """
    loop = asyncio.get_running_loop()
    # Install the shutdown handlers BEFORE announcing ACTIVE so there is no
    # window in which SIGINT/SIGTERM still has its default (terminating)
    # disposition — an operator who sees ACTIVE can always shut down cleanly.
    installed = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
            installed = True
        except (NotImplementedError, RuntimeError):
            # Non-UNIX platform or non-main-thread loop: fall back to periodic
            # wakeups; the default KeyboardInterrupt/termination still
            # interrupts the wait below and shuts down cleanly.
            pass
    print("\nZERION RUNTIME: ACTIVE")
    print("LIFECYCLE: PERSISTENT")
    print("STATE: WAITING_FOR_EVENTS")
    print("Ctrl-C to shut down cleanly.")
    try:
        if installed:
            await shutdown_event.wait()
        else:
            while not shutdown_event.is_set():
                await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        pass


async def _enter_interactive_chat(engine: AscendantEngine,
                                  shutdown_event: asyncio.Event,
                                  stdin=None) -> None:
    """Text-only product REPL: INPUT=TEXT, OUTPUT=TEXT+LOCAL VOICE.

    This is the canonical ``python main.py`` interactive experience on a real
    terminal (Termux/desktop TTY). Every turn is routed through the REAL
    CognitiveRuntime router — the exact same canonical path as the web UI
    (CommandAPI RUN_TASK) and the voice pipeline — and the response is spoken
    through the local offline TTS engine when one exists.

    Nothing here is simulated: a missing GGUF or TTS engine is reported
    honestly (never a faked READY), a failed turn NEVER terminates the
    runtime, and the loop keeps returning to ``YOU > ``. Only ``exit`` /
    ``quit``, EOF, or the shutdown event (Ctrl-C / SIGTERM) ends it.
    """
    stream = stdin if stdin is not None else sys.stdin
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except (NotImplementedError, RuntimeError):
            # Non-UNIX platform: default KeyboardInterrupt handling still
            # interrupts the await below and shuts down cleanly.
            pass

    from zerion.cognitive_os.router_types import RoutingMode, Task, TaskType

    # Banner values come from the REAL runtime — never hard-coded. The model
    # lines are evidence-based: a file existing is only DISCOVERY; COGNITION
    # ACTIVE is claimed only after a real load + inference probe verified
    # real tokens (see engine.local_readiness / gguf_backend).
    r = engine.local_readiness()
    models = r.get("models") or {}
    registry = getattr(engine, "local_model_registry", None)
    entries = registry.list_models() if registry is not None else []
    ms = models.get("status", "NO_LOCAL_MODEL_AVAILABLE")
    available = models.get("available") or 0
    selected = models.get("selected") or []
    backend = models.get("backend") or {}
    probe = models.get("probe") or {}
    if ms == "READY" and available:
        model_line = ", ".join(str(s) for s in selected) if selected else \
            f"{available} model(s) available"
    elif available:
        model_line = ", ".join(str(s) for s in selected) if selected else \
            f"{available} model(s) available (DISCOVERED)"
    elif entries:
        model_line = f"{len(entries)} discovered, 0 available"
    else:
        model_line = "NONE (no .gguf in models/)"
    tts = r.get("tts") or {}
    tts_line = "READY" if tts.get("status") == "AVAILABLE" \
        else tts.get("status", "UNKNOWN")
    if tts.get("reason"):
        tts_line = f"{tts_line} ({tts['reason']})"

    print("\nZERION X")
    print("────────────────────────────────")
    print(f"MODE        {r.get('mode', 'LOCAL')} OFFLINE")
    print("INPUT       TEXT")
    print("VOICE       OUTPUT ONLY")
    print(f"MODEL       {model_line}")
    print(f"BACKEND     {backend.get('name', 'UNKNOWN')}"
          + ("" if backend.get("available") else " (MISSING)"))
    print(f"INFERENCE   {probe.get('inference', 'NOT_VERIFIED')}")
    print(f"COGNITION   {'ACTIVE' if ms == 'READY' else 'MODEL_BLOCKED'}")
    print(f"TTS         {tts_line}")
    print("RUNTIME     ACTIVE")
    print("────────────────────────────────")
    if ms == "BLOCKED" and available:
        reason = probe.get("error") or models.get("reason") \
            or backend.get("install_hint") or "inference not verified"
        print(f"MODEL INFERENCE = FAILED — {reason}")
        low = reason.lower()
        if "timeout" in low or "still alive" in low:
            print("NOTE: the model was still loading when a timeout budget ran "
                  "out, not broken. Timeouts are unlimited by default; if you "
                  "set one, raise or unset ZERION_GGUF_PROBE_TIMEOUT / "
                  "ZERION_GGUF_TIMEOUT_SECONDS. On Android, copy the .gguf "
                  "into Termux home (mkdir -p ~/models && cp <model>.gguf "
                  "~/models/) — FUSE-backed /storage/emulated/0 loads much "
                  "slower; a smaller model also loads faster on this phone.")
    elif ms == "NO_LOCAL_MODEL_AVAILABLE":
        print("MODEL INFERENCE = NOT_VERIFIED (no local .gguf model)")
    print("Type a message and press Enter. 'exit' or Ctrl-C to quit.\n")

    runtime = engine.cognitive_runtime
    tts_provider = getattr(
        getattr(engine, "voice_pipeline", None), "tts_provider", None)

    def _read_line():
        try:
            return stream.readline()
        except Exception:  # noqa: BLE001 — treat any read error as EOF
            return None

    while not shutdown_event.is_set():
        sys.stdout.write("YOU > ")
        sys.stdout.flush()
        read_task = asyncio.create_task(asyncio.to_thread(_read_line))
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            {read_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED)
        if shutdown_task in done or shutdown_event.is_set():
            for t in pending:
                t.cancel()
            break
        shutdown_task.cancel()
        line = read_task.result()
        if line is None or line == "":
            print()
            break
        text = line.strip()
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            print("[ZERION] shutting down cleanly.")
            break
        try:
            print("[ZERION] THINKING...")
            # Real remembered context: instructions the user gave (their own
            # words, from the persistent UserLearningStore) are injected into
            # the prompt so the model can actually retrieve them. Without
            # signals the prompt is exactly the user's text.
            prompt_text = text
            try:
                user_learning = getattr(runtime, "user_learning", None)
                signals = (user_learning.learned_preferences()
                           if user_learning is not None else [])
                if signals:
                    lines = [f"- {s.snippet}" for s in signals[-5:]]
                    prompt_text = (
                        "User instructions Zerion has learned (the user's own "
                        "words; use as context):\n"
                        + "\n".join(lines)
                        + "\n\nUser message: " + text)
            except Exception:  # noqa: BLE001 — context injection never breaks a turn
                prompt_text = text
            task = Task(
                type=TaskType.CONVERSATION,
                description=f"User message: {text[:200]}",
                difficulty=0.3,
                uncertainty=0.4,
                novelty=0.3,
                stakes=0.1,
                goal_relevance=0.5,
                required_capabilities=set(),
                offline_required=True,
                verification_required=False,
                metadata={"source": "termux_chat"},
            )
            result = await runtime.execute_task(
                task, prompt_text, mode=RoutingMode.OFFLINE_ONLY)
            # Observable trace (ZERION_DEBUG=1): safe metadata only — never
            # internal chain-of-thought. request_id, model, backend, latency,
            # success and output length come from the REAL result.
            if os.environ.get("ZERION_DEBUG"):
                usage = getattr(result, "usage", None) or {}
                out_len = len(getattr(result, "output", "") or "")
                print(
                    f"[TRACE] request_id={task.task_id} "
                    f"model={getattr(result, 'model', None) or 'NONE'} "
                    f"backend={usage.get('backend') or 'NONE'} "
                    f"latency_ms={getattr(result, 'latency_ms', None)} "
                    f"success={bool(getattr(result, 'output', None))} "
                    f"output_len={out_len} "
                    f"status={getattr(getattr(result, 'status', None), 'value', 'FAILURE')}")
            out = getattr(result, "output", None)
            if out:
                print(f"\n[ZERION]\n{out}")
                # Local voice output through the REAL offline TTS engine.
                if tts_provider is not None:
                    tts_evidence = await asyncio.to_thread(
                        tts_provider.synthesize, out)
                    if tts_evidence.get("status") not in (
                            "AUDIO_GENERATED", "AUDIO_PLAYED"):
                        print(f"[ZERION] TTS: {tts_evidence.get('status')} — "
                              f"{tts_evidence.get('reason', 'no offline engine')}")
            else:
                status = getattr(getattr(result, "status", None),
                                 "value", "FAILURE")
                errors = getattr(result, "errors", None)
                tail = (" (LOCAL MODEL UNAVAILABLE — drop a .gguf into "
                        "models/)" if not available else
                        " (MODEL BLOCKED — see the readiness banner above; on "
                        "slow phones a smaller model or ZERION_GGUF_NO_MMAP=1 "
                        "helps)")
                print(f"\n[ZERION] {status}"
                      + (f" — {errors}" if errors else "") + tail)
            # Principle 8: real user-learning signals from every turn
            # (explicit preferences/corrections only; plain turns are neutral).
            user_learning = getattr(runtime, "user_learning", None)
            if user_learning is not None:
                user_learning.observe_turn(text, out or None)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a failed turn never kills runtime
            print(f"[ZERION] ERROR: {type(e).__name__}: {str(e)[:300]}")
            print("[ZERION] returning to input (runtime remains ACTIVE).")
        print()


def _print_inference_ledger(engine: AscendantEngine) -> None:
    """Render the observable inference ledger (real runtime records).

    Every request/result pair is a genuine USER INPUT -> ROUTER -> RESULT
    record captured by CognitiveRuntime.execute_task — never simulated.
    """
    ledger = engine.cognitive_runtime.inference_ledger
    s = ledger.summary()
    print("\n=== INFERENCE LEDGER (real runtime records) ===")
    print(f"Requests:  {s['total']}  (successes: {s['successes']}, "
          f"failures: {s['failures']})")
    if s["last"] is None:
        print("No inference has been executed yet "
              "(run --chat and send a message, or a task).")
    for req, res in zip(ledger.requests(), ledger.results()):
        print(f"[{res.request_id}] {res.provider or 'NONE'}/"
              f"{res.model or 'NONE'}")
        print(f"    input:  {req.user_input[:60]!r}")
        print(f"    output: {res.generated_text[:60]!r}"
              if res.generated_text else
              f"    output: NONE (status={res.termination_reason}, "
              f"error={res.error or 'none'})")
        print(f"    success={res.success} tokens=({res.prompt_tokens}, "
              f"{res.completion_tokens}) decision={res.decision} "
              f"({res.decision_reason})")


async def run_cli():
    parser = argparse.ArgumentParser(description="ZERION-X GENESIS X10 Developmental Intelligence Organism")
    parser.add_argument("--status", action="store_true", help="Display full organism developmental status")
    parser.add_argument("--readiness", action="store_true", help="Display ZERION LOCAL READINESS (real mic/STT/model/TTS/runtime/UI states; no API keys required)")
    parser.add_argument("--cycle", action="store_true", help="Execute 1 autonomous developmental flywheel cycle")
    parser.add_argument("--cycles", type=int, default=1, help="Execute N autonomous developmental flywheel cycles")
    parser.add_argument("--objective", action="store_true", help="Inspect active long-term continuous objectives")
    parser.add_argument("--problems", action="store_true", help="List autonomously discovered problems")
    parser.add_argument("--questions", action="store_true", help="List active ranked questions in genesis graph")
    parser.add_argument("--strategies", action="store_true", help="List registered cognitive strategies")
    parser.add_argument("--capabilities", action="store_true", help="List native and dynamically born capabilities")
    parser.add_argument("--memory", action="store_true", help="Inspect 7-domain developmental memory stores")
    parser.add_argument("--genome", action="store_true", help="Inspect 22-dimensional Cognitive Genome")
    parser.add_argument("--maturity", action="store_true", help="Assess current Cognitive Maturity Level (L0-L7)")
    parser.add_argument("--architecture", action="store_true", help="Inspect cognitive architecture topologies")
    parser.add_argument("--experiment", action="store_true", help="Run self-experimentation architecture trial")
    parser.add_argument("--benchmark", action="store_true", help="Run 14-category scientific benchmark suite")
    parser.add_argument("--cognitive-benchmark", action="store_true", help="Run ZERION_COGNITIVE_BENCHMARK (BASELINE vs ZERION, 10 categories, offline, deterministic)")
    parser.add_argument("--models", action="store_true", help="List locally discovered GGUF models (real file scan, honest metadata)")
    parser.add_argument("--inference", action="store_true", help="Show the observable inference ledger (real request/result records from the cognitive runtime)")
    parser.add_argument("--ablation", action="store_true", help="Run systematic 11-subsystem ablation study")
    parser.add_argument("--trajectory", action="store_true", help="Display developmental learning trajectory")
    parser.add_argument("--reality-audit", action="store_true", help="Actually run the test suite and report real pass/fail/skip counts (never fabricated)")
    parser.add_argument("--audit-target", type=str, default=None, help="Optional targeted pytest path for --reality-audit (default: full tests/ suite)")
    parser.add_argument("--scoreboard", action="store_true", help="Display developmental scoreboard")
    parser.add_argument("--level", type=int, choices=range(1, 8), help="Query 7-Level Cognitive Hierarchy (1 to 7)")
    parser.add_argument("--introspect", action="store_true", help="Display self-model capabilities and limitations")
    parser.add_argument("--ui", action="store_true", help="Start the ZERION-X GENESIS Cybernetic Web Interface")
    parser.add_argument("--voice", action="store_true", help="Run the always-available voice perception service WITHOUT the web UI (engine-scoped; reports real microphone state, never fake listening)")
    parser.add_argument("--chat", action="store_true", help="Run the interactive text REPL (YOU > -> CognitiveRuntime -> local TTS). Default when stdin is a terminal.")
    parser.add_argument("--port", type=int, default=8080, help="Port for the UI web server (default: 8080)")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory for durable persistence")

    args = parser.parse_args()

    shutdown_event = asyncio.Event()
    engine = AscendantEngine(data_dir=args.data_dir)
    await engine.start()

    try:
        if args.status:
            print("\n================ ZERION-X GENESIS X10 STATUS ================")
            mat = engine.maturity_evaluator.evaluate_from_evidence(collect_runtime_evidence(engine))
            print(f"System Name:       {engine.identity.system_name}")
            print(f"Cognitive State:   ORGANISM ACTIVE")
            print(f"Maturity Level:    {mat.current_level.value} (Level {mat.level_index}/7)")
            print(f"Genome Version:    v{engine.genome_manager.current_genome.version}")
            print(f"Active Objectives: {len(engine.continuous_objectives.list_active_objectives())}")
            print(f"Strategies Count:  {len(engine.strategy_registry.list_strategies())}")
            print(f"Capabilities:      {len(engine.self_model._capabilities)} active ({len(engine.capability_registry.list_born_capabilities())} born)")
            # Canonical Slice 4 stores — the legacy DevelopmentalMemoryStore is
            # a deprecated read-only view and is no longer written by the runtime.
            print(f"Memory Episodes:   {engine.cognitive_runtime.episode_store.count()}")
            print(f"Distilled Rules:   {engine.cognitive_runtime.distilled_store.count()}")

        elif args.objective:
            print("\n=== ACTIVE CONTINUOUS OBJECTIVES ===")
            for obj in engine.continuous_objectives.list_active_objectives():
                print(f"[{obj.objective_id}] {obj.title} (Priority: {obj.priority}, Progress: {obj.progress*100:.1f}%)")
                print(f"  Next Action: {obj.next_action}")

        elif args.problems:
            print("\n=== AUTONOMOUSLY DISCOVERED PROBLEMS ===")
            for p in engine.organism.problems.get_recent_problems():
                print(f"[{p.problem_id}] {p.title} (Urgency: {p.urgency}, Value: {p.expected_value})")

        elif args.questions:
            print("\n=== RANKED QUESTION GENESIS GRAPH ===")
            for q in engine.question_graph.list_questions()[:10]:
                print(f"[{q.id}] ({q.question_type.value}) {q.text} (Priority: {q.priority:.2f})")

        elif args.strategies:
            print("\n=== REGISTERED COGNITIVE STRATEGIES ===")
            for s in engine.strategy_registry.list_strategies():
                print(f"[{s.strategy_id}] {s.name} (Domain: {s.domain}, Reliability: {s.reliability*100:.1f}%)")

        elif args.capabilities:
            print("\n=== CAPABILITY CATALOG ===")
            for c in engine.self_model.what_can_i_do():
                print(f"  - {c['name']} ({c['category']}): Reliability={c['reliability']*100:.1f}%")

        elif args.memory:
            # Canonical Slice 4 memory stores (episodes + distilled experience).
            print("\n=== CANONICAL MEMORY STORES ===")
            print(f"Episodic Logs:     {engine.cognitive_runtime.episode_store.count()}")
            print(f"Distilled Rules:   {engine.cognitive_runtime.distilled_store.count()}")
            for d in engine.cognitive_runtime.distilled_store.list()[:5]:
                print(f"  - [{d.type.value}] {d.statement[:90]}")

        elif args.genome:
            print("\n================ COGNITIVE GENOME (v%d) ================" % engine.genome_manager.current_genome.version)
            d = engine.genome_manager.current_genome.to_dict()
            for k, v in d.items():
                if k not in ("mutation_history", "active_phenotypes"):
                    print(f"  {k:32}: {v}")

        elif args.maturity:
            mat = engine.maturity_evaluator.evaluate_from_evidence(collect_runtime_evidence(engine))
            print("\n================ COGNITIVE MATURITY LEVEL ================")
            print(f"Current Level:    {mat.current_level.value} (Level {mat.level_index} of 7)")
            print(f"Evidence Score:   {mat.evidence_score * 100:.1f}%")
            for c in mat.criteria_met:
                print(f"  [✓] {c}")

        elif args.architecture:
            print("\n=== COGNITIVE ARCHITECTURE TOPOLOGIES ===")
            for t_id, top in engine.organism.architecture_controller._topologies.items():
                print(f"[{top.topology_id}] {top.name}: {' -> '.join(top.cell_sequence)} (Cost: {top.resource_cost})")

        elif args.experiment:
            print("[ASCENDANT] Executing Self-Experimentation Architecture Trial...")
            trial = await engine.self_experimentation.run_architecture_experiment(
                hypothesis="Expanding verification depth improves debugging success",
                target_dimension="verification_ratio",
                control_val=0.80,
                treatment_val=0.95,
                target_phenotype="DebuggingPhenotype"
            )
            print(f"Trial ID:    {trial.experiment_id}")
            print(f"Hypothesis:  {trial.hypothesis}")
            if trial.effect_size is None:
                print("Effect Size: UNAVAILABLE (not measured — no eval_fn "
                      "supplied for this trial)")
            else:
                print(f"Effect Size: {trial.effect_size:+.4f}")
            print(f"Decision:    {trial.decision}")
            print(f"Rationale:   {trial.rationale}")

        elif args.benchmark:
            print("[GENESIS X10] Executing 14-Category Benchmark Suite "
                  "(real sandbox measurement where a harness is wired; "
                  "other categories reported NOT_MEASURED)...")
            report = await engine.benchmarks.run_all()
            print(f"\n================ BENCHMARK REPORT: {report.run_id} ================")
            print(f"Tasks Evaluated:              {report.total_tasks} "
                  f"({report.measured_tasks} measured, "
                  f"{report.total_tasks - report.measured_tasks} NOT_MEASURED)")
            if report.avg_baseline_score is None:
                print("Average Baseline Score:       UNAVAILABLE (no measured tasks)")
            else:
                print(f"Average Baseline Score:       {report.avg_baseline_score:.3f}")
            if report.avg_ascendant_score is None:
                print("Average Ascendant Score:      UNAVAILABLE (no measured tasks)")
            else:
                print(f"Average Ascendant Score:      {report.avg_ascendant_score:.3f}")
            if report.composite_improvement_ratio is None:
                print("Improvement Ratio:            UNAVAILABLE")
            else:
                print(f"Improvement Ratio:            {report.composite_improvement_ratio:.2f}x")
            if report.effective_intelligence_score is None:
                print("Effective Intelligence Score: UNAVAILABLE "
                      "(transfer factor not measured)")
            else:
                print(f"Effective Intelligence Score: "
                      f"{report.effective_intelligence_score:.4f}")

        elif args.cognitive_benchmark:
            from pathlib import Path as _Path
            print("[SLICE 9] Executing ZERION_COGNITIVE_BENCHMARK "
                  "(BASELINE vs ZERION + verification ablation, offline)...")
            from zerion.cognitive_os.benchmark import run_end_to_end_benchmark
            run = run_end_to_end_benchmark(
                output_dir=str(_Path(args.data_dir) / "benchmark_runs"))
            overall = run.analysis.get("overall", {})
            b = (overall.get("modes") or {}).get("BASELINE")
            z = (overall.get("modes") or {}).get("ZERION")
            ratio = overall.get("success_rate_ratio")
            print(f"\n================ COGNITIVE BENCHMARK: {run.manifest.run_id} ================")
            print(f"Integrity:            {run.integrity.get('status')}")
            if b:
                print(f"BASELINE success:     {b['successes']}/{b['n']} "
                      f"({b['success_rate'] * 100:.1f}%)")
            if z:
                print(f"ZERION success:       {z['successes']}/{z['n']} "
                      f"({z['success_rate'] * 100:.1f}%)")
            print(f"Aggregate ratio:      {('%.2fx' % ratio) if ratio is not None else 'UNKNOWN'} "
                  "(pooled across task classes; NOT an intelligence claim)")
            print(f"Trials per task:      {run.manifest.trials_per_task}")
            print(f"Modes:                {', '.join(run.manifest.modes)}")
            print(f"Report:               ZERION_COGNITIVE_BENCHMARK.md")

        elif args.ablation:
            print("[GENESIS X10] Ablation study (SIMULATED reference priors — "
                  "no empirical ablation executed; scores are illustrative, "
                  "NOT measurements)")
            from zerion.experiments.ablation_study import AblationStudyRunner
            runner = AblationStudyRunner()
            report = await runner.run_ablation_matrix()
            print(f"Full Baseline Score (SIMULATED): {report.full_ascendant_baseline:.4f}")
            print(f"Most Critical (SIMULATED):       {report.most_critical_component}")
            for res in report.ablation_results:
                print(f"  {res.config_name:18}: Score={res.overall_score:.3f} (Drop: {res.degradation_percent:5.1f}%) "
                      f"Criticality: {res.criticality} [{res.measurement_status}]")

        elif args.trajectory:
            print("\n=== DEVELOPMENTAL LEARNING TRAJECTORY ===")
            acc_ratio = engine.learning_to_learn.calculate_learning_acceleration()
            print(f"Current Learning Acceleration Ratio: {acc_ratio:.2f}x")
            print(f"Total Snapshots Recorded:            {len(engine.timeline._snapshots)}")

        elif args.reality_audit:
            result = run_reality_audit(target=args.audit_target)
            print("\n" + result.render_text())
            if not result.all_passed:
                sys.exit(1)

        elif args.models:
            print("\n=== LOCAL GGUF MODELS (real discovery) ===")
            registry = engine.local_model_registry
            models = registry.list_models()
            print(f"Models dir: {registry.models_dir}")
            if not models:
                print("No .gguf models discovered (empty or missing models directory).")
            for m in models:
                print(f"[{m['model_id']}] {m['filename']} "
                      f"({m['size_mb']} MB, {m['availability']}, {m['load_status']})")
                print(f"    context={m['context_window'] or 'UNKNOWN'} "
                      f"arch={m['architecture']} quant={m['quantization']} "
                      f"caps={','.join(m['capabilities']) or 'UNKNOWN'}")

        elif args.inference and not args.chat:
            # Standalone mode: print the ledger of the CURRENT process. To see
            # a live chat session's records, combine with --chat so the REPL
            # runs first and the ledger prints on exit (the ledger is real
            # per-process runtime state, never persisted or fabricated).
            _print_inference_ledger(engine)

        elif args.level:
            ans = engine.answer_hierarchy_level(args.level)
            print(f"\n=== LEVEL {args.level} INTROSPECTION QUERY ===")
            print(json.dumps(ans, indent=2))

        elif args.introspect:
            print("\n=== SELF-MODEL INTROSPECTION ===")
            for cap in engine.self_model.what_can_i_do():
                print(f"  - {cap['name']} ({cap['category']}): reliability {cap['reliability']*100:.1f}%, latency {cap['avg_latency_ms']}ms")

        elif args.scoreboard:
            evidence = collect_runtime_evidence(engine)
            snap = engine.scoreboard.capture_snapshot_from_evidence(evidence, cycles_run=engine._cycle_count)
            print(engine.scoreboard.render_summary_text(snap))

        elif args.readiness:
            # ZERION LOCAL READINESS — real measured per-subsystem states.
            # No OpenAI/Gemini key is required; LOCAL is the canonical mode.
            _print_readiness(engine)

        elif args.voice:
            # Slice 10.1: voice-first daemon. Runs the always-available voice
            # perception service with NO UI open. Reports the exact microphone
            # state from real telemetry (LISTENING only when genuinely active).
            svc = engine.voice_perception
            tele = svc.telemetry()
            print(f"\n[ZERION VOICE] perception service started "
                  f"(independent of UI: {tele['independent_of_ui']})")
            print(f"[ZERION VOICE] mic phase:     {tele['mic_phase']}")
            print(f"[ZERION VOICE] health:        {tele['health']}")
            print(f"[ZERION VOICE] is_listening:  {tele['is_listening']}")
            print(f"[ZERION VOICE] stt:           {tele['stt']['status']} "
                  f"({tele['stt']['reason'] or 'n/a'})")
            if not tele["is_listening"]:
                print(f"[ZERION VOICE] NOT listening — reason: "
                      f"{tele['mic_reason'] or tele['mic'].get('reason')}")
            print("\nVoice perception running. Ctrl-C to stop.")
            try:
                while True:
                    await asyncio.sleep(3600)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass

        elif args.ui:
            from zerion.ui.server import GenesisWebServer
            server = GenesisWebServer(engine=engine, host="0.0.0.0", port=args.port)
            await server.start()
            print(f"[GENESIS UI] Live interactive interface running at http://0.0.0.0:{args.port}")
            try:
                while True:
                    await asyncio.sleep(3600)
            except (asyncio.CancelledError, KeyboardInterrupt):
                await server.stop()

        else:
            # Canonical startup contract (spec §35): python main.py verifies
            # local readiness from REAL runtime checks before running. On a
            # phone the probe really loads the .gguf, which can take minutes;
            # say so instead of appearing hung. The probe waits as long as it
            # takes (unlimited by default); ZERION_GGUF_PROBE_TIMEOUT bounds
            # the wait for users who want one.
            print("[ZERION] Verifying local model readiness — the probe really "
                  "loads the .gguf and waits as long as it takes (unlimited "
                  "by default; set ZERION_GGUF_PROBE_TIMEOUT to bound it).")
            _print_readiness(engine)
            n = max(1, args.cycles)
            print(f"[GENESIS X10] Executing {n} autonomous developmental flywheel cycle(s)...")
            for i in range(n):
                trace = await engine.run_developmental_cycle()
                print(f"[{trace.cycle_id}] Strat={trace.strategy_selected:28} Mode={trace.cognitive_allocation_mode:12} Maturity={trace.maturity_level:20} Dur={trace.duration_ms:.1f}ms")
            evidence = collect_runtime_evidence(engine)
            snap = engine.scoreboard.capture_snapshot_from_evidence(evidence, cycles_run=engine._cycle_count)
            print("\n" + engine.scoreboard.render_summary_text(snap))
            # Lifecycle: the developmental cycle is ONE operation inside the
            # runtime — its completion must NOT terminate Zerion. On an
            # interactive terminal, enter the text REPL (YOU > -> real
            # cognitive runtime -> local TTS); otherwise transition to ACTIVE
            # / WAITING_FOR_EVENTS until explicit shutdown (headless previews,
            # daemon runs, tests). Both paths keep the runtime resident.
            try:
                is_tty = sys.stdin.isatty()
            except Exception:  # noqa: BLE001
                is_tty = False
            if args.chat or is_tty:
                await _enter_interactive_chat(engine, shutdown_event)
            else:
                await _enter_persistent_runtime(engine, shutdown_event)
            # Session evidence (opt-in): --inference prints the real
            # request/result records captured by this process's runtime.
            if args.inference:
                _print_inference_ledger(engine)

    finally:
        await engine.stop()


def _print_readiness(engine: AscendantEngine) -> None:
    """ZERION LOCAL READINESS — real measured per-subsystem states, never
    hard-coded. No OpenAI/Gemini key is required; LOCAL is the canonical mode.
    """
    r = engine.local_readiness()
    print("\n================ ZERION LOCAL READINESS ================")
    print(f"MODE:            {r['mode']}")
    mic = r["microphone"]
    print(f"MICROPHONE:      {mic['status']}"
          + (f"  ({mic['reason']})" if mic.get("reason") else ""))
    stt = r["stt"]
    stt_status = stt.get("display_status") or stt["status"]
    stt_detail = stt.get("reason") or ""
    stt_models = stt.get("models") or {}
    if stt_models.get("discovered") is not None:
        stt_detail = (f"{stt_detail} · {stt_models['discovered']} model(s) "
                      f"in {stt_models.get('dir', 'models/stt')}").strip(" ·")
    print(f"LOCAL STT:       {stt_status}"
          + (f"  ({stt_detail})" if stt_detail else ""))
    mod = r["models"]
    # Evidence-based lifecycle: DISCOVERED -> BACKEND -> LOAD -> PROBE -> READY.
    print("LOCAL MODEL:")
    print(f"  DISCOVERED:    {'YES' if mod.get('discovered') else 'NO'}"
          f" ({mod.get('discovered', 0)} file(s), "
          f"{mod.get('available', 0)} valid)"
          + (f"  dir={mod.get('dir')}" if mod.get("dir") else ""))
    if mod.get("selected_path"):
        print(f"  PATH:          {mod['selected_path']}")
    b = mod.get("backend") or {}
    print(f"  BACKEND:       {b.get('name', 'UNKNOWN')}"
          + ("" if b.get("available") else " (MISSING)"))
    p = mod.get("probe") or {}
    print(f"  LOADABLE:      {p.get('loadable', 'NOT_ATTEMPTED')}")
    print(f"  INFERENCE:     {p.get('inference', 'NOT_VERIFIED')}")
    print(f"  STATUS:        {mod.get('status', 'UNKNOWN')}"
          + (f"  ({mod.get('reason')})" if mod.get("reason") else ""))
    if p.get("probe_latency_ms") is not None:
        print(f"  PROBE LATENCY: {p['probe_latency_ms']} ms")
    if p.get("error"):
        print(f"  PROBE ERROR:   {p['error']}")
    tts = r["tts"]
    print(f"LOCAL TTS:       {tts['status']}"
          + (f"  ({tts['reason']})" if tts.get("reason") else ""))
    rt = r["runtime"]
    print(f"RUNTIME:         started={rt['started']} "
          f"offline_mode={rt['offline_mode']}")
    print(f"UI BRIDGE:       {r['ui']['status']}")
    print(f"NETWORK:         {r['network'].get('state')} "
          f"(LOCAL cognition never requires it)")
    print(f"KEYS:            OPENAI={r['keys']['OPENAI_API_KEY']} "
          f"GEMINI={r['keys']['GEMINI_API_KEY']} "
          f"(none required for LOCAL mode)")


def main():
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
