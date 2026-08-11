"""
ZERION-X — ASCENDANT ∞ Command-Line Interface
"""

import argparse
import asyncio
import json
import sys
from zerion.engine import AscendantEngine


async def run_cli():
    parser = argparse.ArgumentParser(description="ZERION-X ASCENDANT ∞ Developmental Intelligence Substrate")
    parser.add_argument("--cycle", action="store_true", help="Execute 1 autonomous developmental flywheel cycle")
    parser.add_argument("--cycles", type=int, default=1, help="Execute N autonomous developmental flywheel cycles")
    parser.add_argument("--benchmark", action="store_true", help="Run 14-category scientific benchmark suite")
    parser.add_argument("--scoreboard", action="store_true", help="Display developmental scoreboard")
    parser.add_argument("--genome", action="store_true", help="Inspect 22-dimensional Cognitive Genome")
    parser.add_argument("--maturity", action="store_true", help="Assess current Cognitive Maturity Level (L0-L7)")
    parser.add_argument("--level", type=int, choices=range(1, 8), help="Query 7-Level Cognitive Hierarchy (1 to 7)")
    parser.add_argument("--introspect", action="store_true", help="Display self-model capabilities and limitations")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory for durable persistence")

    args = parser.parse_args()

    engine = AscendantEngine(data_dir=args.data_dir)
    await engine.start()

    try:
        if args.genome:
            print("\n================ COGNITIVE GENOME (v%d) ================" % engine.genome_manager.current_genome.version)
            d = engine.genome_manager.current_genome.to_dict()
            for k, v in d.items():
                if k not in ("mutation_history", "active_phenotypes"):
                    print(f"  {k:32}: {v}")
            print("\n[Active Phenotypes]")
            for p in ["CodingPhenotype", "ResearchPhenotype", "DebuggingPhenotype", "MathematicalPhenotype", "SecurityPhenotype"]:
                ph = engine.genome_manager.get_phenotype(p)
                print(f"  - {ph.name:24} (Depth={ph.reasoning_depth}, Verif={ph.verification_ratio*100:.0f}%, ExpRate={ph.experiment_rate*100:.0f}%)")

        elif args.maturity:
            mat = engine.maturity_evaluator.evaluate(
                has_native_caps=True,
                episodes_count=len(engine.memory._episodes),
                procedural_rules_count=len(engine.memory._procedural_rules),
                flywheel_cycles=engine._cycle_count
            )
            print("\n================ COGNITIVE MATURITY LEVEL ================")
            print(f"Current Level:    {mat.current_level.value} (Level {mat.level_index} of 7)")
            print(f"Evidence Score:   {mat.evidence_score * 100:.1f}%")
            print("\n[Criteria Met]")
            for c in mat.criteria_met:
                print(f"  [✓] {c}")
            if mat.criteria_pending:
                print("\n[Criteria Pending]")
                for p in mat.criteria_pending:
                    print(f"  [ ] {p}")

        elif args.level:
            ans = engine.answer_hierarchy_level(args.level)
            print(f"\n=== LEVEL {args.level} INTROSPECTION QUERY ===")
            print(json.dumps(ans, indent=2))

        elif args.benchmark:
            print("[ASCENDANT ∞] Executing 14-Category Benchmark Suite...")
            report = await engine.benchmarks.run_all()
            print(f"\n================ BENCHMARK REPORT: {report.run_id} ================")
            print(f"Tasks Evaluated:              {report.total_tasks}")
            print(f"Average Baseline Score:       {report.avg_baseline_score:.3f}")
            print(f"Average Ascendant Score:      {report.avg_ascendant_score:.3f}")
            print(f"Improvement Ratio:            {report.composite_improvement_ratio:.2f}x")
            print(f"Effective Intelligence Score: {report.effective_intelligence_score:.4f}")
            print("----------------------------------------------------------------")
            for t in report.task_results:
                print(f"[{t.category.upper():18}] {t.task_id}: Score={t.ascendant_score:.2f} vs Base={t.baseline_score:.2f} Latency={t.latency_ms:.1f}ms")

        elif args.introspect:
            print("\n=== SELF-MODEL INTROSPECTION ===")
            print("\n[What can I do?]")
            for cap in engine.self_model.what_can_i_do():
                print(f"  - {cap['name']} ({cap['category']}): reliability {cap['reliability']*100:.1f}%, latency {cap['avg_latency_ms']}ms")
            print("\n[What can I not do / active limitations?]")
            for lim in engine.self_model.what_can_i_not_do():
                print(f"  - {lim.get('title', lim.get('name'))}: {lim.get('description', '')}")

        elif args.scoreboard:
            print(engine.scoreboard.render_summary_text())

        else:
            n = max(1, args.cycles)
            print(f"[ASCENDANT ∞] Executing {n} autonomous developmental flywheel cycle(s)...")
            for i in range(n):
                trace = await engine.run_developmental_cycle()
                print(f"[{trace.cycle_id}] Strat={trace.strategy_selected:28} Mode={trace.cognitive_allocation_mode:12} Maturity={trace.maturity_level:20} Dur={trace.duration_ms:.1f}ms")
            print("\n" + engine.scoreboard.render_summary_text())

    finally:
        await engine.stop()


def main():
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
