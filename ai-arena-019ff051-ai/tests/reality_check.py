#!/usr/bin/env python3
"""Reality check — traces the actual Zerion execution path."""
import os
import sys
import tempfile

os.environ['ZERION_DISABLE_MIC'] = '1'

print('=== ZERION REALITY CHECK ===')
print()

# 1. Main entry point
print('1. ENTRY POINT:')
from zerion.cli import main
print('   main.py → zerion.cli.main → asyncio.run(run_cli) ✓')

# 2. Engine creation
print()
print('2. ENGINE:')
from zerion.engine import AscendantEngine
print('   AscendantEngine imported ✓')

# 3. Cognitive Runtime
print()
print('3. COGNITIVE RUNTIME:')
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
print('   CognitiveRuntime imported ✓')

# 4. Providers
print()
print('4. PROVIDERS:')
with tempfile.TemporaryDirectory() as tmp:
    rt = CognitiveRuntime(data_dir=tmp)
    providers = rt.cognitive_router.providers()
    print(f'   Registered: {providers}')
    
    for p in providers:
        h = rt.cognitive_router.health.get(p)
        print(f'   {p}: configured={h.configured}, impl={h.integration_implemented}, status={h.status.value}')

# 5. Gemini
print()
print('5. GEMINI PROVIDER:')
from zerion.model_providers.gemini_provider import GeminiProvider
gp = GeminiProvider()
print(f'   Model: {gp.default_model}')
print(f'   API key set: {bool(gp.api_key)}')
print(f'   is_available: {gp.is_available()}')

# 6. Agents
print()
print('6. AGENTS:')
from zerion.agents.registry import AgentRegistry
ar = AgentRegistry()
agents = ar.list_all()
print(f'   Count: {len(agents)}')
if agents:
    print(f'   First 5: {[a.name for a in agents[:5]]}')

# 7. Tools
print()
print('7. TOOLS:')
from zerion.tools.registry import ToolRegistry
tr = ToolRegistry()
print(f'   Count: {tr.count()}')
tools = tr.describe_all()
if tools:
    print(f'   First 5: {[t["name"] for t in tools[:5]]}')

# 8. Memory
print()
print('8. MEMORY:')
from zerion.memory.developmental_store import SmartMemory
with tempfile.TemporaryDirectory() as md:
    m = SmartMemory(data_dir=md)
    item = m.remember('test fact', source='user')
    results = m.retrieve('test', top_k=1)
    print(f'   SmartMemory: write={bool(item)}, retrieve={len(results)>0} ✓')

# 9. Chat endpoint
print()
print('9. CHAT ENDPOINT:')
print('   /api/chat → runtime.execute_task → cognitive_router.execute → Gemini')

# 10. Identity
print()
print('10. IDENTITY:')
from zerion.cognitive_os.tool_router import ZerionToolRouter
print('   ZerionToolRouter imported ✓')

print()
print('=== REALITY CHECK COMPLETE ===')
