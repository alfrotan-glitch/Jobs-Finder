"""Compatibility view over the maintained Afghanistan source registry.

`docs/source_registry.json` is now the source of truth.  This module preserves
older tests/tools that read `docs/source_inventory.json` by projecting registry
records into the previous inventory shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.source_registry import REGISTRY_PATH, registry_as_inventory


INVENTORY_PATH = Path(__file__).resolve().parent.parent / "docs" / "source_inventory.json"


def inventory_as_dicts() -> list[dict[str, Any]]:
    return registry_as_inventory()


def write_inventory(path: str | Path = INVENTORY_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory_as_dicts(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_inventory(path: str | Path = INVENTORY_PATH) -> list[dict[str, Any]]:
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return inventory_as_dicts()


def registry_path() -> Path:
    return REGISTRY_PATH


if __name__ == "__main__":  # pragma: no cover
    print(write_inventory())
