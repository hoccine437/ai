"""
ZERION-X — GENESIS ∞ Full REST API & Cybernetic Web Server
Exposes all required runtime endpoints and serves the high-fidelity cinematic UI on 0.0.0.0.
"""

import asyncio
from http import HTTPStatus
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from zerion.ui.state_bridge import UIStateBridge, UIStateMode


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
                snap = self.engine.resources.sample()
                ui_dict = self.engine.ui_bridge.current_state.to_dict()
                ui_dict["resource_state"] = {
                    "cpu_percent": snap.cpu_percent,
                    "memory_mb": snap.memory_available_mb,
                    "compute_tier": snap.compute_tier,
                    "is_battery": snap.is_battery_powered
                }
                body = json.dumps(ui_dict).encode("utf-8")
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
                mat = self.engine.maturity_evaluator.evaluate()
                res = {
                    "system_name": self.engine.identity.system_name,
                    "maturity_level": mat.current_level.value,
                    "genome_version": self.engine.genome_manager.current_genome.version,
                    "active_objectives": len(self.engine.continuous_objectives.list_active_objectives()),
                    "active_strategies": len(self.engine.strategy_registry.list_strategies()),
                    "total_capabilities": len(self.engine.self_model._capabilities)
                }
                self._send_response(writer, 200, "application/json", json.dumps(res).encode("utf-8"))

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
                mat = self.engine.maturity_evaluator.evaluate()
                self._send_response(writer, 200, "application/json", json.dumps(mat.to_dict()).encode("utf-8"))

            elif method == "GET" and path == "/api/strategies":
                strats = [s.to_dict() for s in self.engine.strategy_registry.list_strategies()]
                self._send_response(writer, 200, "application/json", json.dumps(strats).encode("utf-8"))

            elif method == "GET" and path == "/api/capabilities":
                caps = self.engine.self_model.what_can_i_do()
                self._send_response(writer, 200, "application/json", json.dumps(caps).encode("utf-8"))

            elif method == "GET" and path == "/api/memory":
                mem = {
                    "episodes_count": len(self.engine.memory._episodes),
                    "procedural_rules": [r.to_dict() for r in self.engine.memory.list_procedural_rules()[:10]]
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
                distilled = self.engine.memory.trigger_distillation()
                self._send_response(writer, 200, "application/json", json.dumps({"new_rules": len(distilled)}).encode("utf-8"))

            elif method == "POST" and path == "/api/mission":
                mis = self.engine.missions.create_mission("Autonomous Genesis Exploration")
                self._send_response(writer, 200, "application/json", json.dumps(mis.to_dict()).encode("utf-8"))

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
