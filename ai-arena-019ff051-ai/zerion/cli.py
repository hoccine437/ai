"""
ZERION-X — GENESIS X10 Command-Line Interface
Implements full CLI interrogation, status monitoring, benchmark execution, and UI server controls.
"""

import argparse
import asyncio
import json
import sys
from zerion.engine import AscendantEngine
from zerion.runtime.evidence import collect_runtime_evidence
from zerion.runtime.reality_audit import run_reality_audit


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
    parser.add_argument("--ablation", action="store_true", help="Run systematic 11-subsystem ablation study")
    parser.add_argument("--trajectory", action="store_true", help="Display developmental learning trajectory")
    parser.add_argument("--reality-audit", action="store_true", help="Actually run the test suite and report real pass/fail/skip counts (never fabricated)")
    parser.add_argument("--audit-target", type=str, default=None, help="Optional targeted pytest path for --reality-audit (default: full tests/ suite)")
    parser.add_argument("--scoreboard", action="store_true", help="Display developmental scoreboard")
    parser.add_argument("--level", type=int, choices=range(1, 8), help="Query 7-Level Cognitive Hierarchy (1 to 7)")
    parser.add_argument("--introspect", action="store_true", help="Display self-model capabilities and limitations")
    parser.add_argument("--ui", action="store_true", help="Start the ZERION-X GENESIS Cybernetic Web Interface")
    parser.add_argument("--voice", action="store_true", help="Run the always-available voice perception service WITHOUT the web UI (engine-scoped; reports real microphone state, never fake listening)")
    parser.add_argument("--port", type=int, default=8080, help="Port for the UI web server (default: 8080)")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory for durable persistence")

    args = parser.parse_args()

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
            print(f"Effect Size: {trial.effect_size:+.4f}")
            print(f"Decision:    {trial.decision}")
            print(f"Rationale:   {trial.rationale}")

        elif args.benchmark:
            print("[GENESIS X10] Executing 14-Category Benchmark Suite...")
            report = await engine.benchmarks.run_all()
            print(f"\n================ BENCHMARK REPORT: {report.run_id} ================")
            print(f"Tasks Evaluated:              {report.total_tasks}")
            print(f"Average Baseline Score:       {report.avg_baseline_score:.3f}")
            print(f"Average Ascendant Score:      {report.avg_ascendant_score:.3f}")
            print(f"Improvement Ratio:            {report.composite_improvement_ratio:.2f}x")
            print(f"Effective Intelligence Score: {report.effective_intelligence_score:.4f}")

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
            # local readiness from REAL runtime checks before running.
            _print_readiness(engine)
            n = max(1, args.cycles)
            print(f"[GENESIS X10] Executing {n} autonomous developmental flywheel cycle(s)...")
            for i in range(n):
                trace = await engine.run_developmental_cycle()
                print(f"[{trace.cycle_id}] Strat={trace.strategy_selected:28} Mode={trace.cognitive_allocation_mode:12} Maturity={trace.maturity_level:20} Dur={trace.duration_ms:.1f}ms")
            evidence = collect_runtime_evidence(engine)
            snap = engine.scoreboard.capture_snapshot_from_evidence(evidence, cycles_run=engine._cycle_count)
            print("\n" + engine.scoreboard.render_summary_text(snap))

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
    print(f"LOCAL STT:       {stt['status']}"
          + (f"  ({stt['reason']})" if stt.get("reason") else ""))
    mod = r["models"]
    print(f"LOCAL MODEL:     {mod['status']}"
          + (f"  ({mod['dir']}, {mod['discovered']} discovered, "
             f"{mod['available']} available)" if mod.get("dir") else ""))
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
