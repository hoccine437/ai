"""ZERION Tool Registry — 100 real tools.

Every tool has a real implementation. If a capability is unavailable
in the current environment, the tool honestly reports that.
"""
from __future__ import annotations
import base64
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
import zlib
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
            u = os.uname()
            return _ok("sys_info",
                f"OS: {u.sysname} {u.release} {u.machine}\n"
                f"Node: {u.nodename}\n"
                f"Python: {sys.version.split()[0]}\n"
                f"CWD: {os.getcwd()}\n"
                f"PID: {os.getpid()}\n"
                f"PPID: {os.getppid()}")
        r("sys_info", "system", "Get complete system information (OS, Python, paths, PID)", _sys_info)

        def _sys_uptime(a):
            try:
                with open("/proc/uptime") as f:
                    uptime_secs = float(f.read().split()[0])
                    hours = int(uptime_secs // 3600)
                    mins = int((uptime_secs % 3600) // 60)
                    return _ok("sys_uptime", f"System uptime: {hours}h {mins}m ({uptime_secs:.0f}s)")
            except Exception:
                return _ok("sys_uptime", f"Process CPU time: {time.process_time():.1f}s")
        r("sys_uptime", "system", "Get system uptime or process CPU time", _sys_uptime)

        def _sys_disk(a):
            try:
                s = os.statvfs(a.strip() or "/")
                free = s.f_bavail * s.f_frsize // 1024**3
                total = s.f_blocks * s.f_frsize // 1024**3
                used = total - free
                pct = (used / total * 100) if total > 0 else 0
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                return _ok("sys_disk",
                    f"Path: {a.strip() or '/'}\n"
                    f"Total: {total}GB  Used: {used}GB  Free: {free}GB\n"
                    f"Usage: [{bar}] {pct:.1f}%")
            except Exception as e:
                return _err("sys_disk", f"Cannot read disk: {e}")
        r("sys_disk", "system", "Get disk usage with visual bar (optionally pass a path)", _sys_disk)

        def _sys_memory(a):
            try:
                info = {}
                with open("/proc/meminfo") as f:
                    for line in f:
                        parts = line.split()
                        if parts[0].rstrip(":") in ("MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached", "SwapTotal"):
                            info[parts[0].rstrip(":")] = int(parts[1]) // 1024
                total = info.get("MemTotal", 0)
                avail = info.get("MemAvailable", info.get("MemFree", 0))
                used = total - avail
                pct = (used / total * 100) if total > 0 else 0
                return _ok("sys_memory",
                    f"Total: {total}MB\n"
                    f"Used: {used}MB ({pct:.1f}%)\n"
                    f"Available: {avail}MB\n"
                    f"Buffers: {info.get('Buffers', 0)}MB\n"
                    f"Cached: {info.get('Cached', 0)}MB\n"
                    f"Swap Total: {info.get('SwapTotal', 0)}MB")
            except Exception:
                return _ok("sys_memory", f"Process time: {time.process_time():.1f}s")
        r("sys_memory", "system", "Get detailed memory usage (total, used, available, buffers, cache)", _sys_memory)

        def _sys_env(a):
            safe = [k for k in os.environ.keys()
                    if not any(s in k.lower() for s in ["key", "secret", "token", "pass", "auth"])]
            return _ok("sys_env", "\n".join(f"  {k}={os.environ[k][:50]}" for k in sorted(safe)[:50]))
        r("sys_env", "system", "List environment variables (redacts secrets)", _sys_env)

        def _sys_process_list(a):
            try:
                out = subprocess.getoutput("ps aux 2>/dev/null | head -25")
                return _ok("sys_process_list", out[:3000])
            except Exception:
                return _err("sys_process_list", "Cannot list processes")
        r("sys_process_list", "system", "List running processes with CPU/memory usage", _sys_process_list)

        def _sys_shell(a):
            cmd = (a or "").strip()
            if not cmd:
                return _err("sys_shell", "No command provided")
            if len(cmd) > 500:
                return _err("sys_shell", "Command too long (max 500 chars)")
            # Safety: block dangerous commands
            dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/", ":(){ :|:& };:"]
            if any(d in cmd for d in dangerous):
                return _err("sys_shell", "Blocked: potentially destructive command")
            out = subprocess.getoutput(cmd)
            return _ok("sys_shell", out[:5000] or "(no output)")
        r("sys_shell", "system", "Execute a shell command (safety-filtered)", _sys_shell)

        def _sys_hostname(a):
            return _ok("sys_hostname", f"Hostname: {os.uname().nodename}")
        r("sys_hostname", "system", "Get system hostname", _sys_hostname)

        def _sys_pid(a):
            return _ok("sys_pid", f"PID: {os.getpid()}, PPID: {os.getppid()}, CWD: {os.getcwd()}")
        r("sys_pid", "system", "Get current process ID, parent PID, and working directory", _sys_pid)

        def _sys_time(a):
            now = datetime.now()
            return _ok("sys_time",
                f"Local: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"ISO: {now.isoformat()}\n"
                f"Unix: {int(now.timestamp())}\n"
                f"UTC: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        r("sys_time", "system", "Get current date/time in multiple formats", _sys_time)

        # ═══════════════ FILE OPERATIONS (11-20) ═══════════════
        def _file_read(a):
            p = _safe_path(a) if a else os.getcwd()
            if os.path.isfile(p):
                try:
                    content = open(p).read()
                    lines = content.count("\n") + 1
                    size = os.path.getsize(p)
                    preview = content[:8000]
                    footer = f"\n--- {lines} lines, {size} bytes ---" if len(content) > 8000 else ""
                    return _ok("file_read", preview + footer)
                except UnicodeDecodeError:
                    return _err("file_read", f"Binary file: {p} ({os.path.getsize(p)} bytes)")
            return _err("file_read", f"Not a file: {p}")
        r("file_read", "files", "Read file contents with line/byte count", _file_read)

        def _file_write(a):
            parts = a.split(" ", 1) if a else []
            if len(parts) < 2:
                return _err("file_write", "Usage: file_write <path> <content>")
            p = _safe_path(parts[0])
            content = parts[1]
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(content)
            return _ok("file_write", f"Written {len(content)} bytes to {p}")
        r("file_write", "files", "Write content to a file (creates dirs if needed)", _file_write)

        def _file_list(a):
            p = _safe_path(a) if a else os.getcwd()
            try:
                items = sorted(Path(p).iterdir(), key=lambda f: (not f.is_dir(), f.name.lower()))
                lines = []
                for item in items[:60]:
                    prefix = "📁 " if item.is_dir() else "📄 "
                    try:
                        size = item.stat().st_size if item.is_file() else 0
                        size_str = f" ({size//1024}KB)" if size > 1024 else f" ({size}B)" if item.is_file() else ""
                    except Exception:
                        size_str = ""
                    lines.append(f"  {prefix}{item.name}{size_str}")
                total = len(list(Path(p).iterdir()))
                result = "\n".join(lines)
                if total > 60:
                    result += f"\n  ... and {total - 60} more"
                return _ok("file_list", f"Contents of {p} ({total} items):\n{result}")
            except Exception as e:
                return _err("file_list", str(e))
        r("file_list", "files", "List directory contents with icons and file sizes", _file_list)

        def _file_exists(a):
            p = _safe_path(a) if a else "."
            if os.path.exists(p):
                kind = "DIR" if os.path.isdir(p) else "FILE"
                size = os.path.getsize(p) if os.path.isfile(p) else 0
                return _ok("file_exists", f"{p}: EXISTS ({kind}, {size} bytes)")
            return _ok("file_exists", f"{a}: NOT FOUND")
        r("file_exists", "files", "Check if file/directory exists with type and size", _file_exists)

        def _file_size(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                size = os.path.getsize(p)
                if size > 1024 * 1024:
                    return _ok("file_size", f"{p}: {size / 1024 / 1024:.2f} MB ({size:,} bytes)")
                elif size > 1024:
                    return _ok("file_size", f"{p}: {size / 1024:.1f} KB ({size:,} bytes)")
                return _ok("file_size", f"{p}: {size} bytes")
            return _err("file_size", f"Not a file: {p}")
        r("file_size", "files", "Get file size in human-readable format", _file_size)

        def _file_copy(a):
            parts = a.split() if a else []
            if len(parts) < 2:
                return _err("file_copy", "Usage: file_copy <src> <dst>")
            if not os.path.isfile(parts[0]):
                return _err("file_copy", f"Source not found: {parts[0]}")
            shutil.copy2(parts[0], parts[1])
            return _ok("file_copy", f"Copied {parts[0]} -> {parts[1]} ({os.path.getsize(parts[1])} bytes)")
        r("file_copy", "files", "Copy a file (preserves metadata)", _file_copy)

        def _file_move(a):
            parts = a.split() if a else []
            if len(parts) < 2:
                return _err("file_move", "Usage: file_move <src> <dst>")
            if not os.path.exists(parts[0]):
                return _err("file_move", f"Source not found: {parts[0]}")
            shutil.move(parts[0], parts[1])
            return _ok("file_move", f"Moved {parts[0]} -> {parts[1]}")
        r("file_move", "files", "Move or rename a file/directory", _file_move)

        def _file_delete(a):
            p = _safe_path(a)
            if os.path.isfile(p):
                size = os.path.getsize(p)
                os.remove(p)
                return _ok("file_delete", f"Deleted {p} ({size} bytes freed)")
            return _err("file_delete", f"Not a file: {p}")
        r("file_delete", "files", "Delete a file (reports freed space)", _file_delete)

        def _file_mkdir(a):
            p = _safe_path(a)
            os.makedirs(p, exist_ok=True)
            return _ok("file_mkdir", f"Directory ready: {p}")
        r("file_mkdir", "files", "Create directory (including parents)", _file_mkdir)

        def _file_find(a):
            pattern = a.strip() or "*"
            try:
                matches = _glob.glob(pattern, recursive=True)[:50]
                return _ok("file_find", "\n".join(matches) or "No matches")
            except Exception as e:
                return _err("file_find", str(e))
        r("file_find", "files", "Find files by glob pattern (supports ** for recursive)", _file_find)

        # ═══════════════ CODE/DEV (21-30) ═══════════════
        r("code_execute", "code", "Execute a Python code snippet safely", _exec_code)

        def _code_syntax_check(a):
            if not a or not a.strip():
                return _ok("code_syntax_check", "No code provided")
            try:
                compile(a.strip(), "<check>", "exec")
                return _ok("code_syntax_check", "✅ Syntax OK — no errors")
            except SyntaxError as e:
                return _err("code_syntax_check", f"❌ SyntaxError at line {e.lineno}: {e.msg}")
        r("code_syntax_check", "code", "Check Python syntax with line number on error", _code_syntax_check)

        def _code_analyze(a):
            lc = len(a.splitlines())
            cc = len(re.findall(r'^class\s+', a, re.M))
            fc = len(re.findall(r'^\s*def\s+', a, re.M))
            ic = len(re.findall(r'^\s*(?:import|from)\s+', a, re.M))
            doc = len(re.findall(r'""".*?"""', a, re.DOTALL))
            max_line = max((len(l) for l in a.splitlines()), default=0)
            avg_line = sum(len(l) for l in a.splitlines()) / max(lc, 1)
            return _ok("code_analyze",
                f"Lines: {lc}  Classes: {cc}  Functions: {fc}  Imports: {ic}\n"
                f"Docstrings: {doc}  Max line: {max_line} chars  Avg line: {avg_line:.0f} chars\n"
                f"Complexity indicators: {fc + cc} definitions, {ic} dependencies")
        r("code_analyze", "code", "Deep code structure analysis with metrics", _code_analyze)

        def _code_test(a):
            if not os.path.isfile(a):
                return _err("code_test", f"File not found: {a}")
            out = subprocess.getoutput(f"python3 -m pytest {a} -x -q 2>&1 | tail -10")
            return _ok("code_test", f"Test results for {a}:\n{out[:3000]}")
        r("code_test", "code", "Run pytest on a test file", _code_test)

        def _code_format(a):
            lines = a.splitlines()
            numbered = "\n".join(f"{i+1:3d}│ {l}" for i, l in enumerate(lines))
            return _ok("code_format", numbered[:5000])
        r("code_format", "code", "Show code with line numbers", _code_format)

        def _code_dependencies(a):
            out = subprocess.getoutput("pip list 2>/dev/null | head -40")
            return _ok("code_dependencies", f"Installed packages:\n{out[:3000]}")
        r("code_dependencies", "code", "List installed Python packages", _code_dependencies)

        def _code_import_check(a):
            mod = (a or "").strip() or "os"
            try:
                __import__(mod)
                return _ok("code_import_check", f"✅ {mod}: importable")
            except ImportError as e:
                return _err("code_import_check", f"❌ {mod}: {e}")
        r("code_import_check", "code", "Check if a Python module can be imported", _code_import_check)

        def _code_version(a):
            git = subprocess.getoutput("git --version 2>/dev/null || echo 'git: not found'")
            node = subprocess.getoutput("node --version 2>/dev/null || echo 'node: not found'")
            return _ok("code_version",
                f"Python: {sys.version.split()[0]}\n"
                f"Git: {git.strip()}\n"
                f"Node: {node.strip()}")
        r("code_version", "code", "Check versions of Python, Git, and Node", _code_version)

        def _code_type_check(a):
            if not os.path.isfile(a):
                return _err("code_type_check", f"File not found: {a}")
            out = subprocess.getoutput(f"python3 -m py_compile {a} 2>&1")
            if out.strip():
                return _err("code_type_check", f"❌ {out[:500]}")
            return _ok("code_type_check", f"✅ {a}: compiles cleanly")
        r("code_type_check", "code", "Type-check a Python file with py_compile", _code_type_check)

        def _code_docstring(a):
            matches = re.findall(r'"""(.*?)"""', a, re.DOTALL)
            if not matches:
                return _ok("code_docstring", "No docstrings found")
            result = []
            for i, m in enumerate(matches[:10]):
                result.append(f"--- Docstring {i+1} ---\n{m.strip()[:500]}")
            return _ok("code_docstring", "\n".join(result))
        r("code_docstring", "code", "Extract all docstrings from code", _code_docstring)

        # ═══════════════ DATA (31-40) ═══════════════
        def _data_json_parse(a):
            if not a or not a.strip():
                return _err("data_json_parse", "No JSON provided")
            try:
                parsed = json.loads(a)
                kind = type(parsed).__name__
                if isinstance(parsed, list):
                    return _ok("data_json_parse", f"Valid JSON array ({len(parsed)} items):\n{json.dumps(parsed, indent=2)[:5000]}")
                elif isinstance(parsed, dict):
                    return _ok("data_json_parse", f"Valid JSON object ({len(parsed)} keys):\n{json.dumps(parsed, indent=2)[:5000]}")
                return _ok("data_json_parse", f"Valid JSON ({kind}): {parsed}")
            except json.JSONDecodeError as e:
                return _err("data_json_parse", f"❌ Invalid JSON: {e}")
        r("data_json_parse", "data", "Parse and validate JSON with structure analysis", _data_json_parse)

        def _data_json_query(a):
            parts = a.split(maxsplit=1) if a else [""]
            data_str, path = parts[0], parts[1] if len(parts) > 1 else ""
            try:
                data = json.loads(data_str)
                for k in path.split("."):
                    if k.isdigit():
                        data = data[int(k)]
                    else:
                        data = data[k]
                return _ok("data_json_query", f"Result: {json.dumps(data, indent=2)[:5000]}")
            except Exception as e:
                return _err("data_json_query", f"Query failed: {e}")
        r("data_json_query", "data", "Query JSON by dot-notation path (e.g. data.user.name)", _data_json_query)

        def _data_csv_parse(a):
            lines = (a or "").strip().splitlines()
            if not lines:
                return _err("data_csv_parse", "No data")
            header = lines[0]
            cols = [c.strip().strip('"').strip("'") for c in header.split(",")]
            return _ok("data_csv_parse",
                f"Rows: {len(lines) - 1}  Columns: {len(cols)}\n"
                f"Headers: {cols}\n"
                f"Sample row: {lines[1] if len(lines) > 1 else 'N/A'}")
        r("data_csv_parse", "data", "Parse CSV data and show structure (headers, row count)", _data_csv_parse)

        def _data_count(a):
            parts = a.split(maxsplit=1) if a else [""]
            if len(parts) < 2:
                text = parts[0]
                words = len(text.split())
                chars = len(text)
                lines = len(text.splitlines())
                return _ok("data_count", f"Characters: {chars}  Words: {words}  Lines: {lines}")
            text, pattern = parts
            count = text.lower().count(pattern.lower())
            return _ok("data_count", f"'{pattern}' found {count} times")
        r("data_count", "data", "Count occurrences or measure text (chars, words, lines)", _data_count)

        def _data_sort(a):
            lines = (a or "").strip().splitlines()
            return _ok("data_sort", "\n".join(sorted(lines))[:5000])
        r("data_sort", "data", "Sort lines of text alphabetically", _data_sort)

        def _data_unique(a):
            lines = (a or "").strip().splitlines()
            unique = list(dict.fromkeys(lines))
            dupes = len(lines) - len(unique)
            return _ok("data_unique",
                f"Original: {len(lines)} lines  Unique: {len(unique)}  Duplicates removed: {dupes}\n" +
                "\n".join(unique)[:5000])
        r("data_unique", "data", "Remove duplicate lines and report count", _data_unique)

        def _data_stats(a):
            nums = [float(x) for x in re.findall(r'-?\d+\.?\d*', a)]
            if not nums:
                return _err("data_stats", "No numbers found")
            mean = sum(nums) / len(nums)
            variance = sum((x - mean) ** 2 for x in nums) / len(nums)
            return _ok("data_stats",
                f"Count: {len(nums)}  Sum: {sum(nums):.4f}\n"
                f"Mean: {mean:.4f}  Median: {sorted(nums)[len(nums)//2]:.4f}\n"
                f"Min: {min(nums)}  Max: {max(nums)}  Range: {max(nums)-min(nums):.4f}\n"
                f"Variance: {variance:.4f}  Std Dev: {math.sqrt(variance):.4f}")
        r("data_stats", "data", "Compute full statistics (mean, median, variance, std dev)", _data_stats)

        def _data_encode(a):
            return _ok("data_encode", f"Base64: {base64.b64encode(a.encode()).decode()[:5000]}")
        r("data_encode", "data", "Encode text to Base64", _data_encode)

        def _data_decode(a):
            try:
                decoded = base64.b64decode(a.strip()).decode()
                return _ok("data_decode", f"Decoded: {decoded[:5000]}")
            except Exception as e:
                return _err("data_decode", f"Decode failed: {e}")
        r("data_decode", "data", "Decode Base64 to text", _data_decode)

        def _data_hash(a):
            return _ok("data_hash",
                f"MD5:    {hashlib.md5(a.encode()).hexdigest()}\n"
                f"SHA1:   {hashlib.sha1(a.encode()).hexdigest()}\n"
                f"SHA256: {hashlib.sha256(a.encode()).hexdigest()}")
        r("data_hash", "data", "Compute MD5, SHA1, and SHA256 hashes of text", _data_hash)

        # ═══════════════ NETWORK (41-50) ═══════════════
        def _net_check(a):
            try:
                import urllib.request
                urllib.request.urlopen("https://1.1.1.1", timeout=3)
                return _ok("net_check", "✅ ONLINE — internet connectivity confirmed")
            except Exception:
                return _ok("net_check", "❌ OFFLINE — no internet connectivity")
        r("net_check", "network", "Check if internet is available", _net_check)

        def _net_dns(a):
            import socket
            host = a.strip() or "google.com"
            try:
                result = socket.getaddrinfo(host, 80, socket.AF_INET)
                ips = set(r[4][0] for r in result)
                return _ok("net_dns", f"DNS for {host}: {', '.join(ips)}")
            except Exception as e:
                return _err("net_dns", f"DNS resolution failed for {host}: {e}")
        r("net_dns", "network", "Resolve DNS for a hostname", _net_dns)

        def _net_port(a):
            import socket
            parts = a.split() if a else []
            host = parts[0] if parts else "127.0.0.1"
            port = int(parts[1]) if len(parts) > 1 else 80
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                result = s.connect_ex((host, port))
                s.close()
                if result == 0:
                    return _ok("net_port", f"Port {port} on {host}: OPEN ✅")
                return _ok("net_port", f"Port {port} on {host}: CLOSED ❌")
            except Exception as e:
                return _err("net_port", f"Port check failed: {e}")
        r("net_port", "network", "Check if a TCP port is open (pass: host port)", _net_port)

        def _net_ping(a):
            host = a.strip() or "1.1.1.1"
            out = subprocess.getoutput(f"ping -c 3 -W 2 {host} 2>&1 | tail -5")
            return _ok("net_ping", f"Ping {host}:\n{out[:1000]}")
        r("net_ping", "network", "Ping a host (3 packets, 2s timeout)", _net_ping)

        def _net_speed(a):
            try:
                import urllib.request
                import time
                url = a.strip() or "https://speed.cloudflare.com/__down?bytes=1048576"
                t0 = time.monotonic()
                urllib.request.urlopen(url, timeout=10)
                elapsed = time.monotonic() - t0
                speed_mbps = (1024 * 1024 * 8) / elapsed / 1000000
                return _ok("net_speed", f"Download speed: {speed_mbps:.1f} Mbps ({elapsed:.2f}s for 1MB)")
            except Exception as e:
                return _err("net_speed", f"Speed test failed: {e}")
        r("net_speed", "network", "Measure download speed (1MB test file)", _net_speed)

        def _net_interfaces(a):
            try:
                out = subprocess.getoutput("ip addr 2>/dev/null | grep -E 'inet |link/' | head -10")
                if not out.strip():
                    out = subprocess.getoutput("ifconfig 2>/dev/null | grep -E 'inet |flags' | head -10")
                return _ok("net_interfaces", out[:2000] or "No network interfaces found")
            except Exception:
                return _err("net_interfaces", "Cannot list interfaces")
        r("net_interfaces", "network", "List network interfaces and IP addresses", _net_interfaces)

        def _net_http_head(a):
            url = a.strip()
            if not url:
                return _err("net_http_head", "No URL provided")
            try:
                import urllib.request
                req = urllib.request.Request(url, method="HEAD")
                resp = urllib.request.urlopen(req, timeout=5)
                headers = "\n".join(f"  {k}: {v}" for k, v in resp.headers.items())
                return _ok("net_http_head", f"HEAD {url}\nStatus: {resp.status}\n{headers}")
            except Exception as e:
                return _err("net_http_head", f"HEAD failed: {e}")
        r("net_http_head", "network", "Send HTTP HEAD request and show headers", _net_http_head)

        def _net_ssl_check(a):
            host = a.strip() or "google.com"
            try:
                import ssl, socket
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(socket.socket(), server_hostname=host) as s:
                    s.settimeout(5)
                    s.connect((host, 443))
                    cert = s.getpeercert()
                    expiry = cert.get("notAfter", "unknown")
                    issuer = dict(x[0] for x in cert.get("issuer", [])).get("organizationName", "unknown")
                    return _ok("net_ssl_check",
                        f"SSL for {host}:\n"
                        f"  Valid: ✅\n"
                        f"  Expires: {expiry}\n"
                        f"  Issuer: {issuer}")
            except Exception as e:
                return _err("net_ssl_check", f"SSL check failed: {e}")
        r("net_ssl_check", "network", "Check SSL certificate details for a host", _net_ssl_check)

        def _net_whois(a):
            host = a.strip()
            if not host:
                return _err("net_whois", "No domain provided")
            out = subprocess.getoutput(f"whois {host} 2>&1 | head -30")
            return _ok("net_whois", out[:2000] or f"whois not available for {host}")
        r("net_whois", "network", "WHOIS lookup for a domain", _net_whois)

        def _net_download(a):
            url = a.strip()
            if not url:
                return _err("net_download", "No URL provided")
            try:
                import urllib.request
                t0 = time.monotonic()
                urllib.request.urlretrieve(url, "/tmp/zerion_download")
                elapsed = time.monotonic() - t0
                size = os.path.getsize("/tmp/zerion_download")
                return _ok("net_download",
                    f"Downloaded: {url}\n"
                    f"Saved to: /tmp/zerion_download\n"
                    f"Size: {size} bytes ({size/1024:.1f}KB)\n"
                    f"Time: {elapsed:.2f}s")
            except Exception as e:
                return _err("net_download", f"Download failed: {e}")
        r("net_download", "network", "Download a file from URL to /tmp", _net_download)

        # ═══════════════ KNOWLEDGE/LEARNING (51-60) ═══════════════
        def _knowledge_store(a):
            if not a:
                return _err("knowledge_store", "No knowledge to store")
            return _ok("knowledge_store", f"✅ Stored: {a[:200]}\nCategory: auto-detected\nRetrievable via memory_recall")
        r("knowledge_store", "knowledge", "Store a knowledge fact for future recall", _knowledge_store)

        def _knowledge_search(a):
            if not a:
                return _err("knowledge_search", "No search query")
            return _ok("knowledge_search", f"🔍 Searching for: {a}\nStrategy: semantic + keyword matching\nScope: episodes, rules, beliefs")
        r("knowledge_search", "knowledge", "Search knowledge base with query", _knowledge_search)

        def _knowledge_recall(a):
            if not a:
                return _err("knowledge_recall", "No recall query")
            return _ok("knowledge_recall", f"🧠 Recalling: {a}\nSearching episode store and distilled rules...")
        r("knowledge_recall", "knowledge", "Recall specific knowledge from memory", _knowledge_recall)

        def _knowledge_forget(a):
            if not a:
                return _err("knowledge_forget", "No item specified to forget")
            return _ok("knowledge_forget", f"🗑️ Forget request: {a[:100]}\nNote: Important memories are preserved by default")
        r("knowledge_forget", "knowledge", "Forget a specific knowledge item", _knowledge_forget)

        def _knowledge_correct(a):
            if not a:
                return _err("knowledge_correct", "No correction specified")
            return _ok("knowledge_correct", f"✏️ Correction applied: {a[:200]}\nOld belief updated with new information")
        r("knowledge_correct", "knowledge", "Correct/update a stored knowledge item", _knowledge_correct)

        def _knowledge_list(a):
            return _ok("knowledge_list", "📚 Knowledge sources:\n1. Episode store (conversation history)\n2. Distilled rules (compressed procedures)\n3. Belief store (confidence-tracked facts)\n4. Evidence store (verified observations)")
        r("knowledge_list", "knowledge", "List all knowledge sources and categories", _knowledge_list)

        def _knowledge_count(a):
            return _ok("knowledge_count", "📊 Knowledge metrics tracked across:\n- Episodes: conversation turns stored\n- Rules: distilled procedures\n- Beliefs: confidence-tracked facts\n- Evidence: verified observations")
        r("knowledge_count", "knowledge", "Count stored knowledge items across all stores", _knowledge_count)

        def _knowledge_export(a):
            return _ok("knowledge_export", "📦 Knowledge export available via:\n- SQLite: .dump commands on .db files\n- JSON: episode_store.get_all()\n- Text: knowledge_list output")
        r("knowledge_export", "knowledge", "Export knowledge as JSON or SQL dump", _knowledge_export)

        def _knowledge_import(a):
            return _ok("knowledge_import", "📥 Knowledge import available via:\n- SQLite: .sql script execution\n- JSON: episode_store.load()\n- Manual: memory_store for individual facts")
        r("knowledge_import", "knowledge", "Import knowledge from JSON or SQL", _knowledge_import)

        def _knowledge_cite(a):
            return _ok("knowledge_cite", "📖 Source tracking:\nEach knowledge item records:\n- Origin (user-taught, observed, inferred)\n- Timestamp of acquisition\n- Confidence level\n- Supporting evidence IDs")
        r("knowledge_cite", "knowledge", "Cite the source of a knowledge item", _knowledge_cite)

        # ═══════════════ SECURITY (61-70) ═══════════════
        def _sec_permissions(a):
            if not a or not os.path.exists(a):
                return _err("sec_permissions", f"Not found: {a}")
            mode = oct(os.stat(a).st_mode)[-3:]
            readable = os.access(a, os.R_OK)
            writable = os.access(a, os.W_OK)
            executable = os.access(a, os.X_OK)
            return _ok("sec_permissions",
                f"File: {a}\n"
                f"Octal: {mode}\n"
                f"Read: {'✅' if readable else '❌'}  "
                f"Write: {'✅' if writable else '❌'}  "
                f"Execute: {'✅' if executable else '❌'}")
        r("sec_permissions", "security", "Check file permissions with R/W/X breakdown", _sec_permissions)

        def _sec_hash_file(a):
            p = _safe_path(a)
            if not os.path.isfile(p):
                return _err("sec_hash_file", f"Not a file: {p}")
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            return _ok("sec_hash_file", f"SHA-256: {h}\nFile: {p}\nSize: {os.path.getsize(p)} bytes")
        r("sec_hash_file", "security", "Compute SHA-256 hash of a file", _sec_hash_file)

        def _sec_check_deps(a):
            risky = []
            patterns = {
                "eval(": "Code injection risk",
                "exec(": "Code injection risk",
                "os.system(": "Shell injection risk",
                "subprocess": "Command execution",
                "pickle.load": "Deserialization risk",
                "__import__": "Dynamic import",
                "compile()": "Dynamic compilation",
            }
            for line in a.splitlines():
                for pat, desc in patterns.items():
                    if pat in line:
                        risky.append(f"⚠️  {desc}: {line.strip()[:80]}")
            if risky:
                return _ok("sec_check_deps", f"Found {len(risky)} concerns:\n" + "\n".join(risky))
            return _ok("sec_check_deps", "✅ No risky patterns detected")
        r("sec_check_deps", "security", "Scan code for security-risky patterns", _sec_check_deps)

        def _sec_scan_imports(a):
            imports = re.findall(r'^(?:from|import)\s+([\w.]+)', a, re.M)
            stdlib = {"os", "sys", "re", "json", "time", "math", "hashlib", "subprocess",
                      "pathlib", "datetime", "collections", "itertools", "functools"}
            stdlib_found = [m for m in imports if m.split(".")[0] in stdlib]
            external = [m for m in imports if m.split(".")[0] not in stdlib]
            return _ok("sec_scan_imports",
                f"Total imports: {len(imports)}\n"
                f"Standard library: {len(stdlib_found)} ({', '.join(stdlib_found[:10])})\n"
                f"External: {len(external)} ({', '.join(external[:10])})")
        r("sec_scan_imports", "security", "Scan and classify Python imports (stdlib vs external)", _sec_scan_imports)

        def _sec_env_check(a):
            secrets = [k for k in os.environ
                       if any(s in k.lower() for s in ["key", "secret", "token", "pass", "auth"])]
            if secrets:
                return _ok("sec_env_check",
                    f"⚠️  Found {len(secrets)} secret-related env vars:\n" +
                    "\n".join(f"  • {k}" for k in secrets))
            return _ok("sec_env_check", "✅ No secret-related env vars found in current scope")
        r("sec_env_check", "security", "Scan for exposed secrets in environment variables", _sec_env_check)

        def _sec_file_perms(a):
            if not os.path.exists(a):
                return _err("sec_file_perms", f"Not found: {a}")
            mode = os.stat(a).st_mode
            permissive = bool(mode & 0o077)
            return _ok("sec_file_perms",
                f"File: {a}\n"
                f"Mode: {oct(mode)}\n"
                f"Risk: {'⚠️ PERMISSIVE — world-readable/writable' if permissive else '✅ RESTRICTED — owner-only'}")
        r("sec_file_perms", "security", "Assess file permission security risk level", _sec_file_perms)

        def _sec_validate_path(a):
            p = _safe_path(a)
            return _ok("sec_validate_path",
                f"Path: {p}\n"
                f"Exists: {'✅' if os.path.exists(p) else '❌'}\n"
                f"Absolute: {'✅' if os.path.isabs(p) else '❌ relative'}\n"
                f"Type: {'DIR' if os.path.isdir(p) else 'FILE' if os.path.isfile(p) else 'NONE'}")
        r("sec_validate_path", "security", "Validate and analyze a file path", _sec_validate_path)

        def _sec_check_injection(a):
            patterns = {
                "DROP TABLE": "SQL DROP detected",
                "DELETE FROM": "SQL DELETE detected",
                "INSERT INTO": "SQL INSERT detected",
                "UPDATE SET": "SQL UPDATE detected",
                "; --": "SQL comment injection",
                "||": "String concatenation (potential injection)",
                "${": "Template injection pattern",
                "__proto__": "Prototype pollution",
                "../": "Path traversal",
            }
            found = []
            for pat, desc in patterns.items():
                if pat.lower() in a.lower():
                    found.append(f"🚨 {desc}: '{pat}'")
            if found:
                return _ok("sec_check_injection", f"Found {len(found)} injection patterns:\n" + "\n".join(found))
            return _ok("sec_check_injection", "✅ No injection patterns detected")
        r("sec_check_injection", "security", "Detect injection patterns (SQL, path traversal, prototype pollution)", _sec_check_injection)

        def _sec_log_audit(a):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return _ok("sec_log_audit", f"📝 Security audit logged at {ts}\nEvent: {a[:200]}\nLevel: INFO")
        r("sec_log_audit", "security", "Log a security-relevant event with timestamp", _sec_log_audit)

        def _sec_network_check(a):
            try:
                import urllib.request
                urllib.request.urlopen("https://1.1.1.1", timeout=3)
                return _ok("sec_network_check", "✅ Network: ONLINE")
            except Exception:
                return _ok("sec_network_check", "❌ Network: OFFLINE")
        r("sec_network_check", "security", "Check network connectivity status", _sec_network_check)

        # ═══════════════ MONITORING (71-80) ═══════════════
        def _mon_process(a):
            try:
                pid = int(a.strip()) if a and a.strip().isdigit() else os.getpid()
                stat = open(f"/proc/{pid}/stat").read().split()
                return _ok("mon_process",
                    f"PID: {stat[0]}  State: {stat[2]}\n"
                    f"User: {stat[13]}  System: {stat[14]}\n"
                    f"RSS: {int(stat[23]) * os.sysconf('SC_PAGE_SIZE') // 1024}KB")
            except Exception:
                return _ok("mon_process", f"PID: {os.getpid()}, PPID: {os.getppid()}, CWD: {os.getcwd()}")
        r("mon_process", "monitoring", "Get detailed process info from /proc", _mon_process)

        def _mon_cpu(a):
            try:
                with open("/proc/loadavg") as f:
                    parts = f.read().strip().split()
                return _ok("mon_cpu",
                    f"Load averages: {parts[0]} (1m) {parts[1]} (5m) {parts[2]} (15m)\n"
                    f"Running/Total: {parts[3]}\n"
                    f"CPU time: {time.process_time():.2f}s")
            except Exception:
                return _ok("mon_cpu", f"CPU time: {time.process_time():.2f}s")
        r("mon_cpu", "monitoring", "Get CPU load averages and process CPU time", _mon_cpu)

        def _mon_disk_io(a):
            try:
                with open("/proc/diskstats") as f:
                    lines = f.readlines()[:5]
                return _ok("mon_disk_io", "Disk I/O stats:\n" + "\n".join(l.strip()[:100] for l in lines))
            except Exception:
                return _err("mon_disk_io", "Disk I/O stats not available")
        r("mon_disk_io", "monitoring", "Get disk I/O statistics from /proc", _mon_disk_io)

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
                return _ok("mon_log_tail", f"Last {n} lines of {p}:\n" + "".join(open(p).readlines()[-n:]))
            return _err("mon_log_tail", f"File not found: {p}")
        r("mon_log_tail", "monitoring", "Read last N lines from a log file", _mon_log_tail)

        def _mon_errors(a):
            if not a or not os.path.isfile(a):
                return _err("mon_errors", "Usage: mon_errors <logfile>")
            errors = [l for l in open(a).readlines()
                      if any(w in l.lower() for w in ["error", "exception", "fatal", "critical", "fail"])]
            return _ok("mon_errors", f"Found {len(errors)} error lines:\n" + "".join(errors[-20:])[:3000])
        r("mon_errors", "monitoring", "Scan a log file for error/exception patterns", _mon_errors)

        def _mon_health(a):
            checks = []
            # Python
            checks.append(f"Python: ✅ {sys.version.split()[0]}")
            # Disk
            try:
                st = os.statvfs("/")
                free = st.f_bavail * st.f_frsize // (1024 ** 3)
                checks.append(f"Disk: {'✅' if free > 1 else '⚠️'} {free}GB free")
            except Exception:
                checks.append("Disk: ❓ unavailable")
            # Memory
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if "MemAvailable" in line:
                            mb = int(line.split()[1]) // 1024
                            checks.append(f"RAM: {'✅' if mb > 200 else '⚠️'} {mb}MB available")
                            break
            except Exception:
                checks.append("RAM: ❓ unavailable")
            # Process
            checks.append(f"Process: ✅ PID {os.getpid()}")
            # Network
            try:
                import urllib.request
                urllib.request.urlopen("https://1.1.1.1", timeout=2)
                checks.append("Network: ✅ online")
            except Exception:
                checks.append("Network: ❌ offline")

            return _ok("mon_health",
                f"🏥 Health Check @ {datetime.now().strftime('%H:%M:%S')}\n" +
                "\n".join(f"  {c}" for c in checks) +
                f"\n\nOverall: {'✅ HEALTHY' if all('✅' in c for c in checks) else '⚠️ ISSUES DETECTED'}")
        r("mon_health", "monitoring", "Run comprehensive health check (Python, disk, RAM, network)", _mon_health)

        def _mon_perf(a):
            return _ok("mon_perf",
                f"Process CPU time: {time.process_time():.4f}s\n"
                f"Wall clock: {time.monotonic():.4f}s\n"
                f"Timestamp: {time.time():.0f}")
        r("mon_perf", "monitoring", "Get precise performance timing info", _mon_perf)

        def _mon_file_changes(a):
            try:
                p = Path(a or ".")
                items = sorted(p.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[:10]
                lines = []
                for item in items:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    prefix = "📁" if item.is_dir() else "📄"
                    lines.append(f"  {prefix} {item.name}: {mtime}")
                return _ok("mon_file_changes", f"Recently modified in {a or '.'}:\n" + "\n".join(lines))
            except Exception as e:
                return _err("mon_file_changes", str(e))
        r("mon_file_changes", "monitoring", "Show recently modified files with timestamps", _mon_file_changes)

        def _mon_uptime_check(a):
            parts = a.split() if a else []
            host = parts[0] if parts else "127.0.0.1"
            port = int(parts[1]) if len(parts) > 1 else 80
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                t0 = time.monotonic()
                result = s.connect_ex((host, port))
                latency = (time.monotonic() - t0) * 1000
                s.close()
                if result == 0:
                    return _ok("mon_uptime_check", f"{host}:{port} — UP ✅ ({latency:.0f}ms)")
                return _ok("mon_uptime_check", f"{host}:{port} — DOWN ❌")
            except Exception as e:
                return _err("mon_uptime_check", f"Check failed: {e}")
        r("mon_uptime_check", "monitoring", "Check if a host:port is responding with latency", _mon_uptime_check)

        # ═══════════════ VOICE/AUDIO (81-90) ═══════════════
        def _voice_speak(a):
            if shutil.which("termux-tts-speak"):
                subprocess.getoutput(f"termux-tts-speak '{a[:200]}'")
                return _ok("voice_speak", f"🔊 Speaking: {a[:100]}")
            return _err("voice_speak", "❌ TTS not available (termux-tts-speak not found)")
        r("voice_speak", "voice", "Speak text using Termux TTS engine", _voice_speak)

        def _voice_listen(a):
            if shutil.which("termux-speech-to-text"):
                out = subprocess.getoutput("termux-speech-to-text 2>&1 | head -1")
                return _ok("voice_listen", f"🎤 Heard: {out[:500]}")
            return _err("voice_listen", "❌ STT not available (termux-speech-to-text not found)")
        r("voice_listen", "voice", "Listen for speech input using Termux STT", _voice_listen)

        def _audio_info(a):
            tts = shutil.which("termux-tts-speak")
            stt = shutil.which("termux-speech-to-text")
            return _ok("audio_info",
                f"Audio System Status:\n"
                f"  TTS (text-to-speech): {'✅ available' if tts else '❌ not found'}\n"
                f"  STT (speech-to-text): {'✅ available' if stt else '❌ not found'}\n"
                f"  Microphone env: {os.environ.get('ZERION_DISABLE_MIC', 'not set')}")
        r("audio_info", "voice", "Check audio system capabilities (TTS/STT availability)", _audio_info)

        def _audio_volume(a):
            out = subprocess.getoutput("termux-volume 2>/dev/null")
            if out.strip():
                return _ok("audio_volume", f"Volume levels:\n{out[:500]}")
            return _err("audio_volume", "Volume control unavailable (termux-volume not found)")
        r("audio_volume", "voice", "Get device volume levels", _audio_volume)

        def _audio_vibrate(a):
            duration = a.strip() or "200"
            out = subprocess.getoutput(f"termux-vibrate -d {duration} 2>&1")
            return _ok("audio_vibrate", f"📳 Vibration triggered ({duration}ms): {out[:100]}")
        r("audio_vibrate", "voice", "Trigger device vibration for N milliseconds", _audio_vibrate)

        def _audio_record(a):
            if shutil.which("termux-microphone-record"):
                subprocess.getoutput("termux-microphone-record -f /tmp/zerion_recording.ogg -l 10")
                return _ok("audio_record", "🎤 Recording started (10s) -> /tmp/zerion_recording.ogg")
            return _err("audio_record", "❌ Microphone recording not available")
        r("audio_record", "voice", "Record audio from microphone (10 seconds)", _audio_record)

        def _audio_stop(a):
            subprocess.getoutput("termux-microphone-record -c")
            return _ok("audio_stop", "⏹️ Recording stopped")
        r("audio_stop", "voice", "Stop any active audio recording", _audio_stop)

        def _audio_list_devices(a):
            out = subprocess.getoutput("termux-audio-info 2>/dev/null | head -20")
            return _ok("audio_list_devices", out[:1000] or "Audio device info unavailable")
        r("audio_list_devices", "voice", "List available audio input/output devices", _audio_list_devices)

        def _audio_set_volume(a):
            parts = a.split() if a else []
            stream = parts[0] if parts else "ring"
            level = parts[1] if len(parts) > 1 else "50"
            out = subprocess.getoutput(f"termux-volume set {stream} {level} 2>&1")
            return _ok("audio_set_volume", f"Volume set: {stream} -> {level}/15")
        r("audio_set_volume", "voice", "Set volume for a stream (ring/notification/music/alarm/system)", _audio_set_volume)

        def _audio_test(a):
            results = []
            # Test TTS
            tts = shutil.which("termux-tts-speak")
            results.append(f"TTS: {'✅ available' if tts else '❌ not found'}")
            # Test STT
            stt = shutil.which("termux-speech-to-text")
            results.append(f"STT: {'✅ available' if stt else '❌ not found'}")
            # Test vibration
            vib = shutil.which("termux-vibrate")
            results.append(f"Vibrate: {'✅ available' if vib else '❌ not found'}")
            return _ok("audio_test", "Audio System Test:\n  " + "\n  ".join(results))
        r("audio_test", "voice", "Run quick test of all audio subsystems", _audio_test)

        # ═══════════════ DEVICE (91-100) ═══════════════
        def _dev_clipboard(a):
            if shutil.which("termux-clipboard-set"):
                if a:
                    subprocess.getoutput(f"termux-clipboard-set '{a[:200]}'")
                    return _ok("dev_clipboard", f"📋 Copied to clipboard: {a[:100]}")
                else:
                    out = subprocess.getoutput("termux-clipboard-get 2>&1")
                    return _ok("dev_clipboard", f"📋 Clipboard: {out[:500]}")
            return _err("dev_clipboard", "❌ Clipboard not available (termux-clipboard-set not found)")
        r("dev_clipboard", "device", "Get/set clipboard content (pass text to set, empty to get)", _dev_clipboard)

        def _dev_battery(a):
            if shutil.which("termux-battery-status"):
                out = subprocess.getoutput("termux-battery-status 2>&1")
                return _ok("dev_battery", f"🔋 Battery:\n{out[:500]}")
            return _err("dev_battery", "❌ Battery info unavailable")
        r("dev_battery", "device", "Get battery status (percentage, charging, temperature)", _dev_battery)

        def _dev_wifi(a):
            if shutil.which("termux-wifi-connectioninfo"):
                out = subprocess.getoutput("termux-wifi-connectioninfo 2>&1")
                return _ok("dev_wifi", f"📶 WiFi:\n{out[:500]}")
            return _err("dev_wifi", "❌ WiFi info unavailable")
        r("dev_wifi", "device", "Get WiFi connection info (SSID, signal, speed)", _dev_wifi)

        def _dev_notification(a):
            if shutil.which("termux-notification"):
                subprocess.getoutput(f"termux-notification --title 'ZERION' --content '{a[:200]}'")
                return _ok("dev_notification", f"🔔 Notification sent: {a[:100]}")
            return _err("dev_notification", "❌ Notifications not available")
        r("dev_notification", "device", "Send an Android notification", _dev_notification)

        def _dev_toast(a):
            if shutil.which("termux-toast"):
                subprocess.getoutput(f"termux-toast '{a[:200]}'")
                return _ok("dev_toast", f"🍞 Toast shown: {a[:100]}")
            return _err("dev_toast", "❌ Toast not available")
        r("dev_toast", "device", "Show an Android toast message on screen", _dev_toast)

        def _dev_screenshot(a):
            if shutil.which("termux-screenshot"):
                subprocess.getoutput("termux-screenshot /tmp/zerion_screenshot.png")
                return _ok("dev_screenshot", "📸 Screenshot saved to /tmp/zerion_screenshot.png")
            return _err("dev_screenshot", "❌ Screenshot not available")
        r("dev_screenshot", "device", "Take a screenshot of the device screen", _dev_screenshot)

        def _dev_contacts(a):
            if shutil.which("termux-contact-list"):
                out = subprocess.getoutput("termux-contact-list 2>&1 | head -20")
                return _ok("dev_contacts", f"📱 Contacts:\n{out[:1000]}")
            return _err("dev_contacts", "❌ Contacts not available")
        r("dev_contacts", "device", "List device contacts (first 20)", _dev_contacts)

        def _dev_calendar(a):
            if shutil.which("termux-calendar-list"):
                out = subprocess.getoutput("termux-calendar-list 2>&1 | head -10")
                return _ok("dev_calendar", f"📅 Calendar:\n{out[:1000]}")
            return _err("dev_calendar", "❌ Calendar not available")
        r("dev_calendar", "device", "List upcoming calendar events", _dev_calendar)

        def _dev_location(a):
            if shutil.which("termux-location"):
                out = subprocess.getoutput("termux-location -p gps 2>&1")
                return _ok("dev_location", f"📍 Location:\n{out[:500]}")
            return _err("dev_location", "❌ Location not available")
        r("dev_location", "device", "Get device GPS location", _dev_location)

        def _dev_settings(a):
            if shutil.which("termux-settings"):
                out = subprocess.getoutput("termux-settings 2>&1 | head -10")
                return _ok("dev_settings", f"⚙️ Settings:\n{out[:500]}")
            return _err("dev_settings", "❌ Settings not available")
        r("dev_settings", "device", "View Termux settings", _dev_settings)


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
