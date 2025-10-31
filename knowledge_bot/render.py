from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from .config import load_config
from .settings import load_types_config


def render_note(templates_dir: Path, payload: dict[str, Any]) -> str:
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=select_autoescape([]))
    type_name = payload.get("type", "знание")
    cfg = load_config()
    types_cfg = load_types_config(cfg.agent_config_path)
    template_name = types_cfg.template_for(type_name)
    template = env.get_template(template_name)
    data = {**payload}
    data.setdefault("created", date.today().isoformat())
    data.setdefault("raw_dir", payload.get("raw_dir", ""))
    # Provide safe defaults for nested structures expected by templates
    if data.get("type") == "контакт":
        handles = data.get("handles") or {}
        handles.setdefault("tg", "")
        handles.setdefault("email", "")
        handles.setdefault("phone", "")
        data["handles"] = handles
    content = template.render(**data)
    # Optional images section (embed) and files section (links)
    att = data.get("attachments") or {}
    files = [p for p in (att.get("files") or []) if isinstance(p, str) and p.strip()]
    if files:
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        import os
        imgs = [p for p in files if os.path.splitext(p)[1].lower() in image_exts]
        docs = [p for p in files if p not in imgs]
        if imgs:
            lines_i = ["\n## Изображения\n"]
            for p in imgs:
                lines_i.append(f"![[{p}]]\n")
            content = f"{content}\n{''.join(lines_i)}"
        if docs:
            lines_f = ["\n## Файлы\n"]
            for p in docs:
                name = p.split("/")[-1]
                lines_f.append(f"- [[{p}|{name}]]\n")
            content = f"{content}\n{''.join(lines_f)}"
    # Optional links section with anchors and plain links fallback
    links_anchors = data.get("links_anchors") or []
    extra_links = []
    for u in (att.get("links") or []):
        if isinstance(u, str) and u.strip():
            extra_links.append(u)
    if isinstance(links_anchors, list) and (links_anchors or extra_links):
        lines = ["\n## Ссылки\n"]
        seen = set()
        for item in links_anchors:
            url = (item.get("url") if isinstance(item, dict) else None) or ""
            text = (item.get("text") if isinstance(item, dict) else None) or url
            if text and url and url not in seen:
                lines.append(f"- [{text}]({url})\n")
                seen.add(url)
        for url in extra_links:
            if url not in seen:
                lines.append(f"- {url}\n")
                seen.add(url)
        if len(lines) > 1:
            content = f"{content}\n{''.join(lines)}"
    raw_text = (data.get("raw_text") or "").strip()
    if raw_text:
        content = f"{content}\n\n## Исходный текст\n\n{raw_text}\n"
    # ASR summary and transcript sections (optional)
    asr_summary = (data.get("asr_summary") or "").strip()
    if asr_summary:
        content = f"{content}\n\n## Сводка (ASR)\n\n{asr_summary}\n"
    asr_text = (data.get("asr_text") or "").strip()
    if asr_text:
        content = f"{content}\n\n## Транскрипция\n\n{asr_text}\n"
    # Remove placeholder line for raw_dir (redundant regardless of presence)
    lines = content.splitlines()
    lines = [ln for ln in lines if not ln.strip().startswith("- Исходные файлы:")]
    content = "\n".join(lines)
    return content


