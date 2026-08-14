#!/usr/bin/env python3
"""
ZERION-X — GENESIS & Ω Intelligence Foundry
Standard Setup Configuration
"""

from glob import glob
from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8") if (this_directory / "README.md").exists() else ""

# Ship the Android Compose sources (ui/zerion/*.kt + README.md) in the wheel so
# the mobile host app consumes the exact UI contract. Guarded: builds from
# directories without ui/zerion (e.g. the historical zerion/ copy) stay no-op.
ui_kt_files = sorted(glob("ui/zerion/*.kt") + glob("ui/zerion/*.md"))

setup(
    name="zerion-genesis",
    version="5.0.0",
    description="ZERION-X Ω — Self-Developing Intelligence Runtime & Intelligence Foundry Substrate",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Zerion Autonomous Engineering Collective",
    author_email="dev@zerion.ai",
    url="https://github.com/hoccine437/ai",
    packages=find_packages(include=["zerion", "zerion.*"]),
    include_package_data=True,
    package_data={
        "zerion": [
            "ui/*.html",
            "ui/*.css",
            "ui/*.js"
        ]
    },
    data_files=[("ui/zerion", ui_kt_files)] if ui_kt_files else [],
    python_requires=">=3.9",
    # Pinned exact versions (2026-08-13), synchronized with requirements.txt and
    # pyproject.toml [project].dependencies. Every pin supports Python 3.9.
    # httpx is the only runtime dependency (OpenAIProvider calls the API with
    # raw httpx); the `openai` SDK is intentionally absent — the runtime never
    # imports it, and its jiter dependency has no Termux/Android aarch64 wheel.
    install_requires=[
        "httpx==0.28.1",
    ],
    # Mirrors pyproject.toml [project.optional-dependencies].
    extras_require={
        "local_llm": ["llama-cpp-python==0.3.34"],
        "audio": ["sounddevice==0.5.5", "numpy==2.0.2"],
        "dev": [
            "pytest==8.3.5",
            "pytest-asyncio==1.2.0",
            "ruff==0.16.3",
            "mypy==1.19.1",
        ],
        "all": [
            "httpx==0.28.1",
            "llama-cpp-python==0.3.34",
            "sounddevice==0.5.5",
            "numpy==2.0.2",
            "pytest==8.3.5",
            "pytest-asyncio==1.2.0",
            "ruff==0.16.3",
            "mypy==1.19.1",
        ],
    },
    entry_points={
        "console_scripts": [
            "zerion = zerion.cli:main",
            "genesis = zerion.cli:main",
            "zerion-ui = zerion.ui.server:main"
        ]
    }
)
