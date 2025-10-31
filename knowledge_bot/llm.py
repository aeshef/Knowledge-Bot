from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests
import logging
import re

from .config import load_config
from .settings import load_types_config


@dataclass
class LLMResult:
    content: Any


class LLMClient:
    def __init__(self, api_key: str | None, base_url: str | None):
        self.api_key = api_key
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"

    def chat_json(self, system_prompt: str, user_prompt: str, model: str = "deepseek-chat") -> LLMResult:
        log = logging.getLogger("kb.llm")
        if not self.api_key:
            log.warning("DEEPSEEK_API_KEY missing, using fallback")
            return LLMResult(content=self._fallback(user_prompt))
        try:
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            }
            # Safe request logging
            log.info("LLM request: url=%s model=%s base=%s", url, model, self.base_url)
            log.debug("LLM headers: %s", {"Authorization": "Bearer ***", "Content-Type": headers.get("Content-Type")})
            log.debug("LLM payload keys: %s", list(payload.keys()))
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
            if not resp.ok:
                body_preview = (resp.text or "")[:500]
                log.error("LLM HTTP %s: %s", resp.status_code, body_preview)
                resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            result = json.loads(text)
            # Log shape safely for dict or list
            if isinstance(result, dict):
                log.debug("LLM response JSON keys: %s", list(result.keys()))
            else:
                log.debug("LLM response JSON type: %s", type(result).__name__)
            return LLMResult(content=result)
        except Exception:
            log.exception("LLM call failed, using fallback")
            return LLMResult(content=self._fallback(user_prompt))

    @staticmethod
    def _fallback(user_prompt: str) -> dict[str, Any]:
        # Generic, config-driven minimal fallback (no hardcoded routing heuristics)
        cfg = load_config()
        types_cfg = load_types_config(cfg.agent_config_path)
        default_type = getattr(types_cfg, "default_type", None) or "знание"
        url = LLMClient._extract_first_url(user_prompt)
        form = "link" if url else "text"
        title_src = user_prompt.strip().splitlines()[0] if user_prompt.strip() else "Без названия"
        title = (re.sub(r"\s+", " ", title_src))[:80]
        return {
            "type": default_type,
            "title": title or "Без названия",
            "tags": [],
            "attachments": {"links": [url] if url else [], "files": []},
            "form": form,
        }

    @staticmethod
    def _extract_first_url(text: str) -> str:
        for token in text.split():
            if token.startswith("http://") or token.startswith("https://"):
                return token
        return ""


