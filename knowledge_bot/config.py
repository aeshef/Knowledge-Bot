import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AppConfig:
    vault_path: Path
    templates_path: Path
    agent_config_path: Path
    export_root: Path
    attachments_root: Path
    telegram_bot_token: Optional[str]
    telegram_user_id: Optional[int]
    telegram_api_base: Optional[str]
    asr_model: Optional[str]
    deepseek_api_key: Optional[str]
    deepseek_base_url: Optional[str]


def load_config() -> AppConfig:
    vault_path = Path(os.environ.get("VAULT_PATH", "/Users/aeshef/Documents/Obsidian Vault")).resolve()
    templates_path_env = os.environ.get("TEMPLATES_PATH")
    templates_path = Path(templates_path_env).resolve() if templates_path_env else (vault_path / "800_Автоматизация" / "Templates" / "Clones")
    agent_config_path_env = os.environ.get("AGENT_CONFIG_PATH")
    agent_config_path = Path(agent_config_path_env).resolve() if agent_config_path_env else (vault_path / "800_Автоматизация" / "Agent" / "config")
    export_root = vault_path / "700_База_Данных" / "Export"
    attachments_root = vault_path / "700_База_Данных" / "_Вложения"
    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_user_id_raw = os.environ.get("TELEGRAM_USER_ID")
    telegram_user_id = int(telegram_user_id_raw) if telegram_user_id_raw and telegram_user_id_raw.isdigit() else None
    telegram_api_base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    asr_model = os.environ.get("ASR_MODEL")
    deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
    deepseek_base_url = os.environ.get("DEEPSEEK_BASE_URL")

    return AppConfig(
        vault_path=vault_path,
        templates_path=templates_path,
        agent_config_path=agent_config_path,
        export_root=export_root,
        attachments_root=attachments_root,
        telegram_bot_token=telegram_bot_token,
        telegram_user_id=telegram_user_id,
        telegram_api_base=telegram_api_base,
        asr_model=asr_model,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=deepseek_base_url,
    )


