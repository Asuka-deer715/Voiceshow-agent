from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPT_DIR = ROOT / "prompts"


def get_prompt(name: str, version: str | None = None) -> tuple[str, str]:
    manifest = json.loads((PROMPT_DIR / "manifest.json").read_text(encoding="utf-8"))
    version = version or os.getenv(f"PROMPT_{name.upper()}_VERSION") or manifest[name]["active"]
    path = PROMPT_DIR / name / f"{version}.md"
    return path.read_text(encoding="utf-8"), f"{name}-{version}"
