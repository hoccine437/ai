"""
ZERION-X — GENESIS ∞ Full REST API & Cybernetic Web Server
Exposes all required runtime endpoints and serves the high-fidelity cinematic UI on 0.0.0.0.
"""

import asyncio
from http import HTTPStatus
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from zerion.ui.state_bridge import UIStateBridge, UIStateMode
from zerion.runtime.evidence import collect_runtime_evidence
from zerion.cognitive_os.episode import EpisodeStatus


class GenesisWebServer:
    def __init__(self, engine: Any, host: str = "0.0.0.0", port: int = 8080):
        self.engine = engine
        self.host = host
        self.port = port
        self.ui_dir = Path(__file__).parent
        self.html_path = self.ui_dir / "index.html"
        self._server = None

    async def start(self):
        self._server = await asyncio.start_server(self.handle_client, self.host, self.port)
        print(f"[GENESIS UI] Server listening on http://{self.host}:{self.port}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
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

            # Read headers
            headers = {}
            content_len = 0
            while True:
                h_line = await reader.readline()
                if not h_line or h_line == b"\r\n" or h_line == b"\n":
                    break
                h_str = h_line.decode(errors="replace").strip()
                if ":" in h_str:
                    k, v = h_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        content_len = int(v.strip())

            # Read body if present
            body_bytes = b""
            if content_len > 0:
                body_bytes = await reader.readexactly(content_len)

            # Route requests
            if method == "GET" and (path == "/" or path == "/index.html"):
                with open(self.html_path, "rb") as f:
                    content = f.read()
                self._send_response(writer, 200, "text/html; charset=utf-8", content)

            elif method == "GET" and path == "/api/state":
                # Slice 10: the HUD state comes from the REAL runtime via the
                # VisualizationStateAdapter — never presentation defaults.
                body = json.dumps(self.engine.ui_adapter.snapshot()
                                  ["presentation"]).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/ui-state":
                # Slice 10: full read-only real-state snapshot for the UI.
                body = json.dumps(self.engine.ui_adapter.snapshot()).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/events":
                body = json.dumps(self.engine.ui_adapter.event_history(limit=100)).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/stream":
                # Minimal reliable event stream (SSE) over the existing server.
                await self._handle_stream(writer)

            elif method == "POST" and path == "/api/command":
                payload = json.loads(body_bytes.decode(errors="replace") or "{}")
                command = payload.get("command", "")
                cmd_payload = payload.get("payload", {})
                if not isinstance(cmd_payload, dict):
                    cmd_payload = {}
                try:
                    result = await self.engine.command_api.execute(command, cmd_payload)
                    status = 200 if result.get("status") == "OK" else 400
                    body = json.dumps(result).encode("utf-8")
                except Exception as e:
                    result = {"command": command, "status": "ERROR",
                              "error": f"{type(e).__name__}: {str(e)[:300]}"}
                    status = 400
                    body = json.dumps(result).encode("utf-8")
                self._send_response(writer, status, "application/json", body)

            elif method == "GET" and path == "/api/cognitive-state":
                # Slice 1: the authoritative CognitiveState document (perception,
                # attention economy, goal field, resource budget, current focus,
                # last event, schema version) — real runtime state, not presentation defaults.
                cr = getattr(self.engine, "cognitive_runtime", None)
                if cr is None:
                    self._send_response(writer, 404, "application/json", b'{"error": "cognitive runtime unavailable"}')
                else:
                    body = json.dumps(cr.snapshot()).encode("utf-8")
                    self._send_response(writer, 200, "application/json", body)

            elif method == "POST" and path == "/api/cycle":
                trace = await self.engine.run_developmental_cycle()
                self.engine.ui_bridge.update_from_cycle(
                    trace_data={
                        "strategy_selected": trace.strategy_selected,
                        "cognitive_allocation_mode": trace.cognitive_allocation_mode,
                        "maturity_level": trace.maturity_level,
                        "anomalies_detected": trace.anomalies_detected,
                        "duration_ms": trace.duration_ms,
                        "learning_acceleration_ratio": trace.learning_acceleration_ratio
                    },
                    engine_ref=self.engine
                )
                body = json.dumps(self.engine.ui_bridge.current_state.to_dict()).encode("utf-8")
                self._send_response(writer, 200, "application/json", body)

            elif method == "GET" and path == "/api/status":
                mat = self.engine.maturity_evaluator.evaluate_from_evidence(collect_runtime_evidence(self.engine))
                res = {
                    "system_name": self.engine.identity.system_name,
                    "maturity_level": mat.current_level.value,
                    "genome_version": self.engine.genome_manager.current_genome.version,
                    "active_objectives": len(self.engine.continuous_objectives.list_active_objectives()),
                    "active_strategies": len(self.engine.strategy_registry.list_strategies()),
                    "total_capabilities": len(self.engine.self_model._capabilities),
                    "active_episodes": len(self.engine.foundry.episode_store._episodes)
                }
                self._send_response(writer, 200, "application/json", json.dumps(res).encode("utf-8"))

            elif method == "GET" and path == "/api/episodes":
                eps = [e.to_dict() for e in self.engine.foundry.episode_store.list_episodes()]
                self._send_response(writer, 200, "application/json", json.dumps(eps).encode("utf-8"))

            elif method == "GET" and path == "/api/objectives":
                objs = [o.to_dict() for o in self.engine.continuous_objectives.list_active_objectives()]
                self._send_response(writer, 200, "application/json", json.dumps(objs).encode("utf-8"))

            elif method == "GET" and path == "/api/problems":
                probs = [p.to_dict() for p in self.engine.organism.problems.get_recent_problems()]
                self._send_response(writer, 200, "application/json", json.dumps(probs).encode("utf-8"))

            elif method == "GET" and path == "/api/questions":
                qs = [q.to_dict() for q in self.engine.question_graph.list_questions()[:10]]
                self._send_response(writer, 200, "application/json", json.dumps(qs).encode("utf-8"))

            elif method == "GET" and path == "/api/genome":
                self._send_response(writer, 200, "application/json", json.dumps(self.engine.genome_manager.current_genome.to_dict()).encode("utf-8"))

            elif method == "GET" and path == "/api/maturity":
                mat = self.engine.maturity_evaluator.evaluate_from_evidence(collect_runtime_evidence(self.engine))
                self._send_response(writer, 200, "application/json", json.dumps(mat.to_dict()).encode("utf-8"))

            elif method == "GET" and path == "/api/strategies":
                strats = [s.to_dict() for s in self.engine.strategy_registry.list_strategies()]
                self._send_response(writer, 200, "application/json", json.dumps(strats).encode("utf-8"))

            elif method == "GET" and path == "/api/capabilities":
                caps = self.engine.self_model.what_can_i_do()
                self._send_response(writer, 200, "application/json", json.dumps(caps).encode("utf-8"))

            elif method == "GET" and path == "/api/memory":
                # Canonical Slice 4 stores — the legacy DevelopmentalMemoryStore
                # is a deprecated read-only view, never a second write path.
                mem = {
                    "episodes_count": self.engine.cognitive_runtime.episode_store.count(),
                    "distilled_count": self.engine.cognitive_runtime.distilled_store.count(),
                    "distilled": [d.to_dict() for d in self.engine.cognitive_runtime.distilled_store.list()[:10]]
                }
                self._send_response(writer, 200, "application/json", json.dumps(mem).encode("utf-8"))

            elif method == "GET" and path == "/api/unknown":
                voids = [v.to_dict() for v in self.engine.unknown_space.get_highest_priority_voids()]
                self._send_response(writer, 200, "application/json", json.dumps(voids).encode("utf-8"))

            elif method == "GET" and path == "/api/architecture":
                cands = [c.to_dict() for c in self.engine.architecture_search.list_candidates()]
                self._send_response(writer, 200, "application/json", json.dumps(cands).encode("utf-8"))

            elif method == "POST" and path == "/api/experiment":
                exp_res = await self.engine.self_experimentation.run_architecture_experiment(
                    hypothesis="Verification depth scaling",
                    target_dimension="verification_ratio",
                    control_val=0.80,
                    treatment_val=0.95
                )
                self._send_response(writer, 200, "application/json", json.dumps(exp_res.to_dict()).encode("utf-8"))

            elif method == "POST" and path == "/api/learn":
                # Canonical distillation of completed canonical episodes (the
                # same path the CognitivePulse uses) — never the legacy store.
                rt = self.engine.cognitive_runtime
                new_rules = 0
                for ep in rt.episode_store.list(status=EpisodeStatus.COMPLETED):
                    produced = rt.experience_distillation.distill_episode(ep)
                    new_rules += len(produced)
                self._send_response(writer, 200, "application/json",
                                    json.dumps({"new_rules": new_rules}).encode("utf-8"))

            elif method == "POST" and path == "/api/mission":
                mis = self.engine.missions.create_mission("Autonomous Genesis Exploration")
                self._send_response(writer, 200, "application/json", json.dumps(mis.to_dict()).encode("utf-8"))

            elif method == "POST" and path == "/api/voice/process":
                payload = json.loads(body_bytes.decode(errors="replace") or "{}")
                transcript = payload.get("transcript", "")
                turn = await self.engine.voice_pipeline.process_speech_input(transcript)
                res = {
                    "turn_id": turn.turn_id,
                    "wake_detected": turn.wake_result.detected,
                    "matched_phrase": turn.wake_result.matched_phrase,
                    "cleaned_command": turn.wake_result.cleaned_command,
                    "cognitive_response": turn.cognitive_response,
                    "tool_executed": turn.tool_executed,
                    "latency_ms": turn.total_latency_ms
                }
                self._send_response(writer, 200, "application/json", json.dumps(res).encode("utf-8"))

            elif method == "POST" and path == "/api/voice/partial":
                payload = json.loads(body_bytes.decode(errors="replace") or "{}")
                transcript = payload.get("transcript", "")
                await self.engine.voice_pipeline.process_partial_transcript(transcript)
                self._send_response(writer, 200, "application/json", b'{"status": "OK"}')

            elif method == "POST" and path == "/api/voice/audio-rms":
                payload = json.loads(body_bytes.decode(errors="replace") or "{}")
                rms = float(payload.get("rms", 0.0))
                await self.engine.voice_pipeline.handle_audio_frame(rms)
                self._send_response(writer, 200, "application/json", b'{"status": "OK"}')

            elif method == "POST" and path == "/api/voice/interrupt":
                await self.engine.voice_pipeline.interrupt_speech()
                self._send_response(writer, 200, "application/json", b'{"status": "INTERRUPTED"}')

            elif method == "GET" and path == "/api/voice/session":
                sess = self.engine.voice_pipeline.session_mgr.create_ephemeral_session()
                res = {
                    "session_id": sess.session_id,
                    "is_authenticated": sess.is_authenticated,
                    "mode": sess.mode,
                    "expires_at": sess.expires_at
                }
                self._send_response(writer, 200, "application/json", json.dumps(res).encode("utf-8"))

            elif method == "GET" and path.startswith("/api/level/"):
                lvl_str = path.replace("/api/level/", "")
                try:
                    lvl = int(lvl_str)
                    ans = self.engine.answer_hierarchy_level(lvl)
                    body = json.dumps(ans).encode("utf-8")
                    self._send_response(writer, 200, "application/json", body)
                except ValueError:
                    self._send_response(writer, 400, "application/json", b'{"error": "Invalid level"}')

            else:
                self._send_response(writer, 404, "application/json", b'{"error": "Not Found"}')

        except Exception as e:
            try:
                self._send_response(writer, 500, "application/json", json.dumps({"error": str(e)}).encode())
            except Exception:
                pass
        finally:
            try:
                await writer.drain()
                writer.close()
            except Exception:
                pass

    async def _handle_stream(self, writer: asyncio.StreamWriter):
        """SSE event stream from the VisualizationStateAdapter.

        Runs until the client disconnects or a hard idle timeout; bounded
        queue on the adapter side provides backpressure (drop-oldest), so a
        burst of runtime events can never buffer unboundedly here."""
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
                    # Keep-alive comment so proxies / clients know we're alive.
                    writer.write(b": keep-alive\n\n")
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        except Exception:  # noqa: BLE001 — stream must never kill the server
            pass
        finally:
            self.engine.ui_adapter.unsubscribe_stream(queue)

    def _send_response(self, writer: asyncio.StreamWriter, status_code: int, content_type: str, body: bytes):
        status_text = "OK" if status_code == 200 else ("Not Found" if status_code == 404 else "Internal Error")
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


async def run_server(port: int = 8080, data_dir: str = "data"):
    from zerion.engine import AscendantEngine
    engine = AscendantEngine(data_dir=data_dir)
    await engine.start()
    server = GenesisWebServer(engine=engine, host="0.0.0.0", port=port)
    await server.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await server.stop()
        await engine.stop()


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    asyncio.run(run_server(port=port))


if __name__ == "__main__":
    main()
