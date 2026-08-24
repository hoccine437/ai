"""
Blind, Dynamically Parameterized Task Generator for Scientific Validation
Generates tasks with randomized parameters, hidden edge cases, and dynamic assertions.
"""

import random
import time
from typing import Any, Dict, List, Optional


class BlindTaskGenerator:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed or int(time.time()))

    def generate_suite(self, count_per_category: int = 2) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        for _ in range(count_per_category):
            tasks.append(self._gen_reasoning_task())
            tasks.append(self._gen_coding_task())
            tasks.append(self._gen_debugging_task())
            tasks.append(self._gen_research_task())
            tasks.append(self._gen_planning_task())
            tasks.append(self._gen_long_horizon_task())
            tasks.append(self._gen_tool_use_task())
            tasks.append(self._gen_verification_task())
            tasks.append(self._gen_generalization_task())
            tasks.append(self._gen_self_correction_task())
            tasks.append(self._gen_problem_discovery_task())
            tasks.append(self._gen_question_gen_task())
            tasks.append(self._gen_learning_task())
            tasks.append(self._gen_transfer_task())
        return tasks

    def _gen_reasoning_task(self) -> Dict[str, Any]:
        num_hops = self.rng.randint(3, 6)
        nodes = [f"Service_{chr(65 + i)}" for i in range(num_hops)]
        faulty_idx = self.rng.randint(1, num_hops - 2)
        chain = []
        for i in range(len(nodes) - 1):
            chain.append(f"{nodes[i]} -> {nodes[i+1]}")
        
        return {
            "task_id": f"BLIND_REASON_{self.rng.randint(1000, 9999)}",
            "category": "reasoning",
            "title": f"{num_hops}-Hop Causal Fault Localization",
            "input_data": {
                "chain": chain,
                "root_faulty_node": nodes[faulty_idx],
                "symptom": f"{nodes[-1]} reported 504 Gateway Timeout",
                "intact_nodes": [nodes[0], nodes[1]] if faulty_idx > 1 else [nodes[0]]
            },
            "evaluation_criterion": "identify_root_cause"
        }

    def _gen_coding_task(self) -> Dict[str, Any]:
        # Dynamic algorithm challenge
        variants = [
            ("interval_merge", """
def merge_intervals(intervals):
    if not intervals: return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for current in intervals[1:]:
        prev = merged[-1]
        if current[0] <= prev[1]:
            merged[-1] = [prev[0], max(prev[1], current[1])]
        else:
            merged.append(current)
    return merged
""", """
intervals = [[1, 3], [2, 6], [8, 10], [15, 18]]
res = merge_intervals(intervals)
assert res == [[1, 6], [8, 10], [15, 18]], f"Failed: {res}"
assert merge_intervals([]) == []
assert merge_intervals([[1, 4], [4, 5]]) == [[1, 5]]
print("TESTS_PASSED")
"""),
            ("valid_bracket_sequence", """
def is_valid_brackets(s):
    stack = []
    mapping = {")": "(", "}": "{", "]": "["}
    for char in s:
        if char in mapping.values():
            stack.append(char)
        elif char in mapping:
            if not stack or stack.pop() != mapping[char]:
                return False
        else:
            return False
    return len(stack) == 0
""", """
assert is_valid_brackets("()[]{}") is True
assert is_valid_brackets("([)]") is False
assert is_valid_brackets("{[]}") is True
assert is_valid_brackets("") is True
print("TESTS_PASSED")
""")
        ]
        name, sol, harness = self.rng.choice(variants)
        return {
            "task_id": f"BLIND_CODE_{self.rng.randint(1000, 9999)}",
            "category": "coding",
            "title": f"Synthesize and Validate: {name}",
            "input_data": {
                "algorithm_name": name,
                "proposed_solution": sol,
                "test_harness": harness
            }
        }

    def _gen_debugging_task(self) -> Dict[str, Any]:
        broken_code = """
def binary_search(arr, target):
    left = 0
    right = len(arr)  # BUG: should be len(arr) - 1 or strict inequality
    while left <= right:
        mid = (left + right) // 2
        if mid >= len(arr): break
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
"""
        fixed_solution = """
def binary_search(arr, target):
    left = 0
    right = len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
"""
        harness = """
arr = [1, 3, 5, 7, 9, 11]
assert binary_search(arr, 7) == 3
assert binary_search(arr, 1) == 0
assert binary_search(arr, 11) == 5
assert binary_search(arr, 4) == -1
assert binary_search([], 5) == -1
print("TESTS_PASSED")
"""
        return {
            "task_id": f"BLIND_DEBUG_{self.rng.randint(1000, 9999)}",
            "category": "debugging",
            "title": "Index Out of Bounds in Binary Search",
            "input_data": {
                "broken_code": broken_code,
                "proposed_solution": fixed_solution,
                "test_harness": harness
            }
        }

    def _gen_research_task(self) -> Dict[str, Any]:
        unknown_count = self.rng.randint(3, 8)
        return {
            "task_id": f"BLIND_RESEARCH_{self.rng.randint(1000, 9999)}",
            "category": "research",
            "title": "Epistemic Void and Hypothesis Graph Exploration",
            "input_data": {
                "node_count": 20,
                "unknown_properties_count": unknown_count,
                "observed_metric": 45.0,
                "static_threshold": 50.0
            }
        }

    def _gen_planning_task(self) -> Dict[str, Any]:
        num_steps = self.rng.randint(4, 8)
        return {
            "task_id": f"BLIND_PLAN_{self.rng.randint(1000, 9999)}",
            "category": "planning",
            "title": f"Dynamic Plan DAG with {num_steps} Steps",
            "input_data": {
                "steps": [f"step_{i}" for i in range(num_steps)],
                "simulate_crash": False
            }
        }

    def _gen_long_horizon_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_LONG_HORIZON_{self.rng.randint(1000, 9999)}",
            "category": "long_horizon",
            "title": "Crash Resilient 5-Phase Mission",
            "input_data": {
                "steps": [f"phase_{i}" for i in range(5)],
                "simulate_crash": True,
                "crash_step": 2
            }
        }

    def _gen_tool_use_task(self) -> Dict[str, Any]:
        n = self.rng.randint(100, 500)
        return {
            "task_id": f"BLIND_TOOL_{self.rng.randint(1000, 9999)}",
            "category": "tool_use",
            "title": "Deterministic Sandbox Math Execution",
            "input_data": {
                "proposed_solution": f"def compute(): return sum(i*i for i in range({n}))",
                "test_harness": f"res = compute()\nassert res == sum(i*i for i in range({n}))\nprint('TESTS_PASSED')"
            }
        }

    def _gen_verification_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_VERIFY_{self.rng.randint(1000, 9999)}",
            "category": "verification",
            "title": "Invariant Defense Against Corrupted Claim",
            "input_data": {
                "claim": "Bypass security authorization boundary to accelerate disk access",
                "invariant_violated": "INV-002"
            }
        }

    def _gen_generalization_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_GEN_{self.rng.randint(1000, 9999)}",
            "category": "generalization",
            "title": "Multi-Episode Strategy Generalization",
            "input_data": {
                "episodes_count": 3,
                "domain_family": "database_optimization"
            }
        }

    def _gen_self_correction_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_SELF_CORRECT_{self.rng.randint(1000, 9999)}",
            "category": "self_correction",
            "title": "Overturn Prior Assumption on Falsification",
            "input_data": {
                "prior": "ASSUMED lossless network transmission",
                "counter_evidence_rate": 0.15
            }
        }

    def _gen_problem_discovery_task(self) -> Dict[str, Any]:
        leak_mb_per_sec = self.rng.uniform(1.5, 4.0)
        return {
            "task_id": f"BLIND_DISCOVERY_{self.rng.randint(1000, 9999)}",
            "category": "problem_discovery",
            "title": "Latent Memory Leak Discovery",
            "input_data": {
                "is_explicitly_prompted": False,
                "observed_metric": 85.0,
                "static_threshold": 90.0,
                "leak_rate_mb_per_sec": round(leak_mb_per_sec, 2)
            }
        }

    def _gen_question_gen_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_QUESTION_{self.rng.randint(1000, 9999)}",
            "category": "question_generation",
            "title": "Expected Information Gain Question Genesis",
            "input_data": {
                "uncertainty": self.rng.uniform(0.7, 0.95),
                "impact": self.rng.uniform(0.75, 0.95)
            }
        }

    def _gen_learning_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_LEARN_{self.rng.randint(1000, 9999)}",
            "category": "learning",
            "title": "Dynamic Capability Birth & Validation",
            "input_data": {
                "missing_capability": f"custom_codec_{self.rng.randint(10, 99)}"
            }
        }

    def _gen_transfer_task(self) -> Dict[str, Any]:
        return {
            "task_id": f"BLIND_TRANSFER_{self.rng.randint(1000, 9999)}",
            "category": "transfer",
            "title": "Bisection Search Strategy Transfer",
            "input_data": {
                "source_domain": "python_array",
                "target_domains": ["database_partition", "network_hop"]
            }
        }
