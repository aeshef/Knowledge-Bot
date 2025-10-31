from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import load_config
from .extract import simple_from_text, extract_from_path, extract_from_url
from .llm import LLMClient
from .render import render_note
from .routing import route_and_fill
from .settings import load_types_config, load_prompt
from .slugify import make_slug


def process_entry(text_or_path: str, llm: LLMClient, output_root: Path | None) -> Path:
    cfg = load_config()
    # detect local file path
    p = Path(text_or_path)
    if str(text_or_path).startswith("http://") or str(text_or_path).startswith("https://"):
        bundle = extract_from_url(str(text_or_path))
    elif p.exists() and p.is_file():
        bundle = extract_from_path(str(p))
    else:
        bundle = simple_from_text(text_or_path)
    routed = route_and_fill(llm, bundle.to_summary(), source_hint="batch")

    # Naming step to compress title
    try:
        naming_system = load_prompt(cfg.agent_config_path, "naming")
        naming_input = json.dumps({"type": routed.get("type"), "title": routed.get("title")}, ensure_ascii=False)
        named = llm.chat_json(naming_system, naming_input).content or {}
        new_title = named.get("title") or routed.get("title")
        if isinstance(new_title, str):
            words = new_title.strip().split()
            if len(words) > 3:
                new_title = " ".join(words[:3])
            routed["title"] = new_title
    except Exception:
        pass

    routed.setdefault("raw_text", raw_text)
    rendered = render_note(cfg.templates_path, routed)

    if output_root is None:
        # write into vault
        types_cfg = load_types_config(cfg.agent_config_path)
        folder = types_cfg.dir_for(routed["type"])
        note_dir = cfg.vault_path / "700_База_Данных" / folder
    else:
        types_cfg = load_types_config(cfg.agent_config_path)
        folder = types_cfg.dir_for(routed["type"])
        note_dir = output_root / folder
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / f"{make_slug(routed['title'])}.md"
    note_path.write_text(rendered, encoding="utf-8")
    return note_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch ingest test for knowledge bot")
    parser.add_argument("input_file", type=Path, help="Text file with one entry per line (text, URL or local path)")
    parser.add_argument("--dry-output", type=Path, default=None, help="If set, write notes under this directory instead of Vault")
    args = parser.parse_args()

    cfg = load_config()
    llm = LLMClient(cfg.deepseek_api_key, cfg.deepseek_base_url)

    lines = [ln.strip() for ln in args.input_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out_paths: list[Path] = []
    for ln in lines:
        out_paths.append(process_entry(ln, llm, args.dry_output))

    print("Created:")
    for p in out_paths:
        print("-", p)


if __name__ == "__main__":
    main()


