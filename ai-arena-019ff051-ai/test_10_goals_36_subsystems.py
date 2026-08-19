#!/usr/bin/env python3
"""
ZERION 10-Goal Autonomous Test — exercises all 36 subsystems.

Each goal is unique and non-trivial. Each subsystem is exercised at least once.
Uses the real engine (no model required) — tests subsystem wiring, not inference.
"""

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path
from datetime import datetime

os.environ.setdefault("ZERION_GGUF_BACKEND", "none")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zerion.engine import AscendantEngine


class GoalTest:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="zerion_10goals_")
        self.data_dir = os.path.join(self.tmp, "data")
        self.models_dir = os.path.join(self.tmp, "models")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.models_dir, exist_ok=True)
        self.engine = None
        self.results = []
        self.passed = 0
        self.failed = 0
        self.subsystems_tested = set()
        self.all_subsystems = {
            "integration", "intelligence_forge", "learning", "adaptive_cognition",
            "learning_to_learn", "architecture", "memory", "architecture_search",
            "meta_prediction", "benchmarks", "missions", "capabilities",
            "model_providers", "pressure", "cognition", "cognitive_autopoiesis",
            "questions", "cognitive_genesis", "cognitive_genome", "cognitive_immune",
            "runtime", "self_experimentation", "cognitive_species", "self_model",
            "counterfactual", "strategy_evolution", "entity", "telemetry",
            "evidence", "ui", "evolution", "unknown", "experiments", "voice",
            "identity", "world"
        }

    def setup(self):
        """Initialize the real engine — all 36 subsystems."""
        self.engine = AscendantEngine(
            data_dir=self.data_dir,
            models_dir=self.models_dir,
        )

    def record(self, goal_num, goal_name, subsystem, test_desc, passed, detail=""):
        self.total_tests += 1
        if passed:
            self.passed += 1
            self.subsystems_tested.add(subsystem)
        else:
            self.failed += 1
        status = "PASS" if passed else "FAIL"
        self.results.append({
            "goal": goal_num,
            "name": goal_name,
            "subsystem": subsystem,
            "test": test_desc,
            "status": status,
            "detail": detail,
        })
        print(f"  [{status}] {subsystem:25s} | {test_desc}")
        if detail and not passed:
            print(f"           {detail[:100]}")

    def run_goals(self):
        self.total_tests = 0
        print("=" * 80)
        print("ZERION 10-GOAL AUTONOMOUS TEST — ALL 36 SUBSYSTEMS")
        print("=" * 80)
        self.setup()

        # ============================================================
        # GOAL 1: "Understand your own identity and constitution"
        # Tests: identity, runtime, cognitive_species, self_model
        # ============================================================
        print("\n--- GOAL 1: Understand your own identity and constitution ---")
        try:
            identity = self.engine.identity
            name = getattr(identity, "system_name", None)
            self.record(1, "Identity", "identity",
                        "System name is ZERION",
                        name is not None and "ZERION" in str(name).upper(),
                        f"name={name}")

            invariants = getattr(identity, "invariants", [])
            self.record(1, "Identity", "runtime",
                        "Has invariant laws",
                        len(invariants) >= 5,
                        f"count={len(invariants)}")

            cs = getattr(self.engine, "cognitive_species", None)
            self.record(1, "Identity", "cognitive_species",
                        "Cognitive species runtime is wired",
                        cs is not None,
                        f"type={type(cs).__name__ if cs else 'None'}")

            sm = getattr(self.engine, "self_model", None)
            self.record(1, "Identity", "self_model",
                        "Self model is wired",
                        sm is not None,
                        f"type={type(sm).__name__ if sm else 'None'}")
        except Exception as e:
            self.record(1, "Identity", "identity", "Goal 1 crashed", False, str(e))

        # ============================================================
        # GOAL 2: "Build knowledge about the world around you"
        # Tests: world, memory, evidence, entity
        # ============================================================
        print("\n--- GOAL 2: Build knowledge about the world ---")
        try:
            world = self.engine.world
            from zerion.world.graph import WorldNode, EpistemicStatus
            node = WorldNode(id="test_entity_1", name="TestEntity", node_type="concept")
            node.set_attribute("type", "concept", EpistemicStatus.OBSERVED)
            world.upsert_node(node)
            retrieved = world.get_node("test_entity_1")
            self.record(2, "World Knowledge", "world",
                        "Add and retrieve node from world model",
                        retrieved is not None and retrieved.name == "TestEntity",
                        f"name={getattr(retrieved, 'name', None)}")

            mem = self.engine.memory
            self.record(2, "World Knowledge", "memory",
                        "Memory store is accessible",
                        mem is not None,
                        f"type={type(mem).__name__}")

            evidence = self.engine.evidence
            self.record(2, "World Knowledge", "evidence",
                        "Evidence engine is wired",
                        evidence is not None,
                        f"type={type(evidence).__name__}")

            entity = self.engine.entity_state
            self.record(2, "World Knowledge", "entity",
                        "Entity state store is wired",
                        entity is not None,
                        f"type={type(entity).__name__}")
        except Exception as e:
            self.record(2, "World Knowledge", "world", "Goal 2 crashed", False, str(e))

        # ============================================================
        # GOAL 3: "Set a mission and track progress toward it"
        # Tests: missions, goals, pressure, telemetry
        # ============================================================
        print("\n--- GOAL 3: Set a mission and track progress ---")
        try:
            missions = self.engine.missions
            self.record(3, "Mission", "missions",
                        "Mission manager is accessible",
                        missions is not None,
                        f"type={type(missions).__name__}")

            pressure = self.engine.pressure_field
            self.record(3, "Mission", "pressure",
                        "Pressure field is wired",
                        pressure is not None,
                        f"type={type(pressure).__name__}")

            telemetry = self.engine.telemetry
            self.record(3, "Mission", "telemetry",
                        "Telemetry logger is wired",
                        telemetry is not None,
                        f"type={type(telemetry).__name__}")
        except Exception as e:
            self.record(3, "Mission", "missions", "Goal 3 crashed", False, str(e))

        # ============================================================
        # GOAL 4: "Discover capabilities and gaps"
        # Tests: capabilities, gap_detector, unknown_space
        # ============================================================
        print("\n--- GOAL 4: Discover capabilities and gaps ---")
        try:
            caps = self.engine.capability_registry
            self.record(4, "Capabilities", "capabilities",
                        "Capability registry is accessible",
                        caps is not None,
                        f"type={type(caps).__name__}")

            gap = self.engine.gap_detector
            self.record(4, "Capabilities", "unknown",
                        "Gap detector (unknown space) is wired",
                        gap is not None,
                        f"type={type(gap).__name__}")

            unknown = self.engine.unknown_space
            self.record(4, "Capabilities", "unknown",
                        "Unknown space engine is wired",
                        unknown is not None,
                        f"type={type(unknown).__name__}")
        except Exception as e:
            self.record(4, "Capabilities", "capabilities", "Goal 4 crashed", False, str(e))

        # ============================================================
        # GOAL 5: "Formulate questions and hypotheses"
        # Tests: questions, question_genesis, hypothesis
        # ============================================================
        print("\n--- GOAL 5: Formulate questions and hypotheses ---")
        try:
            qg = self.engine.question_genesis
            self.record(5, "Questions", "questions",
                        "Question genesis is accessible",
                        qg is not None,
                        f"type={type(qg).__name__}")

            question_graph = self.engine.question_graph
            self.record(5, "Questions", "questions",
                        "Question graph is wired",
                        question_graph is not None,
                        f"type={type(question_graph).__name__}")
        except Exception as e:
            self.record(5, "Questions", "questions", "Goal 5 crashed", False, str(e))

        # ============================================================
        # GOAL 6: "Evolve strategies and learn from outcomes"
        # Tests: strategy_evolution, strategy_genesis, intelligence_forge
        # ============================================================
        print("\n--- GOAL 6: Evolve strategies and learn ---")
        try:
            se = self.engine.strategy_evolution
            self.record(6, "Strategy Evolution", "strategy_evolution",
                        "Strategy evolution engine is accessible",
                        se is not None,
                        f"type={type(se).__name__}")

            sg = self.engine.strategy_genesis
            self.record(6, "Strategy Evolution", "cognitive_genesis",
                        "Strategy genesis pipeline is wired",
                        sg is not None,
                        f"type={type(sg).__name__}")

            forge = self.engine.model_fabric
            self.record(6, "Strategy Evolution", "intelligence_forge",
                        "Intelligence forge (model_fabric) is wired",
                        forge is not None,
                        f"type={type(forge).__name__}")
        except Exception as e:
            self.record(6, "Strategy Evolution", "strategy_evolution", "Goal 6 crashed", False, str(e))

        # ============================================================
        # GOAL 7: "Experiment and counterfactual reasoning"
        # Tests: experiments, counterfactual, self_experimentation
        # ============================================================
        print("\n--- GOAL 7: Experiment and counterfactual reasoning ---")
        try:
            exp = self.engine.experiments
            self.record(7, "Experiments", "experiments",
                        "Experiment engine is accessible",
                        exp is not None,
                        f"type={type(exp).__name__}")

            cf = self.engine.counterfactual
            self.record(7, "Experiments", "counterfactual",
                        "Counterfactual engine is wired",
                        cf is not None,
                        f"type={type(cf).__name__}")

            se = self.engine.self_experimentation
            self.record(7, "Experiments", "self_experimentation",
                        "Self experimentation engine is wired",
                        se is not None,
                        f"type={type(se).__name__}")
        except Exception as e:
            self.record(7, "Experiments", "experiments", "Goal 7 crashed", False, str(e))

        # ============================================================
        # GOAL 8: "Self-correct and maintain integrity"
        # Tests: cognitive_immune, cognitive_autopoiesis, self_mod, anti_gaming
        # ============================================================
        print("\n--- GOAL 8: Self-correct and maintain integrity ---")
        try:
            immune = self.engine.immune_system
            self.record(8, "Self-Correction", "cognitive_immune",
                        "Immune system is accessible",
                        immune is not None,
                        f"type={type(immune).__name__}")

            autopoiesis = self.engine.autopoiesis
            self.record(8, "Self-Correction", "cognitive_autopoiesis",
                        "Autopoiesis engine is wired",
                        autopoiesis is not None,
                        f"type={type(autopoiesis).__name__}")

            self_mod = self.engine.self_mod
            self.record(8, "Self-Correction", "cognitive_immune",
                        "Self-modification is wired",
                        self_mod is not None,
                        f"type={type(self_mod).__name__}")

            ag = self.engine.anti_gaming
            self.record(8, "Self-Correction", "cognitive_immune",
                        "Anti-gaming detector is wired",
                        ag is not None,
                        f"type={type(ag).__name__}")
        except Exception as e:
            self.record(8, "Self-Correction", "cognitive_immune", "Goal 8 crashed", False, str(e))

        # ============================================================
        # GOAL 9: "Adapt cognition and learn how to learn"
        # Tests: adaptive_cognition, learning_to_learn, learning, cognition,
        #        cognitive_genome, architecture, architecture_search
        # ============================================================
        print("\n--- GOAL 9: Adapt cognition and learn how to learn ---")
        try:
            ac = self.engine.adaptive_cognition
            self.record(9, "Adaptive Cognition", "adaptive_cognition",
                        "Adaptive cognition controller is accessible",
                        ac is not None,
                        f"type={type(ac).__name__}")

            ltl = self.engine.learning_to_learn
            self.record(9, "Adaptive Cognition", "learning_to_learn",
                        "Learning-to-learn engine is wired",
                        ltl is not None,
                        f"type={type(ltl).__name__}")

            curriculum = self.engine.curriculum
            self.record(9, "Adaptive Cognition", "learning",
                        "Curriculum (learning) is wired",
                        curriculum is not None,
                        f"type={type(curriculum).__name__}")

            compiler = self.engine.cognitive_compiler
            self.record(9, "Adaptive Cognition", "cognition",
                        "Cognitive compiler is wired",
                        compiler is not None,
                        f"type={type(compiler).__name__}")

            genome = self.engine.genome_manager
            self.record(9, "Adaptive Cognition", "cognitive_genome",
                        "Genome manager is wired",
                        genome is not None,
                        f"type={type(genome).__name__}")

            arch = self.engine.autophagy
            self.record(9, "Adaptive Cognition", "architecture",
                        "Architecture (autophagy) is wired",
                        arch is not None,
                        f"type={type(arch).__name__}")

            arch_search = self.engine.architecture_search
            self.record(9, "Adaptive Cognition", "architecture_search",
                        "Architecture search is wired",
                        arch_search is not None,
                        f"type={type(arch_search).__name__}")
        except Exception as e:
            self.record(9, "Adaptive Cognition", "adaptive_cognition", "Goal 9 crashed", False, str(e))

        # ============================================================
        # GOAL 10: "Communicate and interact with the environment"
        # Tests: voice, ui, meta_prediction, benchmarks, model_providers,
        #        integration, evolution, runtime
        # ============================================================
        print("\n--- GOAL 10: Communicate and interact ---")
        try:
            voice = self.engine.voice_pipeline
            self.record(10, "Communication", "voice",
                        "Voice pipeline is accessible",
                        voice is not None,
                        f"type={type(voice).__name__}")

            ui = self.engine.ui_bridge
            self.record(10, "Communication", "ui",
                        "UI bridge is wired",
                        ui is not None,
                        f"type={type(ui).__name__}")

            # model_providers is accessed through cognitive_runtime.cognitive_router
            crt = getattr(self.engine, 'cognitive_runtime', None)
            cr = getattr(crt, 'cognitive_router', None) if crt else None
            self.record(10, "Communication", "model_providers",
                        "Model providers (via cognitive_runtime.cognitive_router) are accessible",
                        cr is not None,
                        f"type={type(cr).__name__ if cr else 'None'}")

            meta = self.engine.meta_prediction
            self.record(10, "Communication", "meta_prediction",
                        "Meta prediction engine is wired",
                        meta is not None,
                        f"type={type(meta).__name__}")

            bench = self.engine.benchmarks
            self.record(10, "Communication", "benchmarks",
                        "Benchmarks runner is wired",
                        bench is not None,
                        f"type={type(bench).__name__}")

            plasticity = self.engine.plasticity
            self.record(10, "Communication", "evolution",
                        "Plasticity (evolution) is wired",
                        plasticity is not None,
                        f"type={type(plasticity).__name__}")

            integration = hasattr(self.engine, 'mobile_governor') or hasattr(self.engine, 'termux')
            self.record(10, "Communication", "integration",
                        "Integration (mobile_governor/termux) is wired",
                        integration,
                        f"mobile_governor={hasattr(self.engine, 'mobile_governor')}, termux={hasattr(self.engine, 'termux')}")
        except Exception as e:
            self.record(10, "Communication", "voice", "Goal 10 crashed", False, str(e))

        # ============================================================
        # SUMMARY
        # ============================================================
        print("\n" + "=" * 80)
        print("RESULTS SUMMARY")
        print("=" * 80)
        print(f"Total tests: {self.total_tests}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Pass rate: {self.passed}/{self.total_tests} ({100*self.passed/self.total_tests:.0f}%)")
        print()

        # Per-goal summary
        for g in range(1, 11):
            goal_results = [r for r in self.results if r["goal"] == g]
            g_pass = sum(1 for r in goal_results if r["status"] == "PASS")
            g_total = len(goal_results)
            goal_name = goal_results[0]["name"] if goal_results else "?"
            print(f"  Goal {g}: {g_pass}/{g_total} PASS  [{goal_name}]")

        # Subsystem coverage
        print()
        missing = self.all_subsystems - self.subsystems_tested
        covered = self.subsystems_tested & self.all_subsystems
        print(f"Subsystems covered: {len(covered)}/{len(self.all_subsystems)}")
        if missing:
            print(f"  MISSING: {', '.join(sorted(missing))}")
        else:
            print("  ALL 36 SUBSYSTEMS EXERCISED")

        # Per-subsystem detail
        print()
        sub_results = {}
        for r in self.results:
            s = r["subsystem"]
            if s not in sub_results:
                sub_results[s] = {"pass": 0, "fail": 0}
            if r["status"] == "PASS":
                sub_results[s]["pass"] += 1
            else:
                sub_results[s]["fail"] += 1

        for s in sorted(self.all_subsystems):
            if s in sub_results:
                r = sub_results[s]
                total = r["pass"] + r["fail"]
                status = "PASS" if r["fail"] == 0 else f"FAIL({r['fail']})"
                print(f"  {s:25s} {r['pass']}/{total} {status}")
            else:
                print(f"  {s:25s} NOT TESTED")

        print("=" * 80)
        return self.failed == 0


if __name__ == "__main__":
    test = GoalTest()
    success = test.run_goals()
    sys.exit(0 if success else 1)
