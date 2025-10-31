from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Optional
import os
import logging


def _safe_import(name: str):
    try:
        return __import__(name)
    except Exception:
        return None


trafilatura = _safe_import("trafilatura")
pdfminer = _safe_import("pdfminer.high_level")
PIL = _safe_import("PIL")
pytesseract = _safe_import("pytesseract")
requests = _safe_import("requests")
fwhisper = _safe_import("faster_whisper")
owhisper = _safe_import("whisper")
import tempfile
import subprocess


@dataclass
class ExtractedBundle:
    raw_text: str = ""
    urls: list[str] = None
    meta: dict[str, Any] = None
    # derived
    url_text: str = ""
    pdf_text: str = ""
    ocr_text: str = ""
    asr_text: str = ""

    def to_summary(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "urls": self.urls or [],
            "meta": self.meta or {},
            "derived": {
                "url_text": self.url_text,
                "pdf_text": self.pdf_text,
                "ocr_text": self.ocr_text,
                "asr_text": self.asr_text,
            },
        }


def simple_from_text(text: str) -> ExtractedBundle:
    log = logging.getLogger("kb.extract")
    urls: list[str] = []
    for m in re.finditer(r"https?://[^\s)]+", text):
        urls.append(m.group(0))
    url_text = ""
    if urls:
        if trafilatura is None:
            log.info("trafilatura not installed; skip URL extract (urls=%d)", len(urls))
        else:
            try:
                fetched = trafilatura.fetch_url(urls[0])
                url_text = trafilatura.extract(fetched) or ""
                log.info("url_text extracted: len=%d from %s", len(url_text or ""), urls[0])
            except Exception as e:
                log.warning("trafilatura failed: %s", e)
        # Fallback: extract page title via requests if no body text
        if not url_text and requests is not None:
            try:
                resp = requests.get(urls[0], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                html = resp.text or ""
                # Try og:title first
                m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if m:
                    url_text = m.group(1).strip()
                else:
                    # Then <title>
                    m2 = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                    if m2:
                        url_text = re.sub(r"\s+", " ", m2.group(1)).strip()
                log.info("url_title fallback: %s (len=%d)", "yes" if url_text else "no", len(url_text or ""))
            except Exception as e:
                log.warning("requests title fallback failed: %s", e)
    return ExtractedBundle(raw_text=text, urls=urls, meta={}, url_text=url_text)


def extract_from_url(url: str) -> ExtractedBundle:
    log = logging.getLogger("kb.extract")
    txt = ""
    if trafilatura is not None:
        try:
            fetched = trafilatura.fetch_url(url)
            txt = trafilatura.extract(fetched) or ""
            log.info("extract_from_url: len=%d %s", len(txt or ""), url)
        except Exception as e:
            log.warning("extract_from_url failed: %s", e)
    if not txt and requests is not None:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            html = resp.text or ""
            m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if m:
                txt = m.group(1).strip()
            else:
                m2 = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                if m2:
                    txt = re.sub(r"\s+", " ", m2.group(1)).strip()
            log.info("extract_from_url title fallback: len=%d %s", len(txt or ""), url)
        except Exception as e:
            log.warning("requests title fallback failed: %s", e)
    return ExtractedBundle(raw_text=url, urls=[url], meta={}, url_text=txt)


def extract_from_pdf(path: Path) -> str:
    log = logging.getLogger("kb.extract")
    if pdfminer is None:
        log.info("pdfminer not installed; skip PDF extract: %s", path)
        return ""
    try:
        # pdfminer.high_level.extract_text
        txt = pdfminer.high_level.extract_text(str(path)) or ""
        log.info("extract_from_pdf: len=%d %s", len(txt or ""), path)
        return txt
    except Exception as e:
        log.warning("extract_from_pdf failed: %s", e)
        return ""


def extract_from_image(path: Path) -> str:
    log = logging.getLogger("kb.extract")
    if PIL is None or pytesseract is None:
        log.info("Pillow/pytesseract not installed; skip OCR: %s", path)
        return ""
    try:
        img = PIL.Image.open(str(path))
        txt = pytesseract.image_to_string(img) or ""
        log.info("extract_from_image: len=%d %s", len(txt or ""), path)
        return txt
    except Exception as e:
        log.warning("extract_from_image failed: %s", e)
        return ""


def extract_from_path(path_str: str, note_text: Optional[str] = None) -> ExtractedBundle:
    path = Path(path_str)
    if not path.exists():
        return simple_from_text(note_text or path_str)
    suffix = path.suffix.lower()
    raw = note_text or f"[FILE] {str(path)}"
    if suffix in {".pdf"}:
        return ExtractedBundle(raw_text=raw, urls=[], meta={"file": str(path)}, pdf_text=extract_from_pdf(path))
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return ExtractedBundle(raw_text=raw, urls=[], meta={"file": str(path)}, ocr_text=extract_from_image(path))
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".mp4", ".mov", ".mkv"}:
        return ExtractedBundle(raw_text=raw, urls=[], meta={"file": str(path)}, asr_text=transcribe_av(path))
    # other types → just reference path
    return ExtractedBundle(raw_text=raw, urls=[], meta={"file": str(path)})


def _ffmpeg_extract_wav(src: Path) -> Optional[Path]:
    log = logging.getLogger("kb.extract")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        cmd = ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav_path)]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return wav_path
    except Exception as e:
        log.warning("ffmpeg failed: %s", e)
        return None


def transcribe_av(path: Path, model_name: Optional[str] = None) -> str:
    log = logging.getLogger("kb.extract")
    model_name = model_name or os.environ.get("ASR_MODEL", "small")
    asr_lang_env = os.environ.get("ASR_LANGUAGE", "auto").strip()
    # Accept: "auto" or comma-separated preference list like "ru,en"
    prefs = [p.strip() for p in asr_lang_env.split(",") if p.strip()] or ["auto"]
    log.info("ASR start: model=%s lang_pref=%s file=%s", model_name, ",".join(prefs), path)
    # Try HTTP ASR via OpenAI-compatible endpoint (skip for Ollama which lacks /v1/audio/transcriptions)
    if requests is not None:
        try:
            base_url = (
                os.environ.get("ASR_BASE_URL")
                or os.environ.get("OLLAMA_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or os.environ.get("EMBED_ENDPOINT")
            )
            api_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("ASR_API_KEY")
            endpoint_path = os.environ.get("ASR_ENDPOINT", "/v1/audio/transcriptions")
            is_ollama_base = bool(base_url) and ("11434" in base_url or "ollama" in base_url.lower())
            if base_url and api_key and not is_ollama_base:
                url = base_url.rstrip("/") + endpoint_path
                headers = {"Authorization": f"Bearer {api_key}"}
                files = {
                    "file": (path.name, open(path, "rb"), "application/octet-stream"),
                }
                # choose first non-auto language pref if provided
                first_lang = next((p for p in prefs if p != "auto"), None)
                data = {"model": model_name, "response_format": "json"}
                if first_lang:
                    data["language"] = first_lang
                log.info("ASR http: url=%s model=%s", url, model_name)
                resp = requests.post(url, headers=headers, data=data, files=files, timeout=600)
                if resp.status_code == 200:
                    j = resp.json()
                    text = (j.get("text") if isinstance(j, dict) else "") or ""
                    log.info("ASR done (http): len=%d provider=%s", len(text), base_url)
                    if text:
                        try:
                            log.info("ASR(http) text: %s", (text or "").strip()[:500])
                        except Exception:
                            pass
                        return text
                else:
                    log.warning("ASR http failed: %s %s", resp.status_code, resp.text[:200])
            elif is_ollama_base:
                logging.getLogger("kb.extract").info("ASR http skipped: Ollama base detected (%s)", base_url)
        except Exception as e:
            log.warning("ASR http exception: %s", e)
    # Prefer OpenAI Whisper if installed (CPU ok, small model)
    if owhisper is not None:
        try:
            # convert to wav for stability
            wav = _ffmpeg_extract_wav(path) or path
            model = owhisper.load_model(model_name)
            for lang in prefs:
                lang_arg = None if lang == "auto" else lang
                result = model.transcribe(str(wav), language=lang_arg, task="transcribe")
                text = (result or {}).get("text", "")
                log.info("ASR(whisper) try lang=%s → len=%d", lang, len(text or ""))
                if text:
                    try:
                        log.info("ASR(whisper) text: %s", (text or "").strip()[:500])
                    except Exception:
                        pass
                    return text
        except Exception as e:
            log.warning("whisper failed: %s", e)
    # Fallback to faster-whisper
    if fwhisper is not None:
        try:
            model = fwhisper.WhisperModel(model_name, compute_type="int8")
            for lang in prefs:
                lang_arg = None if lang == "auto" else lang
                for vad in (True, False):
                    segments, info = model.transcribe(
                        str(path),
                        language=lang_arg,
                        task="transcribe",
                        vad_filter=vad,
                    )
                    text = " ".join(seg.text.strip() for seg in segments if getattr(seg, "text", "").strip())
                    det_lang = getattr(info, "language", None)
                    det_prob = getattr(info, "language_probability", None)
                    log.info("ASR(fw) try lang=%s vad=%s → len=%d detected=%s p=%.2f", lang, vad, len(text or ""), det_lang, det_prob or -1)
                    if text:
                        try:
                            log.info("ASR(fw) text: %s", (text or "").strip()[:500])
                        except Exception:
                            pass
                        return text
        except Exception as e:
            log.warning("faster_whisper failed: %s", e)
    log.info("ASR unavailable; returning empty for %s", path)
    return ""


