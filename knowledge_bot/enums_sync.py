from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import yaml

from .config import load_config


SUGGESTER_RE = re.compile(
    r"const\s+([\wА-Яа-я_]+)\s*=\s*await\s*tp\.system\.suggester\(\s*\[(.*?)\]\s*,\s*\[(.*?)\]\s*\)",
    re.DOTALL,
)

# Match type: "идея" (quote optional)
TYPE_LITERAL_RE = re.compile(r'type:\s*"?([^"\n]+)"?')


def parse_array(src: str) -> List[str]:
    # Try robust parsing using ast; fallback to quoted string regex
    import ast
    try:
        val = ast.literal_eval(f'[{src}]')
        return [str(x).strip() for x in val if isinstance(x, str) and x.strip()]
    except Exception:
        items: List[str] = []
        for m in re.finditer(r'"(.*?)"|\'(.*?)\'', src):
            s = (m.group(1) or m.group(2) or '').strip()
            if s:
                items.append(s)
        return items


def extract_type_name(file_text: str) -> str | None:
    m = TYPE_LITERAL_RE.search(file_text)
    return m.group(1) if m else None


def main() -> None:
    cfg = load_config()
    templates_dir = cfg.vault_path / "800_Автоматизация" / "Templates" / "Сущности"
    files = list(templates_dir.glob("*.md"))
    per_type: Dict[str, Dict[str, List[str]]] = {}
    namespaces_controlled: set[str] = set()

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        type_name = extract_type_name(text) or ""
        local_fields: Dict[str, List[str]] = {}
        for m in SUGGESTER_RE.finditer(text):
            field = m.group(1)
            # ui choices (group 1) ignored; values (group 3) used
            values = parse_array(m.group(3))
            if values:
                local_fields[field] = values
                namespaces_controlled.add(field)
        if local_fields and type_name:
            per_type.setdefault(type_name, {}).update(local_fields)

    enums_path = cfg.agent_config_path / "enums.yaml"
    existing = {}
    if enums_path.exists():
        existing = yaml.safe_load(enums_path.read_text(encoding="utf-8")) or {}

    # Merge with existing
    existing_namespaces = set((existing.get("namespaces", {}) or {}).get("controlled", []))
    merged_namespaces = sorted(existing_namespaces.union(namespaces_controlled))

    common = existing.get("common", {}) or {}
    merged_per_type = existing.get("per_type", {}) or {}
    for t, fields in per_type.items():
        block = merged_per_type.setdefault(t, {})
        for k, vals in fields.items():
            block[k] = sorted(set(vals))

    data = {
        "namespaces": {"controlled": merged_namespaces},
        "common": common,  # keep existing globals
        "per_type": merged_per_type,
    }
    enums_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()


