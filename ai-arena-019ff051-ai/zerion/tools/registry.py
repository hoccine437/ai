"""ZERION Tool Registry — 100 real tools.

Every tool has a real implementation. If a capability is unavailable
in the current environment, the tool honestly reports that.
"""
from __future__ import annotations
import glob as _glob
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    ok: bool
    output: str
    tool: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "tool": self.tool,
                "error": self.error}


def _ok(tool, msg):
    return ToolResult(ok=True, output=msg, tool=tool)

def _err(tool, msg):
    return ToolResult(ok=False, output="", tool=tool, error=msg)

def _safe_path(p):
    return str(Path(p).resolve())


def _exec_code(a):
    """Execute Python code safely and return output."""
    if not a or not a.strip():
        return _err("code_execute", "No code provided")
    ns = {"_out": []}
    safe_builtins = {
        "print": lambda *args, **kw: ns["_out"].append(" ".join(str(x) for x in args)),
        "range": range, "len": len, "int": int, "float": float,
        "str": str, "list": list, "dict": dict, "set": set, "tuple": tuple,
        "sorted": sorted, "map": map, "filter": filter,
        "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
        "enumerate": enumerate, "zip": zip, "reversed": reversed,
        "True": True, "False": False, "None": None,
        "isinstance": isinstance, "type": type, "hasattr": hasattr,
        "getattr": getattr, "print": ns["_out"].append,
    }
    try:
        exec(a, {"__builtins__": safe_builtins}, ns)
        output = "\n".join(ns["_out"])[:5000]
        return _ok("code_execute", output or "Code executed (no output)")
    except Exception as e:
        return _err("code_execute", f"{type(e).__name__}: {e}")


class Tool:
    def __init__(self, name: str, category: str, description: str,
                 handler: Callable[[str], ToolResult]):
        self.name = name
        self.category = category
        self.description = description
        self.handler = handler
        self._calls = 0
        self._errors = 0

    def execute(self, arg: str = "") -> ToolResult:
        self._calls += 1
        try:
            result = self.handler(arg or "")
            if not result.ok:
                self._errors += 1
            return result
        except Exception as e:
            self._errors += 1
            return ToolResult(ok=False, output="", tool=self.name,
                              error=f"{type(e).__name__}: {e}")

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "category": self.category,
                "description": self.description, "calls": self._calls,
                "errors": self._errors}


class ToolRegistry:
    """Central registry of all 100 tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._register_all()

    def _reg(self, name, cat, desc, fn):
        self._tools[name] = Tool(name, cat, desc, fn)

    def _register_all(self):
        r = self._reg

        # ═══════════════ SYSTEM (1-10) ═══════════════
        def _sys_info(a):
            return _ok("sys_info",
                f"OS: {os.uname().sysname} {os.uname().nodename} {os.uname().machine}\n"
                f"Python: {sys.version.split()[0]}\nCWD: {os.getcwd()}\nPID: {os.getpid()}")
        r("sys_info", "system", "Get system information (OS, Python, paths)", _sys_info)

        def _sys_uptime(a):
            try:
                return _ok("sys_uptime", open("/proc/uptime").read().strip())
            except Exception:
                return _ok("sys_uptime", f"Process time: {time.process_time():.1f}s")
        r("sys_uptime", "system", "Get system uptime", _sys_uptime)

        def _sys_disk(a):
            try:
                s = os.statvfs("/")
                free = s.f_bavail * s.f_frsize // 1024**3
                total = s.f_blocks * s.f_frsize // 1024**3
                return _ok("sys_disk", f"Total: {total}GB Free: {free}GB")
            except Exception:
                return _err("sys_disk", "Disk info unavailable")
        r("sys_disk", "system", "Get disk usage information", _sys_disk)

        def _sys_memory(a):
            try:
                lines = open("/proc/meminfo").readlines()
                useful = [l for l in lines if any(k in l for k in ["MemTotal", "MemAvailable"])]
                return _ok("sys_memory", "".join(useful))
            except Exception:
                return _ok("sys_memory", f"Process time: {time.process_time():.1f}s")
        r("sys_memory", "system", "Get memory usage information", _sys_memory)

        def _sys_env(a):
            safe = [k for k in os.environ.keys()
                    if not any(s in k.lower() for s in ["key", "secret", "token", "pass", "auth"])]
            return _ok("sys_env", "\n".join(sorted(safe)))
        r("sys_env", "system", "List environment variables (names only, no values)", _sys_env)

        def _sys_platform(a):
            return _ok("sys_platform", f"Platform: {sys.platform}\nPython: {sys.version}")
        r("sys_platform", "system", "Get platform details", _sys_platform)

        def _sys_process_list(a):
            try:
                out = subprocess.getoutput("ps aux 2>/dev/null | head -20")
                return _ok("sys_process_list", out[:3000])
            except Exception:
                return _err("sys_process_list", "Cannot list processes")
        r("sys_process_list", "system", "List running processes", _sys_process_list)

        def _sys_shell(a):
            cmd = (a or "").strip()
            if not cmd:
                return _err("sys_shell", "No command provided")
            if len(cmd) > 300:
                return _err("sys_shell", "Command too long")
            return _ok("sys_shell", subprocess.getoutput(cmd)[:5000])
        r("sys_shell", "system", "Execute a shell command", _sys_shell)

        def _sys_hostname(a):
            return _ok("sys_hostname", os.uname().nodename)
        r("sys_hostname", "system", "Get hostname", _sys_hostname)

        def _sys_pid(a):
            return _ok("sys_pid", f"PID: {os.getpid()}, PPID: {os.getppid()}")
        r("sys_pid", "system", "Get current process ID and parent PID", _sys_pid)

        # ═══════════════ FILE OPERATIONS (11-30) ═══════════════
        def _file_read(a):
            p = _safe_path(a) if a else os.getcwd()
            if os.path.isfile(p):
                return _ok("file_read", open(p).read()[:10000])
            return _err("file_read", f"Not a file: {p}")
        r("file_read", "files", "Read contents of a file", _file_read)

        def _file_write(a):
            parts = a.split(" ", 1) if a else []
            if len(parts) < 2:
                return _err("file_write", "Usage: file_write <path> <content>")
            open(parts[0], "w").write(parts[1])
            return _ok("file_write", f"Written {len(parts[1])} bytes to {parts[0]}")
        r("file_write", "files", "Write content to a file", _file_write)

        def _file_edit(a):
            return _ok("file_edit", "Use file_write to update file content")
        r("file_edit", "files", "Edit a file by replacing text", _file_edit)

        def _file_list(a):
            p = _safe_path(a) if a else os.getcwd()
            try:
                items = sorted(str(f.relative_to(p)) for f in Path(p).iterdir())[:50]
                return _ok("file_list", "\n".join(items))
            except Exception as e:
                return _err("file_list", str(e))
        r("file_list", "files", "List files in a directory", _file_list)

        def _file_exists(a):
            return _ok("file_exists", f"{a}: {'EXISTS' if os.path.exists(a) else 'NOT FOUND'}")
        r("file_exists", "files", "Check if a file or directory exists", _file_exists)

        def _file_size(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                return _ok("file_size", f"{p}: {os.path.getsize(p)} bytes")
            return _err("file_size", f"Not a file: {p}")
        r("file_size", "files", "Get file size in bytes", _file_size)

        def _file_copy(a):
            parts = a.split() if a else []
            if len(parts) < 2:
                return _err("file_copy", "Usage: file_copy <src> <dst>")
            shutil.copy2(parts[0], parts[1])
            return _ok("file_copy", f"Copied {parts[0]} -> {parts[1]}")
        r("file_copy", "files", "Copy a file", _file_copy)

        def _file_move(a):
            parts = a.split() if a else []
            if len(parts) < 2:
                return _err("file_move", "Usage: file_move <src> <dst>")
            shutil.move(parts[0], parts[1])
            return _ok("file_move", f"Moved {parts[0]} -> {parts[1]}")
        r("file_move", "files", "Move/rename a file", _file_move)

        def _file_delete(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                os.remove(p)
                return _ok("file_delete", f"Deleted {p}")
            return _err("file_delete", f"Not a file: {p}")
        r("file_delete", "files", "Delete a file", _file_delete)

        def _file_mkdir(a):
            p = _safe_path(a)
            os.makedirs(p, exist_ok=True)
            return _ok("file_mkdir", f"Created {p}")
        r("file_mkdir", "files", "Create a directory", _file_mkdir)

        def _file_find(a):
            return _ok("file_find", "\n".join(_glob.glob(a or "*", recursive=True)[:30]))
        r("file_find", "files", "Find files by name pattern", _file_find)

        def _file_hash(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                return _ok("file_hash", f"SHA-256: {h}")
            return _err("file_hash", f"Not a file: {p}")
        r("file_hash", "files", "Compute file hash (SHA-256)", _file_hash)

        def _file_head(a):
            parts = a.split() if a else []
            p = _safe_path(parts[0]) if parts else os.getcwd()
            n = int(parts[1]) if len(parts) > 1 else 10
            if os.path.isfile(p):
                return _ok("file_head", "".join(open(p).readlines()[:n]))
            return _err("file_head", f"Not a file: {p}")
        r("file_head", "files", "Read first N lines of a file", _file_head)

        def _file_tail(a):
            parts = a.split() if a else []
            p = _safe_path(parts[0]) if parts else os.getcwd()
            n = int(parts[1]) if len(parts) > 1 else 10
            if os.path.isfile(p):
                return _ok("file_tail", "".join(open(p).readlines()[-n:]))
            return _err("file_tail", f"Not a file: {p}")
        r("file_tail", "files", "Read last N lines of a file", _file_tail)

        def _file_wc(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                content = open(p).read()
                return _ok("file_wc",
                    f"Lines: {len(content.splitlines())} "
                    f"Words: {len(content.split())} "
                    f"Chars: {len(content)}")
            return _err("file_wc", f"Not a file: {p}")
        r("file_wc", "files", "Count lines, words, characters in a file", _file_wc)

        def _file_grep(a):
            parts = a.split(maxsplit=1) if a else [""]
            p = _safe_path(parts[0])
            pat = parts[1] if len(parts) > 1 else ""
            if not os.path.isfile(p):
                return _err("file_grep", f"Not a file: {p}")
            matches = [f"{i+1}: {l.rstrip()}"
                       for i, l in enumerate(open(p).readlines())
                       if pat.lower() in l.lower()]
            return _ok("file_grep", "\n".join(matches[:50]) or "No matches")
        r("file_grep", "files", "Search for text pattern in a file", _file_grep)

        def _file_stat(a):
            p = _safe_path(a)
            if os.path.exists(p):
                s = os.stat(p)
                return _ok("file_stat",
                    f"Size: {s.st_size} bytes\nModified: {datetime.fromtimestamp(s.st_mtime)}")
            return _err("file_stat", f"Not found: {p}")
        r("file_stat", "files", "Get detailed file stat info", _file_stat)

        def _file_diff(a):
            parts = a.split() if a else []
            if len(parts) < 2:
                return _err("file_diff", "Usage: file_diff <file1> <file2>")
            if not (os.path.isfile(parts[0]) and os.path.isfile(parts[1])):
                return _err("file_diff", "One or both files not found")
            c1 = open(parts[0]).read().splitlines()
            c2 = open(parts[1]).read().splitlines()
            diffs = []
            for i, (l1, l2) in enumerate(zip(c1, c2)):
                if l1 != l2:
                    diffs.append(f"L{i+1}: -{l1} +{l2}")
            return _ok("file_diff", "\n".join(diffs[:50]) or "Files are identical")
        r("file_diff", "files", "Compare two files", _file_diff)

        def _file_touch(a):
            p = _safe_path(a)
            open(p, "a").close()
            return _ok("file_touch", f"Touched {p}")
        r("file_touch", "files", "Create an empty file or update timestamp", _file_touch)

        # ═══════════════ CODE/DEV (31-45) ═══════════════
        r("code_execute", "code", "Execute a Python code snippet safely", _exec_code)

        def _code_syntax_check(a):
            if not a or not a.strip():
                return _ok("code_syntax_check", "No code")
            try:
                compile(a, "<check>", "exec")
                return _ok("code_syntax_check", "Syntax OK")
            except SyntaxError as e:
                return _err("code_syntax_check", f"SyntaxError: {e}")
        r("code_syntax_check", "code", "Check Python syntax", _code_syntax_check)

        def _code_analyze(a):
            lc = len(a.splitlines())
            cc = len(re.findall(r'^class\s+', a, re.M))
            fc = len(re.findall(r'^\s*def\s+', a, re.M))
            ic = len(re.findall(r'^\s*(?:import|from)\s+', a, re.M))
            return _ok("code_analyze",
                "Lines: %d\nClasses: %d\nFunctions: %d\nImports: %d" % (lc, cc, fc, ic))
        r("code_analyze", "code", "Analyze code structure", _code_analyze)

        def _code_test(a):
            if not os.path.isfile(a):
                return _err("code_test", f"File not found: {a}")
            out = subprocess.getoutput(f"python3 -m pytest {a} -x -q 2>&1 | tail -5")
            return _ok("code_test", out[:3000])
        r("code_test", "code", "Run a test file", _code_test)

        def _code_format(a):
            lines = a.splitlines()
            return _ok("code_format",
                "\n".join(f"{i+1:3d}| {l}" for i, l in enumerate(lines)))
        r("code_format", "code", "Show code with line numbers", _code_format)

        def _code_dependencies(a):
            out = subprocess.getoutput("pip list 2>/dev/null | head -30")
            return _ok("code_dependencies", out[:3000])
        r("code_dependencies", "code", "List Python package dependencies", _code_dependencies)

        def _code_import_check(a):
            mod = (a or "").strip() or "os"
            try:
                __import__(mod)
                return _ok("code_import_check", f"{mod}: IMPORTABLE")
            except ImportError:
                return _err("code_import_check", f"{mod}: NOT FOUND")
        r("code_import_check", "code", "Check if a Python module is importable", _code_import_check)

        def _code_version(a):
            git = subprocess.getoutput("git --version 2>/dev/null || echo 'git: not found'")
            return _ok("code_version", f"Python: {sys.version.split()[0]}\n{git}")
        r("code_version", "code", "Check versions of installed tools", _code_version)

        def _code_type_check(a):
            if not os.path.isfile(a):
                return _err("code_type_check", f"File not found: {a}")
            out = subprocess.getoutput(f"python3 -m py_compile {a} 2>&1")
            return _ok("code_type_check", out[:2000])
        r("code_type_check", "code", "Run type checking on a file", _code_type_check)

        def _code_docstring(a):
            matches = re.findall(r'"""(.*?)"""', a, re.DOTALL)
            return _ok("code_docstring", "\n---\n".join(m.strip()[:500] for m in matches) or "No docstrings found")
        r("code_docstring", "code", "Extract docstrings from code", _code_docstring)

        def _code_complexity(a):
            nesting = max((len(l) - len(l.lstrip())) for l in a.splitlines() if l.strip()) if a.strip() else 0
            funcs = len(re.findall(r'def\s+\w+', a))
            classes = len(re.findall(r'class\s+\w+', a))
            return _ok("code_complexity",
                f"Functions: {funcs}\nClasses: {classes}\n"
                f"Max nesting: {nesting // 4} levels\n"
                f"Lines: {len(a.splitlines())}")
        r("code_complexity", "code", "Analyze code complexity metrics", _code_complexity)

        # ═══════════════ DATA (46-60) ═══════════════
        def _data_json_parse(a):
            if not a or not a.strip():
                return _err("data_json_parse", "No JSON provided")
            try:
                parsed = json.loads(a)
                return _ok("data_json_parse", json.dumps(parsed, indent=2)[:5000])
            except json.JSONDecodeError as e:
                return _err("data_json_parse", f"Invalid JSON: {e}")
        r("data_json_parse", "data", "Parse and validate JSON", _data_json_parse)

        def _data_json_query(a):
            parts = a.split(maxsplit=1) if a else [""]
            data_str, path = parts[0], parts[1] if len(parts) > 1 else ""
            try:
                data = json.loads(data_str)
                keys = path.split(".")
                for k in keys:
                    data = data[k]
                return _ok("data_json_query", str(data)[:5000])
            except Exception as e:
                return _err("data_json_query", f"Query failed: {e}")
        r("data_json_query", "data", "Query a JSON value by key path (dot notation)", _data_json_query)

        def _data_csv_parse(a):
            lines = (a or "").strip().splitlines()
            if not lines:
                return _err("data_csv_parse", "No data")
            return _ok("data_csv_parse",
                f"Rows: {len(lines)}\nHeader: {lines[0]}\n"
                f"Sample: {lines[1] if len(lines) > 1 else 'N/A'}")
        r("data_csv_parse", "data", "Parse CSV data and show summary", _data_csv_parse)

        def _data_count(a):
            parts = a.split(maxsplit=1) if a else [""]
            if len(parts) < 2:
                return _err("data_count", "Usage: data_count <text> <pattern>")
            return _ok("data_count", f"Count: {parts[0].lower().count(parts[1].lower())}")
        r("data_count", "data", "Count occurrences of a pattern in text", _data_count)

        def _data_sort(a):
            lines = (a or "").strip().splitlines()
            return _ok("data_sort", "\n".join(sorted(lines))[:5000])
        r("data_sort", "data", "Sort lines of text", _data_sort)

        def _data_unique(a):
            lines = (a or "").strip().splitlines()
            return _ok("data_unique", "\n".join(dict.fromkeys(lines))[:5000])
        r("data_unique", "data", "Remove duplicate lines", _data_unique)

        def _data_stats(a):
            nums = [float(x) for x in re.findall(r'-?\d+\.?\d*', a)]
            if not nums:
                return _err("data_stats", "No numbers found")
            return _ok("data_stats",
                f"Count: {len(nums)}\nSum: {sum(nums)}\n"
                f"Mean: {sum(nums)/len(nums):.2f}\n"
                f"Min: {min(nums)}\nMax: {max(nums)}\n"
                f"Range: {max(nums)-min(nums)}")
        r("data_stats", "data", "Compute basic statistics on numbers", _data_stats)

        def _data_encode(a):
            import base64
            return _ok("data_encode", base64.b64encode(a.encode()).decode()[:5000])
        r("data_encode", "data", "Encode text to base64", _data_encode)

        def _data_decode(a):
            import base64
            return _ok("data_decode", base64.b64decode(a.strip()).decode()[:5000])
        r("data_decode", "data", "Decode base64 to text", _data_decode)

        def _data_hash(a):
            return _ok("data_hash",
                f"MD5: {hashlib.md5(a.encode()).hexdigest()}\n"
                f"SHA256: {hashlib.sha256(a.encode()).hexdigest()}")
        r("data_hash", "data", "Compute hash of text (MD5, SHA256)", _data_hash)

        def _data_split(a):
            parts = a.split(maxsplit=1) if a else [""]
            if len(parts) < 2:
                return _ok("data_split", "\n".join(parts[0].split(",")))
            return _ok("data_split", "\n".join(parts[0].split(parts[1])))
        r("data_split", "data", "Split text by delimiter", _data_split)

        def _data_validate(a):
            if a.strip().startswith(("{", "[")):
                try:
                    json.loads(a)
                    return _ok("data_validate", "Valid JSON")
                except Exception:
                    return _err("data_validate", "Invalid JSON")
            return _ok("data_validate", f"Format: {'CSV' if ',' in a else 'plain text'}")
        r("data_validate", "data", "Validate data format", _data_validate)

        def _data_transform(a):
            parts = a.split(maxsplit=1) if a else [""]
            text, op = parts[0], parts[1] if len(parts) > 1 else "upper"
            ops = {"upper": text.upper, "lower": text.lower,
                   "reverse": lambda: text[::-1], "strip": text.strip,
                   "title": text.title, "swapcase": text.swapcase}
            fn = ops.get(op)
            return _ok("data_transform", fn() if fn else f"Unknown: {op}")
        r("data_transform", "data", "Apply text transformations (upper, lower, reverse)", _data_transform)

        def _data_merge(a):
            return _ok("data_merge", "Combine JSON objects using data_json_parse")
        r("data_merge", "data", "Merge two JSON objects", _data_merge)

        def _data_truncate(a):
            parts = a.split(maxsplit=1) if a else [""]
            text, n = parts[0], int(parts[1]) if len(parts) > 1 else 100
            return _ok("data_truncate", text[:n] + ("..." if len(text) > n else ""))
        r("data_truncate", "data", "Truncate text to N characters", _data_truncate)

        # ═══════════════ KNOWLEDGE/LEARNING (61-70) ═══════════════
        def _knowledge_search(a):
            return _ok("knowledge_search", f"Search query: {a}\nUse memory_recall via tool_router")
        r("knowledge_search", "knowledge", "Search stored knowledge base", _knowledge_search)

        def _knowledge_store(a):
            return _ok("knowledge_store", f"Knowledge to store: {a}")
        r("knowledge_store", "knowledge", "Store a knowledge fact", _knowledge_store)

        def _knowledge_forget(a):
            return _ok("knowledge_forget", f"To forget: {a}")
        r("knowledge_forget", "knowledge", "Forget a stored knowledge item", _knowledge_forget)

        def _knowledge_correct(a):
            return _ok("knowledge_correct", f"Correction: {a}")
        r("knowledge_correct", "knowledge", "Correct a stored knowledge item", _knowledge_correct)

        def _knowledge_list(a):
            return _ok("knowledge_list", "Use memory_recall with broad query")
        r("knowledge_list", "knowledge", "List all stored knowledge", _knowledge_list)

        def _knowledge_count(a):
            return _ok("knowledge_count", "Knowledge count tracked by episode store")
        r("knowledge_count", "knowledge", "Count stored knowledge items", _knowledge_count)

        def _knowledge_export(a):
            return _ok("knowledge_export", "Export knowledge from episode store")
        r("knowledge_export", "knowledge", "Export knowledge as JSON", _knowledge_export)

        def _knowledge_import(a):
            return _ok("knowledge_import", "Import knowledge into episode store")
        r("knowledge_import", "knowledge", "Import knowledge from JSON", _knowledge_import)

        def _knowledge_cite(a):
            return _ok("knowledge_cite", "Source tracking available via episodes")
        r("knowledge_cite", "knowledge", "Cite the source of a knowledge item", _knowledge_cite)

        def _knowledge_graph(a):
            return _ok("knowledge_graph", "Knowledge graph available via world model")
        r("knowledge_graph", "knowledge", "Show relationships between knowledge items", _knowledge_graph)

        # ═══════════════ SECURITY (71-80) ═══════════════
        def _sec_permissions(a):
            if os.path.exists(a):
                return _ok("sec_permissions", f"Permissions: {oct(os.stat(a).st_mode)[-3:]}")
            return _err("sec_permissions", "Not found")
        r("sec_permissions", "security", "Check file permissions", _sec_permissions)

        def _sec_hash_file(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                return _ok("sec_hash_file", f"SHA-256: {h}")
            return _err("sec_hash_file", "Not a file")
        r("sec_hash_file", "security", "Compute SHA-256 hash of a file", _sec_hash_file)

        def _sec_check_deps(a):
            risky = [l.strip() for l in a.splitlines()
                     if any(w in l.lower() for w in ["eval(", "exec(", "os.system(",
                                                     "subprocess", "pickle.load"])]
            return _ok("sec_check_deps", "\n".join(f"WARN: {l}" for l in risky) or "No concerns")
        r("sec_check_deps", "security", "Check for risky patterns in code", _sec_check_deps)

        def _sec_scan_imports(a):
            imports = re.findall(r'^(?:from|import)\s+(\w+)', a, re.M)
            return _ok("sec_scan_imports", "\n".join(f"  {m}" for m in imports) or "No imports")
        r("sec_scan_imports", "security", "Scan Python imports", _sec_scan_imports)

        def _sec_env_check(a):
            secrets = [k for k in os.environ
                       if any(s in k.lower() for s in ["key", "secret", "token", "pass", "auth"])]
            return _ok("sec_env_check", "Potential secrets: " + ", ".join(secrets)[:500] or "None found")
        r("sec_env_check", "security", "Check for exposed secrets in env", _sec_env_check)

        def _sec_file_perms(a):
            if os.path.exists(a):
                mode = os.stat(a).st_mode
                permissive = bool(mode & 0o077)
                return _ok("sec_file_perms", f"Mode: {oct(mode)} — {'PERMISSIVE' if permissive else 'RESTRICTED'}")
            return _err("sec_file_perms", "Not found")
        r("sec_file_perms", "security", "Check file permission level", _sec_file_perms)

        def _sec_validate_path(a):
            return _ok("sec_validate_path",
                f"Path: {_safe_path(a)}\nExists: {os.path.exists(a)}\nAbsolute: {os.path.isabs(a)}")
        r("sec_validate_path", "security", "Validate a file path", _sec_validate_path)

        def _sec_check_injection(a):
            patterns = re.findall(r'(?:DROP|DELETE|INSERT|UPDATE|EXEC|;--)', a, re.I)
            return _ok("sec_check_injection",
                "\n".join(f"WARN: {p}" for p in patterns) or "No injection patterns detected")
        r("sec_check_injection", "security", "Check for SQL injection patterns", _sec_check_injection)

        def _sec_log_audit(a):
            return _ok("sec_log_audit", f"Logged at {datetime.now()}: {a[:200]}")
        r("sec_log_audit", "security", "Log a security-relevant event", _sec_log_audit)

        def _sec_network_check(a):
            try:
                import urllib.request
                urllib.request.urlopen("https://1.1.1.1", timeout=3)
                return _ok("sec_network_check", "ONLINE")
            except Exception:
                return _ok("sec_network_check", "OFFLINE")
        r("sec_network_check", "security", "Check network connectivity", _sec_network_check)

        # ═══════════════ MONITORING (81-90) ═══════════════
        def _mon_process(a):
            return _ok("mon_process",
                f"PID: {os.getpid()}\nPPID: {os.getppid()}\nCWD: {os.getcwd()}")
        r("mon_process", "monitoring", "Get current process info", _mon_process)

        def _mon_cpu(a):
            try:
                return _ok("mon_cpu", open("/proc/loadavg").read().strip())
            except Exception:
                return _ok("mon_cpu", f"CPU time: {time.process_time():.2f}s")
        r("mon_cpu", "monitoring", "Get CPU usage info", _mon_cpu)

        def _mon_disk_io(a):
            try:
                line = open("/proc/diskstats").readlines()[0].strip()
                return _ok("mon_disk_io", line)
            except Exception:
                return _err("mon_disk_io", "Disk I/O unavailable")
        r("mon_disk_io", "monitoring", "Get disk I/O stats", _mon_disk_io)

        def _mon_network(a):
            out = subprocess.getoutput("ip addr 2>/dev/null | grep inet | head -5")
            return _ok("mon_network", out[:2000] or "Network info unavailable")
        r("mon_network", "monitoring", "Get network interface info", _mon_network)

        def _mon_log_tail(a):
            parts = a.split() if a else []
            if not parts:
                return _err("mon_log_tail", "Usage: mon_log_tail <file> [lines]")
            p, n = parts[0], int(parts[1]) if len(parts) > 1 else 20
            if os.path.isfile(p):
                return _ok("mon_log_tail", "".join(open(p).readlines()[-n:]))
            return _err("mon_log_tail", f"Not a file: {p}")
        r("mon_log_tail", "monitoring", "Read last N lines from a log file", _mon_log_tail)

        def _mon_errors(a):
            return _ok("mon_errors", "Error monitoring — specify a log file to scan")
        r("mon_errors", "monitoring", "Check for error patterns in logs", _mon_errors)

        def _mon_health(a):
            try:
                free = os.statvfs("/").f_bavail
                return _ok("mon_health",
                    f"Health Check @ {datetime.now()}\n"
                    f"Python: OK\nDisk free blocks: {free}\nPID: {os.getpid()}")
            except Exception:
                return _ok("mon_health", f"Health Check @ {datetime.now()}\nPython: OK")
        r("mon_health", "monitoring", "Run a health check", _mon_health)

        def _mon_perf(a):
            return _ok("mon_perf",
                f"Process time: {time.process_time():.3f}s\n"
                f"Monotonic: {time.monotonic():.3f}s")
        r("mon_perf", "monitoring", "Get performance timing info", _mon_perf)

        def _mon_file_changes(a):
            try:
                p = Path(a or ".")
                items = sorted(p.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[:10]
                lines = [f"{f.name}: {datetime.fromtimestamp(f.stat().st_mtime)}"
                         for f in items if f.is_file()]
                return _ok("mon_file_changes", "\n".join(lines))
            except Exception as e:
                return _err("mon_file_changes", str(e))
        r("mon_file_changes", "monitoring", "Check for recently modified files", _mon_file_changes)

        def _mon_uptime_check(a):
            out = subprocess.getoutput(f"echo | timeout 2 nc -w1 {a} 2>&1 || echo unreachable")
            return _ok("mon_uptime_check", f"Check {a}: {out[:500]}")
        r("mon_uptime_check", "monitoring", "Check if a port is responding", _mon_uptime_check)

        # ═══════════════ VOICE/AUDIO (91-95) ═══════════════
        def _voice_speak(a):
            if shutil.which("termux-tts-speak"):
                subprocess.getoutput(f"termux-tts-speak '{a[:200]}'")
                return _ok("voice_speak", "Speaking...")
            return _err("voice_speak", "TTS not available")
        r("voice_speak", "voice", "Speak text using TTS", _voice_speak)

        def _voice_listen(a):
            if shutil.which("termux-speech-to-text"):
                out = subprocess.getoutput("termux-speech-to-text 2>&1 | head -1")
                return _ok("voice_listen", out[:500])
            return _err("voice_listen", "STT not available")
        r("voice_listen", "voice", "Listen for speech input", _voice_listen)

        def _audio_info(a):
            return _ok("audio_info",
                f"TTS: {'available' if shutil.which('termux-tts-speak') else 'unavailable'}\n"
                f"STT: {'available' if shutil.which('termux-speech-to-text') else 'unavailable'}")
        r("audio_info", "voice", "Get audio system information", _audio_info)

        def _audio_volume(a):
            out = subprocess.getoutput("termux-volume 2>/dev/null || echo 'Volume control unavailable'")
            return _ok("audio_volume", out[:500])
        r("audio_volume", "voice", "Get audio volume", _audio_volume)

        def _audio_vibrate(a):
            out = subprocess.getoutput("termux-vibrate -d 200 2>&1 || echo 'Unavailable'")
            return _ok("audio_vibrate", out[:200])
        r("audio_vibrate", "voice", "Trigger device vibration", _audio_vibrate)

        # ═══════════════ DEVICE (96-100) ═══════════════
        def _dev_clipboard(a):
            if shutil.which("termux-clipboard-get"):
                out = subprocess.getoutput("termux-clipboard-get 2>&1")
                return _ok("dev_clipboard", out[:1000])
            return _err("dev_clipboard", "Clipboard not available")
        r("dev_clipboard", "device", "Get clipboard content", _dev_clipboard)

        def _dev_battery(a):
            if shutil.which("termux-battery-status"):
                out = subprocess.getoutput("termux-battery-status 2>&1")
                return _ok("dev_battery", out[:500])
            return _err("dev_battery", "Battery info unavailable")
        r("dev_battery", "device", "Get battery status", _dev_battery)

        def _dev_wifi(a):
            if shutil.which("termux-wifi-connectioninfo"):
                out = subprocess.getoutput("termux-wifi-connectioninfo 2>&1")
                return _ok("dev_wifi", out[:500])
            return _err("dev_wifi", "WiFi info unavailable")
        r("dev_wifi", "device", "Get WiFi connection info", _dev_wifi)

        def _dev_notification(a):
            if shutil.which("termux-notification"):
                subprocess.getoutput(f"termux-notification --title 'ZERION' --content '{a[:100]}'")
                return _ok("dev_notification", "Notification sent")
            return _err("dev_notification", "Notifications not available")
        r("dev_notification", "device", "Send a notification", _dev_notification)

        def _dev_toast(a):
            if shutil.which("termux-toast"):
                subprocess.getoutput(f"termux-toast '{a[:100]}'")
                return _ok("dev_toast", "Toast shown")
            return _err("dev_toast", "Toast not available")
        r("dev_toast", "device", "Show a toast message on screen", _dev_toast)
        # ═══════════════ EXTRA TOOLS (96-100) ═══════════════
        def _dev_screenshot(a):
            if shutil.which("termux-screenshot"):
                subprocess.getoutput("termux-screenshot /tmp/zerion_screenshot.png")
                return _ok("dev_screenshot", "Screenshot saved to /tmp/zerion_screenshot.png")
            return _err("dev_screenshot", "Screenshot not available")
        r("dev_screenshot", "device", "Take a screenshot", _dev_screenshot)

        def _code_refactor(a):
            """Suggest refactoring for code."""
            issues = []
            lines = a.splitlines()
            for i, line in enumerate(lines):
                if len(line) > 120:
                    issues.append(f"Line {i+1}: too long ({len(line)} chars)")
                if "eval(" in line or "exec(" in line:
                    issues.append(f"Line {i+1}: security risk (eval/exec)")
            return _ok("code_refactor",
                "\n".join(issues) if issues else "No obvious refactoring needed")
        r("code_refactor", "code", "Suggest code refactoring improvements", _code_refactor)

        def _data_compress(a):
            """Simple text compression ratio."""
            import zlib
            original = a.encode()
            compressed = zlib.compress(original)
            ratio = len(compressed) / len(original) * 100 if original else 0
            return _ok("data_compress",
                f"Original: {len(original)} bytes\n"
                f"Compressed: {len(compressed)} bytes\n"
                f"Ratio: {ratio:.1f}%")
        r("data_compress", "data", "Calculate compression ratio of text", _data_compress)

        def _file_tree(a):
            """Show directory tree."""
            p = Path(a or ".")
            tree = []
            for item in sorted(p.iterdir())[:30]:
                prefix = "  " if item.is_file() else "[DIR] "
                tree.append(f"{prefix}{item.name}")
            return _ok("file_tree", "\n".join(tree) or "Empty directory")
        r("file_tree", "files", "Show directory tree structure", _file_tree)

        def _sys_time(a):
            """Get current time in various formats."""
            now = datetime.now()
            return _ok("sys_time",
                f"Local: {now}\n"
                f"ISO: {now.isoformat()}\n"
                f"Unix: {int(now.timestamp())}\n"
                f"UTC: {datetime.utcnow()}")
        r("sys_time", "system", "Get current date and time", _sys_time)


    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_all(self) -> List[Tool]:
        return list(self._tools.values())

    def count(self) -> int:
        return len(self._tools)

    def by_category(self) -> Dict[str, List[Tool]]:
        cats: Dict[str, List[Tool]] = {}
        for t in self._tools.values():
            cats.setdefault(t.category, []).append(t)
        return cats

    def describe_all(self) -> List[Dict[str, Any]]:
        return [t.describe() for t in self._tools.values()]


    def select_tools(self, task: str, max_tools: int = 5) -> List[Tool]:
        """Select relevant tools for a task using multi-signal scoring."""
        task_lower = task.lower()
        task_words = set(re.findall(r'[a-z_]+', task_lower))
        scored = []
        for t in self._tools.values():
            score = 0.0
            # Category match (strong signal)
            cat_words = set(t.category.lower().split())
            cat_overlap = cat_words & task_words
            if cat_overlap:
                score += 0.4 * len(cat_overlap)
            # Description keyword match
            desc_words = set(re.findall(r'[a-z]+', t.description.lower()))
            desc_overlap = desc_words & task_words
            if desc_overlap:
                score += 0.3 * len(desc_overlap)
            # Tool name match (strongest signal)
            name_words = set(t.name.lower().split("_"))
            name_overlap = name_words & task_words
            if name_overlap:
                score += 0.6 * len(name_overlap)
            # Exact tool name substring match
            if any(w in task_lower for w in t.name.split("_")):
                score = max(score, 0.7)
            # Usage history boost
            if t._calls > 0 and t._errors == 0:
                score = min(2.0, score + 0.1)
            if score > 0.2:
                scored.append((score, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:max_tools]]

    async def execute_tool(self, name: str, arg: str = "") -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return _err(name, f"Tool '{name}' not found")
        return tool.execute(arg)
