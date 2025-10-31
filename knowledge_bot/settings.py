from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class TypesConfig:
    default_template: str
    types: dict[str, dict[str, str]]

    def dir_for(self, type_name: str) -> str:
        entry = self.types.get(type_name)
        return entry.get("dir") if entry else "Знания"

    def template_for(self, type_name: str) -> str:
        entry = self.types.get(type_name)
        return (entry.get("template") if entry else None) or self.default_template


@lru_cache(maxsize=1)
def load_types_config(config_dir: Path) -> TypesConfig:
    cfg_path = config_dir / "types.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return TypesConfig(
        default_template=data.get("default_template", "Знание.j2.md"),
        types=data.get("types", {}),
    )


def load_prompt(config_dir: Path, name: str) -> str:
    p = config_dir / "prompts" / f"{name}.txt"
    return p.read_text(encoding="utf-8")


@dataclass
class EnumsConfig:
    namespaces_controlled: list[str]
    common: dict[str, list[str]]
    per_type: dict[str, dict[str, list[str]]]
    synonyms: dict[str, dict[str, str]]


@lru_cache(maxsize=1)
def load_enums_config(config_dir: Path) -> EnumsConfig:
    p = config_dir / "enums.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return EnumsConfig(
        namespaces_controlled=data.get("namespaces", {}).get("controlled", []),
        common=data.get("common", {}),
        per_type=data.get("per_type", {}),
        synonyms=data.get("synonyms", {}) or data.get("aliases", {}),
    )


