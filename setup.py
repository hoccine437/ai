#!/usr/bin/env python3
"""
ZERION-X — GENESIS & Ω Intelligence Foundry
Standard Setup Configuration
"""

from setuptools import setup, find_packages
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8") if (this_directory / "README.md").exists() else ""

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
    python_requires=">=3.9",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "zerion = zerion.cli:main",
            "genesis = zerion.cli:main",
            "zerion-ui = zerion.ui.server:main"
        ]
    }
)
