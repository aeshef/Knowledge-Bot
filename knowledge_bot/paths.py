from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import load_config
from .settings import load_types_config


def ensure_dirs(root: Path, *subdirs: str) -> None:
    for sub in subdirs:
        (root / sub).mkdir(parents=True, exist_ok=True)


def now_parts() -> tuple[str, str]:
    dt = datetime.now()
    return dt.strftime("%Y"), dt.strftime("%m")


def build_export_path(export_root: Path, original_name: str, hash8: str) -> Path:
    year, month = now_parts()
    target_dir = export_root / year / month
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{hash8}_{original_name}"


def build_attachments_path(attachments_root: Path, original_name: str, hash8: str) -> Path:
    year, month = now_parts()
    target_dir = attachments_root / year / month
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{hash8}_{original_name}"


def target_note_path(vault_root: Path, type_name: str, slug: str) -> Path:
    cfg = load_config()
    types_cfg = load_types_config(cfg.agent_config_path)
    folder = types_cfg.dir_for(type_name)
    base = vault_root / "700_База_Данных" / folder
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{slug}.md"


