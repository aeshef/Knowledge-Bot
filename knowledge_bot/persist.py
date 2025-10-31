from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from .paths import build_export_path, build_attachments_path, target_note_path
from .slugify import make_slug


def sha256_8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def choose_unique_note_path(vault_root: Path, type_name: str, slug: str) -> Path:
    p = target_note_path(vault_root, type_name, slug)
    if not p.exists():
        return p
    i = 1
    while True:
        candidate = target_note_path(vault_root, type_name, f"{slug}_{i}")
        if not candidate.exists():
            return candidate
        i += 1


def save_raw_file(export_root: Path, filename: str, content: bytes) -> Path:
    h8 = sha256_8(content)
    dst = build_export_path(export_root, filename, h8)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(content)
    return dst


def save_attachments(attachments_root: Path, files: Iterable[tuple[str, bytes]]) -> list[Path]:
    saved: list[Path] = []
    for name, content in files:
        h8 = sha256_8(content)
        dst = build_attachments_path(attachments_root, name, h8)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
        saved.append(dst)
    return saved


def write_note(vault_root: Path, type_name: str, title: str, rendered: str) -> Path:
    base_slug = make_slug(title)
    note_path = choose_unique_note_path(vault_root, type_name, base_slug)
    note_path.write_text(rendered, encoding="utf-8")
    return note_path


