#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════
 ZERION — SINGLE UI MODULE (ui.py)
═══════════════════════════════════════════════════════════════════════

ui.py is THE authoritative Zerion user-interface module: HTTP API routes,
the web UI asset, SSE streaming and voice endpoints all live here.

The UI is a CLIENT of the central runtime created by main2.py:

    main2.py → ZerionRuntime → ui.py → display

It contains NO business logic of its own — no separate router, no separate
memory, no separate provider, no separate agent/tool system. Every route
delegates to `self.runtime.engine` (the one AscendantEngine), and /api/status
reads ONLY the authoritative RuntimeState owned by main2.

`zerion/ui/server.py` remains only as a compatibility shim re-exporting
this module; there is no second UI server.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# The authoritative RuntimeState refresh lives with the state definition.
from zerion.runtime.state import refresh_runtime_state


_UI_ASSET = Path(__file__).parent / "zerion" / "ui" / "index.html"


class ZerionUI:
    """Single-file UI server. A pure client of the ZerionRuntime."""

    def __init__(self, runtime: Any = None, engine: Any = None,
                 host: str = "0.0.0.0", port: int = 8080):
        # Preferred: constructed with the central runtime object.
        if runtime is not None:
            self.runtime = runtime
            self.engine = runtime.engine
        elif engine is not None:
            # Compatibility path (existing tests construct with an engine).
            self.engine = engine
            self.runtime = None
        else:
            raise ValueError("ZerionUI requires a ZerionRuntime (or legacy engine).")
        self.host = host
        self.port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self.html_path = _UI_ASSET

    # ── lifecycle ────────────────────────────────────────────────────────
    async def start(self):
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port)
        print(f"[ZERION UI] Server listening on http://{self.host}:{self.port}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # ── status (ONE source of truth) ─────────────────────────────────────
    def _status_document(self) -> Dict[str, Any]:
        """Read REAL runtime state. When running under main2, this is the
        authoritative RuntimeState; otherwise measured live from the engine."""
        if self.runtime is not None:
            refresh_runtime_state(self.runtime.state, self.engine)
            base = self.runtime.state.to_dict()
        else:
            from zerion.runtime.state import RuntimeState as _RS
            tmp = _RS()
            refresh_runtime_state(tmp, self.engine)
            base = tmp.to_dict()

        # Real developmental metrics (measured, never hard-coded).
        doc: Dict[str, Any] = dict(base)
        try:
            from zerion.runtime.evidence import collect_runtime_evidence
            mat = self.engine.maturity_evaluator.evaluate_from_evidence(
                collect_runtime_evidence(self.engine))
            doc["maturity_level"] = mat.current_level.value
        except Exception as e:  # noqa: BLE001
            doc["maturity_level"] = f"UNKNOWN ({type(e).__name__})"
        try:
            doc["system_name"] = self.engine.identity.system_name
            doc["active_objectives"] = len(
                self.engine.continuous_objectives.list_active_objectives())
            doc["active_strategies"] = len(
                self.engine.strategy_registry.list_strategies())
            doc["genome_version"] = self.engine.genome_manager.current_genome.version
        except Exception:
            pass
        return doc

    # ── request handling ─────────────────────────────────────────────────
    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                return

            req_line = line.decode(errors="replace").strip()
            parts = req_line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, raw_path = parts[0], parts[1]
            parsed_url = urlparse(raw_path)
            path = parsed_url.path

            headers: Dict[str, str] = {}
            content_len = 0
            while True:
                h_line = await reader.readline()
                if not h_line or h_line in (b"\r\n", b"\n"):
                    break
                h_str = h_line.decode(errors="replace").strip()
                if ":" in h_str:
                    k, v = h_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        content_len = int(v.strip())

            body_bytes = b""
            if content_len > 0:
                body_bytes = await reader.readexactly(content_len)

            e = self.engine

            if method == "GET" and path in ("/", "/index.html"):
                with open(self.html_path, "rb") as f:
                    content = f.read()
                self._send_response(writer, 200, "text/html; charset=utf-8", content)

            elif method == "GET" and path == "/api/state":
                body = json.dumps(e.ui_adapter.snapshot()["presentation"]).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/ui-state":
                body = json.dumps(e.ui_adapter.snapshot()).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/events":
                body = json.dumps(e.ui_adapter.event_history(limit=100)).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/stream":
                await self._handle_stream(writer)

            elif method == "POST" and path == "/api/command":
                payload = json.loads(body_bytes.decode(errors="replace") or "{}")
                command = payload.get("command", "")
                cmd_payload = payload.get("payload", {})
                if not isinstance(cmd_payload, dict):
                    cmd_payload = {}
                try:
                    result = await e.command_api.execute(command, cmd_payload)
                    status = 200 if result.get("status") == "OK" else 400
                    body = json.dumps(result).encode("utf-8")
                except Exception as ex:
                    result = {"command": command, "status": "ERROR",
                              "error": f"{type(ex).__name__}: {str(ex)[:300]}"}
                    status = 400
                    body = json.dumps(result).encode("utf-8")
                self._send_response(writer, status, "application/json", body)

            elif method == "GET" and path == "/api/cognitive-state":
                cr = getattr(e, "cognitive_runtime", None)
                if cr is None:
                    self._send_response(writer, 404, "application/json",
                                        b'{"error": "cognitive runtime unavailable"}')
                else:
                    body = json.dumps(cr.snapshot()).encode("utf-8")
                    self._send_response(writer, 200, "application/json", body)

            elif method == "POST" and path == "/api/cycle":
                trace = await e.run_developmental_cycle()
                e.ui_bridge.update_from_cycle(
                    trace_data={
                        "strategy_selected": trace.strategy_selected,
                        "cognitive_allocation_mode": trace.cognitive_allocation_mode,
                        "maturity_level": trace.maturity_level,
                        "anomalies_detected": trace.anomalies_detected,
                        "duration_ms": trace.duration_ms,
                        "learning_acceleration_ratio": trace.learning_acceleration_ratio
                    },
                    engine_ref=e)
                body = json.dumps(e.ui_bridge.current_state.to_dict()).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/status":
                # ONE SOURCE OF TRUTH: the RuntimeState owned by main2.
                body = json.dumps(self._status_document()).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "POST" and path == "/api/chat":
                # ONE CONVERSATION PIPELINE: UI → runtime → context →
                # cognition (Gemini primary) → memory/tools/agents → reply.
                try:
                    payload = json.loads(body_bytes.decode(errors="replace") or "{}")
                    message = payload.get("message", "")
                    if not message:
                        self._send_response(writer, 400, "application/json",
                                            b'{"error": "No message provided"}')
                        return
                    from zerion.cognitive_os.router_types import RoutingMode, Task, TaskType
                    task = Task(
                        type=TaskType.CONVERSATION,
                        description=f"UI chat: {message[:200]}",
                        difficulty=0.3, uncertainty=0.4, novelty=0.3,
                        stakes=0.1, goal_relevance=0.5,
                        required_capabilities=set(),
                        verification_required=False,
                        metadata={"source": "web_ui"},
                    )
                    runtime_core = e.cognitive_runtime
                    result = await runtime_core.execute_task(
                        task, message, mode=RoutingMode.AUTO)
                    output = getattr(result, "output", None)
                    reply = output or f"[{getattr(result.status, 'value', 'ERROR')}] No response generated."
                    md = getattr(result, "metadata", {}) or {}
                    res = {"reply": reply,
                           "status": getattr(result.status, "value", "ERROR"),
                           "provider": getattr(result, "provider", ""),
                           "trace": md.get("trace"),
                           "agent_used": md.get("agent_used"),
                           "tool_used": md.get("tool_used"),
                           "verification": md.get("verification")}
                except Exception as ex:
                    res = {"reply": f"Error: {type(ex).__name__}: {str(ex)[:200]}",
                           "status": "ERROR"}
                self._send_response(writer, 200, "application/json",
                                    json.dumps(res).encode("utf-8"))

            elif method == "GET" and path == "/api/episodes":
                eps = [ep.to_dict() for ep in e.foundry.episode_store.list_episodes()]
                self._send_response(writer, 200, "application/json", json.dumps(eps).encode("utf-8"))

            elif method == "GET" and path == "/api/objectives":
                objs = [o.to_dict() for o in e.continuous_objectives.list_active_objectives()]
                self._send_response(writer, 200, "application/json", json.dumps(objs).encode("utf-8"))

            elif method == "GET" and path == "/api/problems":
                probs = [p.to_dict() for p in e.organism.problems.get_recent_problems()]
                self._send_response(writer, 200, "application/json", json.dumps(probs).encode("utf-8"))

            elif method == "GET" and path == "/api/questions":
                qs = [q.to_dict() for q in e.question_graph.list_questions()[:10]]
                self._send_response(writer, 200, "application/json", json.dumps(qs).encode("utf-8"))

            elif method == "GET" and path == "/api/genome":
                self._send_response(writer, 200, "application/json",
                                    json.dumps(e.genome_manager.current_genome.to_dict()).encode("utf-8"))

            elif method == "GET" and path == "/api/maturity":
                from zerion.runtime.evidence import collect_runtime_evidence
                mat = e.maturity_evaluator.evaluate_from_evidence(
                    collect_runtime_evidence(e))
                self._send_response(writer, 200, "application/json",
                                    json.dumps(mat.to_dict()).encode("utf-8"))

            elif method == "GET" and path == "/api/strategies":
                strats = [s.to_dict() for s in e.strategy_registry.list_strategies()]
                self._send_response(writer, 200, "application/json", json.dumps(strats).encode("utf-8"))

            elif method == "GET" and path == "/api/capabilities":
                caps = e.self_model.what_can_i_do()
                self._send_response(writer, 200, "application/json", json.dumps(caps).encode("utf-8"))

            elif method == "GET" and path == "/api/memory":
                mem = {
                    "episodes_count": e.cognitive_runtime.episode_store.count(),
                    "distilled_count": e.cognitive_runtime.distilled_store.count(),
                    "distilled": [d.to_dict() for d in e.cognitive_runtime.distilled_store.list()[:10]]
                }
                self._send_response(writer, 200, "application/json", json.dumps(mem).encode("utf-8"))

            elif method == "GET" and path == "/api/unknown":
                voids = [v.to_dict() for v in e.unknown_space.get_highest_priority_voids()]
                self._send_response(writer, 200, "application/json", json.dumps(voids).encode("utf-8"))

            elif method == "GET" and path == "/api/architecture":
                cands = [c.to_dict() for c in e.architecture_search.list_candidates()]
                self._send_response(writer, 200, "application/json", json.dumps(cands).encode("utf-8"))

            elif method == "POST" and path == "/api/experiment":
                exp_res = await e.self_experimentation.run_architecture_experiment(
                    hypothesis="Verification depth scaling",
                    target_dimension="verification_ratio",
                    control_val=0.80,
                    treatment_val=0.95)
                self._send_response(writer, 200, "application/json",
                                    json.dumps(exp_res.to_dict()).encode("utf-8"))

            elif method == "POST" and path == "/api/learn":
                from zerion.cognitive_os.episode import EpisodeStatus
                crt = e.cognitive_runtime
                new_rules = 0
                for ep in crt.episode_store.list(status=EpisodeStatus.COMPLETED):
                    produced = crt.experience_distillation.distill_episode(ep)
                    new_rules += len(produced)
                self._send_response(writer, 200, "application/json",
                                    json.dumps({"new_rules": new_rules}).encode("utf-8"))

            elif method == "POST" and path == "/api/mission":
                mis = e.missions.create_mission("Autonomous Genesis Exploration")
                self._send_response(writer, 200, "application/json",
                                    json.dumps(mis.to_dict()).encode("utf-8"))

            # Voice/microphone endpoints removed: Zerion is text-input only.

            elif method == "GET" and path.startswith("/api/level/"):
                lvl_str = path.replace("/api/level/", "")
                try:
                    lvl = int(lvl_str)
                    ans = e.answer_hierarchy_level(lvl)
                    body = json.dumps(ans).encode("utf-8")
                    self._send_response(writer, 200, "application/json", body)
                except ValueError:
                    self._send_response(writer, 400, "application/json",
                                        b'{"error": "Invalid level"}')

            else:
                self._send_response(writer, 404, "application/json", b'{"error": "Not Found"}')

        except Exception as ex:
            try:
                self._send_response(writer, 500, "application/json",
                                    json.dumps({"error": str(ex)}).encode())
            except Exception:
                pass
        finally:
            try:
                await writer.drain()
                writer.close()
            except Exception:
                pass

    async def _handle_stream(self, writer: asyncio.StreamWriter):
        """SSE event stream from the VisualizationStateAdapter."""
        queue = self.engine.ui_adapter.subscribe_stream()
        headers = [
            "HTTP/1.1 200 OK",
            "Content-Type: text/event-stream",
            "Cache-Control: no-cache",
            "Connection: keep-alive",
            "Access-Control-Allow-Origin: *",
            "",
            "",
        ]
        try:
            writer.write("\r\n".join(headers).encode("utf-8"))
            await writer.drain()
            idle_since = time.time()
            while time.time() - idle_since < 600:
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15.0)
                    idle_since = time.time()
                    line = f"data: {json.dumps(record)}\n\n"
                    writer.write(line.encode("utf-8"))
                    await writer.drain()
                except asyncio.TimeoutError:
                    writer.write(b": keep-alive\n\n")
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        except Exception:  # noqa: BLE001 — stream must never kill the server
            pass
        finally:
            self.engine.ui_adapter.unsubscribe_stream(queue)

    def _send_response(self, writer: asyncio.StreamWriter, status_code: int,
                       content_type: str, body: bytes):
        status_text = ("OK" if status_code == 200
                       else ("Not Found" if status_code == 404 else "Internal Error"))
        headers = [
            f"HTTP/1.1 {status_code} {status_text}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Access-Control-Allow-Origin: *",
            "Access-Control-Allow-Methods: GET, POST, OPTIONS",
            "Access-Control-Allow-Headers: Content-Type",
            "Connection: close",
            "",
            ""
        ]
        writer.write("\r\n".join(headers).encode("utf-8") + body)


# Backwards-compatible alias: historical name for the single UI server class.
GenesisWebServer = ZerionUI
