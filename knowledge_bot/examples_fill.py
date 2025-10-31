from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_config
from .llm import LLMClient
from .settings import load_prompt, load_types_config, load_enums_config
from .extract import simple_from_text, extract_from_url, extract_from_path
from .routing import route_and_fill


COLUMNS = [
    "id",
    "input_type",
    "input",
    "expected_type",
    "expected_title",
    "expected_tags",
    "expected_fields_json",
    "notes",
]


def detect_bundle(s: str):
    p = Path(s)
    if s.startswith("http://") or s.startswith("https://"):
        return extract_from_url(s)
    if p.exists() and p.is_file():
        return extract_from_path(s)
    return simple_from_text(s)


def fill_row(llm: LLMClient, text: str) -> dict[str, Any]:
    cfg = load_config()
    bundle = detect_bundle(text)
    routed = route_and_fill(llm, bundle.to_summary(), source_hint="examples")
    # naming
    try:
        naming_system = load_prompt(cfg.agent_config_path, "naming")
        named = llm.chat_json(naming_system, json.dumps({"type": routed.get("type"), "title": routed.get("title")}, ensure_ascii=False)).content or {}
        if isinstance(named.get("title"), str) and named["title"].strip():
            routed["title"] = named["title"].strip()
    except Exception:
        pass
    # field fill
    enums_cfg = load_enums_config(cfg.agent_config_path)
    types_cfg = load_types_config(cfg.agent_config_path)
    template_name = types_cfg.template_for(routed["type"])  # not used directly, but asserts type exists
    field_system = load_prompt(cfg.agent_config_path, "field_fill")
    user = {
        "type": routed["type"],
        "allowed_fields": [],  # для примеров не ограничиваем, LLM вернёт минимум
        "summary": bundle.to_summary(),
        "enums": {
            "namespaces_controlled": enums_cfg.namespaces_controlled,
            "common": enums_cfg.common,
            "per_type": enums_cfg.per_type,
        }
    }
    filled = llm.chat_json(field_system, json.dumps(user, ensure_ascii=False)).content or {}
    # collect tags
    tags = routed.get("tags") or []
    result = {
        "expected_type": routed.get("type"),
        "expected_title": routed.get("title"),
        "expected_tags": ",".join(tags) if tags else "",
        "expected_fields_json": json.dumps(filled, ensure_ascii=False) if filled else "",
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill examples xlsx/csv with expected outputs")
    parser.add_argument("input_path", type=Path, nargs="?", default=None, help="Path to examples_template.xlsx or .csv")
    parser.add_argument("--output", type=Path, default=None, help="Output path (.xlsx). Defaults to *_filled.xlsx next to input")
    parser.add_argument("--sheet", type=str, default=None, help="Excel sheet name (if not first)")
    parser.add_argument("--force", action="store_true", help="Fill even if expected_type already present")
    args = parser.parse_args()

    cfg = load_config()
    llm = LLMClient(cfg.deepseek_api_key, cfg.deepseek_base_url)

    in_path = args.input_path or (cfg.agent_config_path / "examples_template.xlsx")
    if not in_path.exists():
        raise FileNotFoundError(f"Input not found: {in_path}")

    if in_path.suffix.lower() == ".csv":
        df = pd.read_csv(in_path)
    else:
        # If sheet not specified, read first sheet explicitly (sheet_name=0)
        if args.sheet is None:
            df = pd.read_excel(in_path, sheet_name=0)
        else:
            df = pd.read_excel(in_path, sheet_name=args.sheet)
        # Guard: if a dict was returned, pick the first sheet
        if isinstance(df, dict):
            first_key = next(iter(df.keys()))
            df = df[first_key]
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""

    processed = 0
    for idx, row in df.iterrows():
        text = str(row.get("input") or "").strip()
        if not text:
            continue
        # only fill missing outputs unless forced
        if not args.force and str(row.get("expected_type") or "").strip():
            continue
        try:
            out = fill_row(llm, text)
            for k, v in out.items():
                df.at[idx, k] = v
            processed += 1
        except Exception as e:
            df.at[idx, "notes"] = f"error: {e}"

    out_path = args.output or (in_path.with_name(in_path.stem + "_filled.xlsx"))
    df.to_excel(out_path, index=False)
    print(f"written: {out_path} | rows processed: {processed} / {len(df)}")


if __name__ == "__main__":
    main()


