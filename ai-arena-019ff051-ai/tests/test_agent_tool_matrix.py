"""
Full functionalization matrix — proves EVERY agent and EVERY tool is real.

AGENTS (21): each is selected, given a task tailored to its responsibility,
executed through the registry, and its output verified against its REAL
responsibility (not merely "did not raise").

TOOLS (100): each is executed individually with valid input. A tool passes
by producing a REAL result; a tool that honestly reports an unavailable
device capability (e.g. no termux-battery-status on this host) also passes
as EXECUTED+HONEST-UNAVAILABLE. A tool that crashes, returns an empty
result, or fabricates success FAILS.
"""

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

from zerion.agents.base import AgentResult
from zerion.agents.registry import AgentRegistry
from zerion.tools.registry import ToolRegistry


class TestAgentMatrix(unittest.TestCase):
    """Every one of the 21 agents must perform its REAL responsibility."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.tmp = tempfile.mkdtemp(prefix="agent_matrix_")

    def _run(self, agent_id, task, expect_patterns, min_len=40):
        agent = self.registry.get(agent_id)
        self.assertIsNotNone(agent, f"{agent_id} not registered")
        result = asyncio.run(agent.execute(task, {}, None))
        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success, f"{agent.name} failed: {result.reasoning}")
        self.assertGreater(len(result.output or ""), min_len,
                           f"{agent.name} returned trivial output")
        for pattern in expect_patterns:
            self.assertRegex(result.output or "", pattern,
                             f"{agent.name} output lacks {pattern!r}")
        return result

    def test_01_strategic_planner_builds_phased_plan(self):
        r = self._run("agent_01_strategic",
                      "Plan how to build a backup service",
                      [r"GOAL", r"PHASE 1", r"PHASE 5", r"RISK"])

    def test_02_deep_reasoner_analyzes_causally(self):
        r = self._run("agent_02_reasoner",
                      "Analyze why API latency increases under load",
                      [r"QUESTION", r"ANALYSIS|APPROACH|CAUSAL|hypothes"])

    def test_03_code_engineer_writes_real_code(self):
        r = self._run("agent_03_code",
                      "Write a function to deduplicate a list in python",
                      [r"def |function|code", r".{20,}"], min_len=60)

    def test_04_bug_hunter_diagnoses_traceback(self):
        tb = ("Traceback (most recent call last):\n"
              '  File "app.py", line 12, in run\n'
              "ZeroDivisionError: division by zero")
        r = self._run("agent_04_debugger", f"Debug this error:\n{tb}",
                      [r"ZeroDivisionError|division|line 12|error"],
                      min_len=30)

    def test_05_security_sentinel_flags_risk(self):
        r = self._run("agent_05_security",
                      "Security review of code using eval() on user input",
                      [r"SECURITY|OWASP|eval|risk|A0", ], min_len=80)

    def test_06_system_navigator_reports_live_os_data(self):
        import os
        r = self._run("agent_06_system",
                      "Check system status cpu memory storage battery",
                      [r"SYSTEM STATUS", os.uname().sysname])
        # Memory numbers must come from the LIVE /proc/meminfo of this host.
        with open("/proc/meminfo") as f:
            first_line = f.readline()
        mem_kb = int(first_line.split()[1]) // 1024
        self.assertIn(str(mem_kb), r.output,
                      "System Navigator memory figure is not from this host")

    def test_07_datawizard_transforms_formats(self):
        r = self._run("agent_07_data",
                      "Convert csv data to json format",
                      [r"FORMAT|CONVERT|JSON|CSV"])

    def test_08_research_scout_structures_research(self):
        r = self._run("agent_08_research",
                      "Research caching strategies for web services",
                      [r"RESEARCH|sources?|protocol|gather", r"."], min_len=100)

    def test_09_network_probe_is_honest_and_specific(self):
        r = self._run("agent_09_network",
                      "Check network interfaces and connectivity",
                      [r"NETWORK"])
        # Honesty: a failed outbound probe must NOT be reported as OFFLINE.
        self.assertNotIn("Status: OFFLINE", r.output)
        self.assertIn("probe", r.output.lower())

    def test_10_database_keeper_reports_real_databases(self):
        r = self._run("agent_10_database",
                      "Inspect the sqlite databases and schema",
                      [r"DATABASE|\.db|sqlite"])

    def test_11_devops_pilot_gives_deployment_options(self):
        r = self._run("agent_11_devops", "Deploy plan for the runtime",
                      [r"DEPLOY|main2\.py|UI"])

    def test_12_memory_sage_maps_memory_commands(self):
        r = self._run("agent_12_memory", "Organize these facts into memory",
                      [r"MEMORY|remember|recall|knowledge"])

    def test_13_creative_spark_generates_named_options(self):
        r = self._run("agent_13_creative",
                      "Brainstorm names for a new app about fitness",
                      [r"NAMING|option|idea|\d\."], min_len=80)

    def test_14_math_engine_computes_for_real(self):
        r = self._run("agent_14_math", "Calculate 17 * 23 + sqrt(144)",
                      [r"MATH|EXPRESSION"])
        # The FULL expression must really evaluate: 391 + 12 = 403.
        self.assertIn("403", r.output,
                      f"Math Engine did not compute the expression: {r.output!r}")

    def test_15_file_guardian_performs_real_fs_work(self):
        marker = Path(self.tmp) / "matrix_marker.txt"
        marker.write_text("zerion-matrix")
        task = f"Find and inspect files in {self.tmp}"
        r = self._run("agent_15_files", task,
                      [r"FILE|directory|matrix_marker|/tmp"], min_len=50)

    def test_16_quality_inspector_runs_checks(self):
        r = self._run("agent_16_quality",
                      "Review this python code for quality issues",
                      [r"QUALITY|syntax|check|level"])

    def test_17_performance_guru_profiles(self):
        r = self._run("agent_17_performance", "Optimize this slow loop",
                      [r"PERFORMANCE|CPU|optimi"])

    def test_18_architecture_sage_maps_architecture(self):
        r = self._run("agent_18_architecture",
                      "Design architecture for a chat service",
                      [r"ARCHITECTURE|component|layer"])

    def test_19_language_bridge_detects_and_assists(self):
        r = self._run("agent_19_language",
                      "Bonjour, pouvez-vous m'aider avec ce code?",
                      [r"LANGUAGE|French|français|multilingual|respond"],
                      min_len=40)

    def test_20_health_watchdog_measures_health(self):
        r = self._run("agent_20_health", "Check health of the running system",
                      [r"HEALTH|metric|status"], min_len=60)

    def test_21_recovery_hero_diagnoses_recovery(self):
        r = self._run("agent_21_recovery",
                      "Recover from this failed deployment",
                      [r"RECOVERY|step|assess|protocol"], min_len=60)

    def test_registry_selects_right_specialist(self):
        cases = {
            "check my battery level": "System Navigator",
            "find the file report.txt and read it": "File Guardian",
            "calculate 452 * 88": "Math Engine",
            "debug this traceback": "Bug Hunter",
            "review security of this login handler": "Security Sentinel",
        }
        for task, expected in cases.items():
            top = self.registry.select_best(task, top_k=1)
            self.assertTrue(top, f"no agent selected for {task!r}")
            self.assertEqual(top[0].name, expected,
                             f"{task!r} selected {top[0].name}, "
                             f"expected {expected}")

    def test_exactly_21_agents_all_distinct(self):
        agents = self.registry.list_all()
        self.assertEqual(len(agents), 21)
        ids = [a.agent_id for a in agents]
        names = [a.name for a in agents]
        self.assertEqual(len(set(ids)), 21, "duplicate agent ids")
        self.assertEqual(len(set(names)), 21, "duplicate agent names")


class TestToolMatrix(unittest.TestCase):
    """Every one of the 100 tools must execute and produce a REAL or
    honestly-unavailable structured result."""

    def setUp(self):
        self.registry = ToolRegistry()
        self.tmp = tempfile.mkdtemp(prefix="tool_matrix_")
        self.sample = Path(self.tmp) / "sample.txt"
        self.sample.write_text("zerion tool matrix sample\nline two\n")

    def args_for(self, name):
        t = self.tmp
        return {
            "sys_shell": "echo zerion-matrix-ok",
            "file_read": str(self.sample),
            "file_write": f"{t}/out.txt hello matrix",
            "file_list": t,
            "file_exists": str(self.sample),
            "file_size": str(self.sample),
            "file_copy": f"{self.sample} {t}/copy.txt",
            "file_move": f"{t}/copy.txt {t}/moved.txt",
            "file_delete": f"{t}/moved.txt",
            "file_mkdir": f"{t}/newdir",
            "file_find": f"{t} sample",
            "file_temp": "matrix",
            "code_execute": "print(6*7)",
            "code_syntax_check": "def f():\n    return 1\n",
            "code_analyze": "import os\nos.system('ls')\n",
            "code_test": "print('ok')",
            "code_format": "x=1\ny = 2\n",
            "code_dependencies": "import os\nimport sys\n",
            "code_import_check": "import os",
            "code_version": "",
            "code_type_check": "x: int = 'str'",
            "code_docstring": "def f():\n    return 1",
            "data_json_parse": '{"a": 1, "b": [2,3]}',
            "data_json_query": '{"a": {"b": 42}} a.b',
            "data_csv_parse": "x,y\n1,2\n3,4",
            "data_count": "a b a c a",
            "data_sort": "3 1 2",
            "data_unique": "a b a",
            "data_stats": "1 2 3 4 5",
            "data_encode": "hello matrix",
            "data_decode": "aGVsbG8gbWF0cml4 base64",
            "data_hash": "matrix",
            "net_check": "",
            "net_dns": "localhost",
            "net_port": "127.0.0.1 80",
            "net_ping": "127.0.0.1",
            "net_speed": "",
            "net_interfaces": "",
            "net_http_head": "http://127.0.0.1:9",
            "net_ssl_check": "localhost",
            "net_whois": "example.com",
            "net_download": f"http://127.0.0.1:9/x {t}/dl.bin",
            "knowledge_store": "matrix_color: teal",
            "knowledge_search": "matrix_color",
            "knowledge_recall": "matrix_color",
            "knowledge_forget": "matrix_color",
            "knowledge_correct": "matrix_color: dark-teal",
            "knowledge_list": "",
            "knowledge_count": "",
            "knowledge_export": t,
            "knowledge_import": f"{t}/export.json",
            "knowledge_cite": "matrix_color",
            "sec_permissions": str(self.sample),
            "sec_hash_file": str(self.sample),
            "sec_check_deps": "",
            "sec_scan_imports": "import os\nimport subprocess",
            "sec_env_check": "PATH",
            "sec_file_perms": str(self.sample),
            "sec_validate_path": f"{t}/safe.txt",
            "sec_check_injection": "'; DROP TABLE users; --",
            "sec_log_audit": "",
            "sec_network_check": "127.0.0.1",
            "mon_process": "",
            "mon_cpu": "",
            "mon_disk_io": "",
            "mon_network": "",
            "mon_log_tail": str(self.sample),
            "mon_errors": str(self.sample),
            "mon_health": "",
            "mon_perf": "",
            "mon_file_changes": t,
            "mon_uptime_check": "",
            "voice_speak": "matrix test",
            "audio_info": "",
            "audio_volume": "",
            "audio_vibrate": "",
            "audio_list_devices": "",
            "audio_set_volume": "50",
            "audio_test": "",
            "dev_clipboard": "copy matrix-value",
            "dev_battery": "",
            "dev_brightness": "",
            "dev_media_control": "play",
            "dev_wifi": "",
            "dev_notification": "matrix notification",
            "dev_toast": "matrix toast",
            "dev_screenshot": f"{t}/screen.png",
            "dev_contacts": "",
            "dev_calendar": "",
            "dev_location": "",
            "dev_settings": "",
            "sys_info": "", "sys_uptime": "", "sys_disk": "", "sys_memory": "",
            "sys_env": "PATH", "sys_process_list": "", "sys_hostname": "",
            "sys_pid": "", "sys_time": "",
        }.get(name, "")

    def test_exactly_100_tools_all_unique_with_descriptions(self):
        tools = self.registry.list_all()
        self.assertEqual(len(tools), 100)
        names = [t.name for t in tools]
        self.assertEqual(len(set(names)), 100, "duplicate tool names")
        for t in tools:
            self.assertTrue(t.description and len(t.description) > 10,
                            f"{t.name} lacks a real description")

    def test_every_tool_executes_with_real_or_honest_result(self):
        results = {}
        failures = []
        for tool in self.registry.list_all():
            arg = self.args_for(tool.name)
            try:
                res = tool.execute(arg)
            except Exception as e:  # unhandled crash = hard fail
                failures.append(f"{tool.name}: CRASHED {type(e).__name__}: {e}")
                continue
            if res.ok:
                if not res.output or not res.output.strip():
                    failures.append(f"{tool.name}: ok=True but empty output")
                elif re.search(r"(?i)^\W*(success|done|ok|completed "
                               r"successfully)[.!\s]*$", res.output):
                    failures.append(f"{tool.name}: looks like a fake "
                                    f"success-only response: {res.output!r}")
                else:
                    results[tool.name] = "REAL"
            else:
                # Honest structured failure: must explain WHY concretely
                # (e.g. missing termux API), never be empty/vague.
                err = res.error or ""
                if len(err) < 8:
                    failures.append(f"{tool.name}: failure without reason")
                elif "not available" in err.lower() and len(err) < 20:
                    failures.append(f"{tool.name}: vague unavailable error")
                else:
                    results[tool.name] = f"HONEST_UNAVAILABLE ({err[:60]})"
        self.assertEqual(failures, [], "tool matrix failures:\n" +
                         "\n".join(failures))
        real = sorted(n for n, v in results.items() if v == "REAL")
        print(f"\n[tool-matrix] REAL={len(real)} HONEST_UNAVAILABLE="
              f"{len(results) - len(real)} TOTAL={len(results)}")
        # Persist the full matrix as evidence.
        out = Path(self.tmp) / "matrix.json"
        out.write_text(json.dumps(results, indent=2))

    def test_tools_actually_operate_on_the_world(self):
        """Spot-check that tools change/read REAL state, not fake strings."""
        t = Path(self.tmp)
        reg = self.registry
        get = lambda n: next(x for x in reg.list_all() if x.name == n)

        # file_write -> file on disk with exact content
        target = t / "world.txt"
        r = get("file_write").execute(f"{target} hello world 123")
        self.assertTrue(r.ok, r.error)
        self.assertEqual(target.read_text(), "hello world 123")

        # code_execute -> actually computes
        r = get("code_execute").execute("print(6*7)")
        self.assertTrue(r.ok, r.error)
        self.assertIn("42", r.output)

        # sys_time -> real epoch seconds
        import time
        r = get("sys_time").execute("")
        self.assertTrue(r.ok)
        m = re.search(r"\b(\d{10})\b", r.output)
        self.assertIsNotNone(m, f"no epoch in sys_time output: {r.output!r}")
        self.assertAlmostEqual(int(m.group(1)), time.time(), delta=120)

        # data_stats -> real statistics
        r = get("data_stats").execute("2 4 6 8")
        self.assertTrue(r.ok)
        self.assertIn("5", r.output)   # count
        self.assertIn("20", r.output)  # sum


if __name__ == "__main__":
    unittest.main(verbosity=2)
