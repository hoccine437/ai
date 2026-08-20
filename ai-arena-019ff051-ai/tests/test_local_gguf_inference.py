"""
Local GGUF inference tests — real backend chain, honest fallbacks.

Covers the corrected ``LocalGGUFProvider``
(``zerion/model_providers/gemini_provider.py``):

- model discovery is recursive and validates the GGUF magic header;
- selection is deterministic (explicit model_id wins, else smallest valid);
- generation is ``REAL_MODEL_RESPONSE`` when a backend runs (llama.cpp CLI via
  a fake binary on PATH; llama-cpp-python via an injected stub module);
- generation is an honest ``FALLBACK_RESPONSE`` naming the missing piece when
  no backend exists — never fabricated model text;
- the cognitive_os adapter maps real output to success and fallbacks to a
  structured ``MODEL_LOAD_FAILURE``.

Hermetic: no real model files or llama.cpp binaries are required.
"""

import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

from zerion.cognitive_os.gguf_discovery import resolve_models_dir
from zerion.cognitive_os.provider_adapters import LegacyGGUFAdapter
from zerion.cognitive_os.provider_interface import ProviderCall, ProviderFailureKind
from zerion.cognitive_os.router_types import Task
from zerion.model_providers.gemini_provider import LocalGGUFProvider
from zerion.model_providers.provider import ModelResponse
from zerion.runtime.evidence import ExecutionMode

_GGUF_ENV_KEYS = (
    "ZERION_GGUF_BACKEND",
    "ZERION_GGUF_THREADS",
    "ZERION_GGUF_CONTEXT",
    "ZERION_GGUF_MAX_TOKENS",
    "ZERION_GGUF_TEMPERATURE",
    "ZERION_GGUF_TIMEOUT_SECONDS",
)


def _write_fake_gguf(path: Path, size: int = 64) -> None:
    """A GGUF that passes the discovery magic check (header + padding)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"GGUF")
        f.write(b"\x00" * max(0, size - 4))


class LocalGGUFProviderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zerion_gguf_")
        self.models_dir = os.path.join(self._tmp, "models")
        os.makedirs(self.models_dir, exist_ok=True)
        self._saved_env = dict(os.environ)
        for key in _GGUF_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _provider(self, backend: str = "auto") -> LocalGGUFProvider:
        return LocalGGUFProvider(models_dir=self.models_dir, backend=backend)

    @staticmethod
    def _no_backend(p: LocalGGUFProvider) -> LocalGGUFProvider:
        """Force the 'no inference backend installed' condition hermetically."""
        p._has_python_backend = lambda: False
        p._find_cli = lambda: None
        return p

    # -- honest fallbacks ---------------------------------------------------

    def test_no_model_file_returns_honest_fallback(self):
        p = self._no_backend(self._provider())
        self.assertFalse(p.is_available())
        resp = asyncio.run(p.generate_response("hello"))
        self.assertEqual(resp.execution_mode, ExecutionMode.FALLBACK_RESPONSE)
        self.assertTrue(resp.is_fallback)
        self.assertIn("FALLBACK", resp.content)
        self.assertIn("no valid .gguf model", p.last_error)

    def test_model_file_without_backend_returns_honest_fallback(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        p = self._no_backend(self._provider())
        self.assertTrue(p.is_available())
        resp = asyncio.run(p.generate_response("hello"))
        self.assertEqual(resp.execution_mode, ExecutionMode.FALLBACK_RESPONSE)
        self.assertTrue(resp.is_fallback)
        self.assertIn("no local GGUF inference backend", p.last_error)
        self.assertNotIn("model_a", resp.content)  # never pretends to be the model

    def test_backend_none_disables_even_with_model(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        os.environ["ZERION_GGUF_BACKEND"] = "none"
        p = self._provider()
        resp = asyncio.run(p.generate_response("hello"))
        self.assertEqual(resp.execution_mode, ExecutionMode.FALLBACK_RESPONSE)
        self.assertIn("disabled", p.last_error)

    # -- discovery & selection ----------------------------------------------

    def test_is_available_is_recursive(self):
        _write_fake_gguf(Path(self.models_dir) / "sub" / "nested.gguf")
        p = self._provider()
        self.assertTrue(p.is_available())

    def test_selection_prefers_smallest_valid_model(self):
        _write_fake_gguf(Path(self.models_dir) / "big.gguf", size=4096)
        _write_fake_gguf(Path(self.models_dir) / "small.gguf", size=64)
        p = self._provider()
        info = p._select_model()
        self.assertIsNotNone(info)
        self.assertEqual(info.model_id, "small")

    def test_selection_honors_explicit_model_id(self):
        _write_fake_gguf(Path(self.models_dir) / "big.gguf", size=4096)
        _write_fake_gguf(Path(self.models_dir) / "small.gguf", size=64)
        p = self._provider()
        info = p._select_model("big")
        self.assertEqual(info.model_id, "big")

    def test_corrupted_file_is_not_available(self):
        (Path(self.models_dir) / "bad.gguf").write_bytes(b"NOPE" + b"\x00" * 60)
        p = self._provider()
        self.assertFalse(p.is_available())

    # -- CLI backend (the Termux path) --------------------------------------

    def _fake_cli(self, body: str) -> str:
        bin_dir = os.path.join(self._tmp, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        script = os.path.join(bin_dir, "llama-cli")
        with open(script, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(script, 0o755)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        return script

    def test_cli_backend_produces_real_response(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        log_path = os.path.join(self._tmp, "args.log")
        self._fake_cli(
            f'echo "$@" > "{log_path}"\n'
            "printf 'Local response text</s>trailing junk'\n")
        os.environ["ZERION_GGUF_BACKEND"] = "cli"
        p = self._provider()
        resp = asyncio.run(p.generate_response("Say something", model_id="model_a"))
        self.assertEqual(resp.execution_mode, ExecutionMode.REAL_MODEL_RESPONSE)
        self.assertFalse(resp.is_fallback)
        self.assertEqual(resp.content, "Local response text")
        self.assertEqual(resp.model_id, "model_a")
        with open(log_path) as f:
            args = f.read()
        self.assertIn("-m", args)
        self.assertIn("model_a.gguf", args)
        self.assertIn("Say something", args)

    def test_cli_backend_failure_returns_fallback(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli("echo 'boom' >&2\nexit 3\n")
        os.environ["ZERION_GGUF_BACKEND"] = "cli"
        p = self._provider()
        resp = asyncio.run(p.generate_response("hello"))
        self.assertEqual(resp.execution_mode, ExecutionMode.FALLBACK_RESPONSE)
        self.assertIn("llama.cpp CLI failed", p.last_error)
        self.assertIn("exit 3", p.last_error)

    # -- python backend (llama-cpp-python) ----------------------------------

    def test_python_backend_produces_real_response_with_usage(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        fake = types.ModuleType("llama_cpp")

        class _FakeLlama:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def create_completion(self, prompt, **kwargs):
                return {
                    "choices": [{"text": "Stub answer<|im_end|>extra"}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                }

        fake.Llama = _FakeLlama
        sys.modules["llama_cpp"] = fake
        self.addCleanup(sys.modules.pop, "llama_cpp", None)
        os.environ["ZERION_GGUF_BACKEND"] = "python"
        p = self._provider()
        p._has_python_backend = lambda: True  # the injected module is not on disk
        resp = asyncio.run(p.generate_response("hello", model_id="model_a"))
        self.assertEqual(resp.execution_mode, ExecutionMode.REAL_MODEL_RESPONSE)
        self.assertFalse(resp.is_fallback)
        self.assertEqual(resp.content, "Stub answer")
        self.assertEqual(resp.prompt_tokens, 7)
        self.assertEqual(resp.completion_tokens, 3)


class LegacyGGUFAdapterTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zerion_gguf_adapter_")
        self.models_dir = os.path.join(self._tmp, "models")
        os.makedirs(self.models_dir, exist_ok=True)
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._saved_env = dict(os.environ)
        for key in _GGUF_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_adapter_maps_fallback_to_structured_failure(self):
        provider = LocalGGUFProvider(models_dir=self.models_dir, backend="none")
        adapter = LegacyGGUFAdapter(models_dir=self.models_dir,
                                    provider=provider)
        call = ProviderCall(task=Task(), prompt="hello", model_id="model_a")
        resp = asyncio.run(adapter.generate(call))
        self.assertFalse(resp.success)
        self.assertIsNone(resp.output)
        self.assertEqual(resp.failure_kind, ProviderFailureKind.MODEL_LOAD_FAILURE)
        self.assertIn("local_gguf", resp.error)

    def test_adapter_passes_through_real_generation(self):
        class _StubLegacy:
            async def generate_response(self, prompt, model_id=None, **kwargs):
                return ModelResponse(
                    provider_name="local_gguf", model_id="model_a",
                    content="real local text",
                    execution_mode=ExecutionMode.REAL_MODEL_RESPONSE,
                    prompt_tokens=3, completion_tokens=4)

        adapter = LegacyGGUFAdapter(models_dir=self.models_dir,
                                    provider=_StubLegacy())
        call = ProviderCall(task=Task(), prompt="hello", model_id="model_a")
        resp = asyncio.run(adapter.generate(call))
        self.assertTrue(resp.success)
        self.assertEqual(resp.output, "real local text")
        self.assertEqual(resp.usage["prompt_tokens"], 3)
        self.assertEqual(resp.usage["completion_tokens"], 4)


class ResolveModelsDirTestCase(unittest.TestCase):
    """Model-directory resolution: env override -> <project root>/models
    (the canonical repo folder) -> runtime default. Explicit paths are never
    hijacked."""

    def setUp(self):
        self._root = Path(tempfile.mkdtemp(prefix="zerion_resolve_"))
        self._base = self._root / "runtime"
        self._base.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._root, ignore_errors=True)

    def test_env_var_wins_over_everything(self):
        env_dir = str(self._root / "custom_models")
        os.makedirs(env_dir, exist_ok=True)
        with mock.patch.dict(os.environ,
                             {"ZERION_MODELS_DIR": env_dir}):
            resolved = resolve_models_dir("models", base=self._base)
        self.assertEqual(resolved, env_dir)

    def test_canonical_repo_models_folder_wins(self):
        # The repository ships <project root>/models as the canonical local
        # model folder; with the default "models" it is auto-detected even
        # when the CWD is elsewhere.
        repo_root = Path(__file__).resolve().parents[1]
        with mock.patch.dict(os.environ, {"ZERION_MODELS_DIR": ""}):
            resolved = resolve_models_dir("models")
        self.assertEqual(Path(resolved), (repo_root / "models").resolve())

    def test_models_next_to_base_wins(self):
        # ``base`` stands in for the project root: models living directly
        # inside it are found when the caller uses the default "models".
        inside = self._base / "models"
        inside.mkdir(parents=True, exist_ok=True)
        resolved = resolve_models_dir("models", base=self._base)
        self.assertEqual(Path(resolved), inside.resolve())

    def test_falls_back_to_runtime_default(self):
        self.assertEqual(resolve_models_dir("models", base=self._base),
                         "models")

    def test_explicit_non_default_path_passes_through(self):
        # Even when the repo models folder exists, an explicit path is never
        # auto-routed anywhere else.
        explicit = str(self._root / "elsewhere" / "models")
        self.assertEqual(resolve_models_dir(explicit, base=self._base),
                         explicit)

    def test_provider_default_resolves_models_dir_via_env(self):
        env_dir = os.path.join(self._root, "env_models")
        os.makedirs(env_dir, exist_ok=True)
        _write_fake_gguf(Path(env_dir) / "env_model.gguf")
        with mock.patch.dict(os.environ,
                             {"ZERION_MODELS_DIR": env_dir}):
            provider = LocalGGUFProvider()  # default models_dir="models"
        self.assertTrue(provider.is_available())
        self.assertEqual(provider.backend_info()["models_dir"], env_dir)


if __name__ == "__main__":
    unittest.main()
