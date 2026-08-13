"""
Command API — Slice 10.

The ONLY way the UI can request actions from the runtime. Every command is:
1. validated (unknown commands rejected, payload schema enforced)
2. executed through runtime-controlled interfaces (CognitiveRuntime goal APIs,
   CognitivePulse lifecycle, CognitiveRouter, voice pipeline state machine)
3. never allowed to bypass permissions, the SelfModificationGate, tool
   security or system-control policy — no command here touches the gate or
   mutates cognitive internals directly.

All commands return a structured result: {command, status, result, error}.
"""

from typing import Any, Dict, List, Optional


class CommandValidationError(ValueError):
    pass


class CommandAPI:
    def __init__(self, engine: Any):
        self.engine = engine

    # -- registry ----------------------------------------------------------

    async def execute(self, command: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        handler = getattr(self, f"_cmd_{command.lower()}", None)
        if handler is None:
            return {
                "command": command, "status": "VALIDATION_ERROR",
                "error": f"unknown command '{command}' — allowed: "
                         + ", ".join(sorted(self.available_commands()))}
        try:
            result = await handler(payload)
            return {"command": command, "status": "OK", "result": result}
        except CommandValidationError as e:
            return {"command": command, "status": "VALIDATION_ERROR",
                    "error": str(e)}
        except Exception as e:  # noqa: BLE001 — structured errors only
            return {"command": command, "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:300]}"}

    def available_commands(self) -> List[str]:
        return [name[5:].upper() for name in dir(self) if name.startswith("_cmd_")]

    # -- validators --------------------------------------------------------

    @staticmethod
    def _require_text(payload: Dict[str, Any], key: str, min_len: int = 1,
                      max_len: int = 500) -> str:
        val = payload.get(key)
        if not isinstance(val, str) or not val.strip():
            raise CommandValidationError(f"'{key}' must be a non-empty string")
        val = val.strip()
        if len(val) < min_len:
            raise CommandValidationError(
                f"'{key}' must be at least {min_len} characters")
        if len(val) > max_len:
            raise CommandValidationError(
                f"'{key}' must be at most {max_len} characters")
        return val

    @staticmethod
    def _require_enum(payload: Dict[str, Any], key: str,
                      allowed: set, default: Optional[str] = None) -> str:
        val = payload.get(key, default)
        if val is None:
            raise CommandValidationError(f"'{key}' is required")
        val = str(val).upper()
        if val not in allowed:
            raise CommandValidationError(
                f"'{key}' must be one of {sorted(allowed)}, got '{val}'")
        return val

    # -- commands ----------------------------------------------------------

    async def _cmd_start_listening(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pipeline = self.engine.voice_pipeline
        await pipeline.start_listening()
        return {"voice_state": pipeline.state_machine.state.value}

    async def _cmd_stop_listening(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pipeline = self.engine.voice_pipeline
        await pipeline.stop_listening()
        return {"voice_state": pipeline.state_machine.state.value}

    async def _cmd_cancel_operation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pipeline = self.engine.voice_pipeline
        await pipeline.interrupt_speech()
        return {"voice_state": pipeline.state_machine.state.value,
                "interrupted": True}

    async def _cmd_pause_pulse(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pulse = self.engine.cognitive_runtime.cognitive_pulse
        await pulse.pause()
        return {"pulse_state": pulse.state.value}

    async def _cmd_resume_pulse(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pulse = self.engine.cognitive_runtime.cognitive_pulse
        await pulse.resume()
        return {"pulse_state": pulse.state.value}

    async def _cmd_set_offline_mode(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"OFFLINE_ONLY", "ONLINE_ALLOWED", "ONLINE_PREFERRED", "AUTO"}
        mode = self._require_enum(payload, "mode", allowed)
        pulse = self.engine.cognitive_runtime.cognitive_pulse
        pulse.set_offline_mode(mode)
        return {"offline_mode": mode, "pulse_state": pulse.state.value}

    async def _cmd_select_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider = self._require_text(payload, "provider", max_len=64)
        model = self._require_text(payload, "model", max_len=128)
        runtime = self.engine.cognitive_runtime
        router = runtime.cognitive_router
        if provider not in router.providers():
            raise CommandValidationError(
                f"unknown provider '{provider}' — registered: {router.providers()}")
        # Only local models can be actively loaded/unloaded; remote providers
        # are selected per-task by the router (never "loaded").
        info = router._models.get(provider, {}).get(model)
        if info is None:
            raise CommandValidationError(
                f"model '{model}' not registered under provider '{provider}'")
        registry = getattr(self.engine, "local_model_registry", None)
        if provider == "local_gguf" and registry is not None:
            load = registry.load(model)
            return {"provider": provider, "model": model, "load": load,
                    "selection_reason": registry.selection_reason()}
        return {"provider": provider, "model": model,
                "note": "provider selected per-task by CognitiveRouter"}

    async def _cmd_create_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        objective = self._require_text(payload, "objective", max_len=300)
        purpose = payload.get("purpose") or ""
        runtime = self.engine.cognitive_runtime
        goal = await runtime.create_goal(objective, purpose=purpose)
        return {"goal_id": goal.objective_id, "title": goal.title,
                "status": getattr(goal.status, "value", str(goal.status))}

    async def _cmd_pause_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goal_id = self._require_text(payload, "goal_id", max_len=128)
        runtime = self.engine.cognitive_runtime
        goal = await runtime.pause_goal(goal_id)
        return {"goal_id": goal.objective_id,
                "status": getattr(goal.status, "value", str(goal.status))}

    async def _cmd_resume_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goal_id = self._require_text(payload, "goal_id", max_len=128)
        runtime = self.engine.cognitive_runtime
        goal = await runtime.resume_goal(goal_id)
        return {"goal_id": goal.objective_id,
                "status": getattr(goal.status, "value", str(goal.status))}

    async def _cmd_run_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._require_text(payload, "prompt", max_len=2000)
        task_type = self._require_enum(
            payload, "task_type",
            {"REASONING", "CODING", "RETRIEVAL", "CONVERSATION", "PLANNING",
             "TOOL_USE", "ANALYSIS", "ARCHITECTURE", "OTHER"},
            default="REASONING")
        mode = self._require_enum(
            payload, "mode",
            {"OFFLINE_ONLY", "ONLINE_ALLOWED", "ONLINE_PREFERRED", "AUTO"},
            default="AUTO")
        from zerion.cognitive_os.router_types import RoutingMode, Task, TaskType
        runtime = self.engine.cognitive_runtime
        task = Task(
            type=TaskType(task_type),
            description=prompt[:200],
            difficulty=0.4,
            uncertainty=0.4,
            novelty=0.4,
            stakes=0.2,
            goal_relevance=0.5,
            required_capabilities=set(),
            offline_required=(RoutingMode(mode) == RoutingMode.OFFLINE_ONLY),
            verification_required=False,
            metadata={"source": "command_api"},
        )
        result = await runtime.execute_task(task, prompt, mode=RoutingMode(mode))
        return {
            "task_id": task.task_id,
            "status": result.status.value,
            "provider": result.provider,
            "model": result.model,
            "output": result.output,
            "errors": list(result.errors or []),
            "latency_ms": result.latency_ms,
        }
