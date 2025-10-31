from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .llm import LLMClient
from .config import load_config
from .settings import load_prompt, load_types_config, load_enums_config


def route_and_fill(
    llm: LLMClient,
    extracted_summary: dict[str, Any],
    source_hint: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    system_prompt = load_prompt(cfg.agent_config_path, "routing")
    types_cfg = load_types_config(cfg.agent_config_path)
    enums_cfg = load_enums_config(cfg.agent_config_path)
    allowed_types = list(types_cfg.types.keys())
    user = json.dumps({
        "summary": extracted_summary,
        "source": source_hint,
        "allowed_types": allowed_types,
        "enums": {
            "namespaces_controlled": enums_cfg.namespaces_controlled,
            "common": enums_cfg.common,
            "per_type": enums_cfg.per_type,
        }
    }, ensure_ascii=False)
    result = llm.chat_json(system_prompt, user)
    payload = result.content or {}
    # Ensure minimal fields
    payload.setdefault("type", types_cfg.types.keys().__iter__().__next__() if allowed_types else "знание")
    payload.setdefault("title", "Без названия")
    # Теги: принимаем из LLM, но позже отфильтруем контролируемые по enums
    payload.setdefault("tags", [])
    payload.setdefault("attachments", {"links": [], "files": []})
    payload.setdefault("form", "text")
    payload.setdefault("source", source_hint or "")
    payload.setdefault("created", date.today().isoformat())
    # Enforce allowed type set
    if payload.get("type") not in allowed_types:
        payload["type"] = getattr(types_cfg, "default_type", None) or "знание"
    # Validate enumerated fields and tags
    t = payload["type"]
    per_type_enums = enums_cfg.per_type.get(t, {})
    # clamp fields like status/priority/category if present
    for field, choices in {**enums_cfg.common, **per_type_enums}.items():
        if field in payload and isinstance(payload[field], str):
            val = payload[field]
            if val not in choices:
                payload[field] = choices[0] if choices else val
    # filter tags
    tags = payload.get("tags") or []
    filtered = []
    for tag in tags:
        if not isinstance(tag, str) or "/" not in tag:
            continue
        ns, _, value = tag.partition("/")
        if ns in enums_cfg.namespaces_controlled:
            allowed = enums_cfg.common.get(ns) or per_type_enums.get(ns)
            if allowed and value in allowed:
                filtered.append(tag)
        else:
            filtered.append(tag)
    payload["tags"] = filtered
    return payload


