from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import load_config
from .extract import simple_from_text, extract_from_path
from .schema import allowed_fields_for_type
from .settings import load_prompt, load_enums_config
from .llm import LLMClient
from .persist import write_note, save_raw_file
from .render import render_note
from .routing import route_and_fill
from .logging_setup import init_logging
import logging
import requests
import json


_PENDING: dict[int, dict[str, Any]] = {}


def _preview_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="💾 Сохранить", callback_data="save")
    kb.button(text="🏷 Тип", callback_data="type")
    kb.button(text="✖️ Отмена", callback_data="cancel")
    kb.adjust(3)
    return kb


async def handle_message(message: Message) -> None:
    log = logging.getLogger("kb.bot")
    cfg = load_config()
    if cfg.telegram_user_id and message.from_user and message.from_user.id != cfg.telegram_user_id:
        await message.answer("⛔️ Доступ запрещён")
        return

    text = message.text or message.caption or ""
    if text.strip().startswith('/'):
        await message.answer("Я принимаю текст/ссылки/медиа и предлагаю сохранить как заметку.")
        return
    log.info("Incoming message len=%d", len(text))
    bundle = simple_from_text(text)

    llm = LLMClient(cfg.deepseek_api_key, cfg.deepseek_base_url)
    summary_obj = bundle.to_summary()
    routed = route_and_fill(llm, summary_obj, source_hint="telegram")
    log.info("Routed type=%s title=%s", routed.get("type"), routed.get("title"))
    # If there is a Telegram document, download and save to Export, link from note
    try:
        doc = getattr(message, "document", None)
        if doc and cfg.telegram_bot_token:
            file = await message.bot.get_file(doc.file_id)
            file_path = getattr(file, "file_path", None)
            if file_path:
                url = f"{cfg.telegram_api_base}/file/bot{cfg.telegram_bot_token}/{file_path}"
                resp = requests.get(url, timeout=120)
                resp.raise_for_status()
                content = resp.content
                name = doc.file_name or file_path.split("/")[-1]
                saved = save_raw_file(cfg.export_root, name, content)
                log.info("Saved document: %s (%d bytes)", saved, len(content))
                if not isinstance(routed.get("attachments"), dict):
                    routed["attachments"] = {"links": [], "files": []}
                routed["attachments"].setdefault("links", [])
                routed["attachments"].setdefault("files", [])
                try:
                    rel = saved.relative_to(cfg.vault_path)
                    routed["attachments"]["files"].append(str(rel))
                    routed["raw_dir"] = str(rel.parent)
                except Exception:
                    routed["attachments"]["files"].append(str(saved))
                    routed["raw_dir"] = str(saved.parent)
                routed["form"] = "file"
                routed.setdefault("filenames", []).append(name)
                # enrich summary with derived text (pdf)
                try:
                    derived = extract_from_path(str(saved))
                    if derived.pdf_text:
                        summary_obj["derived"]["pdf_text"] = derived.pdf_text
                except Exception as ee:
                    log.warning("pdf extract failed: %s", ee)
    except Exception as e:
        log.warning("failed to download/save document: %s", e)
        # provide filename hint if present
        try:
            doc = getattr(message, "document", None)
            if doc and getattr(doc, "file_name", None):
                routed.setdefault("filenames", []).append(doc.file_name)
                routed.setdefault("form", "file")
        except Exception:
            pass
    # If there is a Telegram photo, download best size and save to Export; embed later in render
    try:
        photos = getattr(message, "photo", None)
        if photos and cfg.telegram_bot_token:
            best = photos[-1]
            file = await message.bot.get_file(best.file_id)
            file_path = getattr(file, "file_path", None)
            if file_path:
                url = f"{cfg.telegram_api_base}/file/bot{cfg.telegram_bot_token}/{file_path}"
                resp = requests.get(url, timeout=120)
                resp.raise_for_status()
                content = resp.content
                # Derive a filename
                name = file_path.split("/")[-1]
                saved = save_raw_file(cfg.export_root, name, content)
                log.info("Saved photo: %s (%d bytes)", saved, len(content))
                if not isinstance(routed.get("attachments"), dict):
                    routed["attachments"] = {"links": [], "files": []}
                routed["attachments"].setdefault("links", [])
                routed["attachments"].setdefault("files", [])
                try:
                    rel = saved.relative_to(cfg.vault_path)
                    routed["attachments"]["files"].append(str(rel))
                    routed["raw_dir"] = str(rel.parent)
                except Exception:
                    routed["attachments"]["files"].append(str(saved))
                    routed["raw_dir"] = str(saved.parent)
                # keep form as-is; photo is supplementary
                try:
                    derived = extract_from_path(str(saved))
                    if derived.ocr_text:
                        summary_obj["derived"]["ocr_text"] = derived.ocr_text
                except Exception as ee:
                    log.warning("ocr extract failed: %s", ee)
    except Exception as e:
        log.warning("failed to download/save photo: %s", e)
    # If there is a Telegram video, download, save to Export and run ASR
    try:
        vid = getattr(message, "video", None) or getattr(message, "video_note", None)
        if vid and cfg.telegram_bot_token:
            file = await message.bot.get_file(vid.file_id)
            file_path = getattr(file, "file_path", None)
            if file_path:
                url = f"{cfg.telegram_api_base}/file/bot{cfg.telegram_bot_token}/{file_path}"
                resp = requests.get(url, timeout=600)
                resp.raise_for_status()
                content = resp.content
                name = (getattr(vid, "file_name", None) or file_path.split("/")[-1])
                saved = save_raw_file(cfg.export_root, name, content)
                log.info("Saved video: %s (%d bytes)", saved, len(content))
                if not isinstance(routed.get("attachments"), dict):
                    routed["attachments"] = {"links": [], "files": []}
                routed["attachments"].setdefault("links", [])
                routed["attachments"].setdefault("files", [])
                try:
                    rel = saved.relative_to(cfg.vault_path)
                    routed["attachments"]["files"].append(str(rel))
                    routed["raw_dir"] = str(rel.parent)
                except Exception:
                    routed["attachments"]["files"].append(str(saved))
                    routed["raw_dir"] = str(saved.parent)
                routed["form"] = "video"
                routed.setdefault("filenames", []).append(name)
                try:
                    log.info("ASR begin for %s", saved)
                    derived = await asyncio.to_thread(extract_from_path, str(saved))
                    if derived.asr_text:
                        summary_obj["derived"]["asr_text"] = derived.asr_text
                        log.info("ASR captured len=%d", len(derived.asr_text))
                        try:
                            log.info("ASR text: %s", (derived.asr_text or "").strip()[:500])
                        except Exception:
                            pass
                        # Re-route based on ASR text (content-driven)
                        try:
                            rerouted = route_and_fill(llm, summary_obj, source_hint="telegram")
                            # Merge existing attachments/files/filenames/raw_dir/form
                            rerouted.setdefault("attachments", {"links": [], "files": []})
                            routed.setdefault("attachments", {"links": [], "files": []})
                            # union links
                            old_links = set(routed["attachments"].get("links", []) or [])
                            new_links = set(rerouted["attachments"].get("links", []) or [])
                            rerouted["attachments"]["links"] = sorted(old_links | new_links)
                            # concat files preserving order
                            old_files = routed["attachments"].get("files", []) or []
                            new_files = rerouted["attachments"].get("files", []) or []
                            rerouted["attachments"]["files"] = new_files + [f for f in old_files if f not in new_files]
                            # preserve filenames/raw_dir/form
                            if routed.get("filenames"):
                                rerouted.setdefault("filenames", []).extend([n for n in routed["filenames"] if n not in (rerouted.get("filenames") or [])])
                            if routed.get("raw_dir"):
                                rerouted["raw_dir"] = routed["raw_dir"]
                            if routed.get("form"):
                                rerouted["form"] = routed["form"]
                            routed = rerouted
                        except Exception as re_err:
                            log.warning("reroute after ASR failed: %s", re_err)
                        # Summarize ASR for readable note section
                        try:
                            asr_system = load_prompt(cfg.agent_config_path, "asr_summary")
                            asr_user = {"asr_text": derived.asr_text, "type": routed.get("type")}
                            asr_resp = llm.chat_json(asr_system, json.dumps(asr_user, ensure_ascii=False)).content or {}
                            if isinstance(asr_resp, dict) and isinstance(asr_resp.get("asr_summary"), str):
                                routed["asr_summary"] = asr_resp["asr_summary"].strip()
                        except Exception as sum_err:
                            log.warning("ASR summarize failed: %s", sum_err)
                        # Also include raw transcript in payload for render
                        routed["asr_text"] = derived.asr_text
                    else:
                        log.info("ASR returned empty text")
                except Exception as ee:
                    log.warning("asr extract failed: %s", ee)
    except Exception as e:
        log.warning("failed to download/save video: %s", e)
    # Naming: use summary context for robust 2–3 word title
    try:
        naming_system = load_prompt(cfg.agent_config_path, "naming")
        naming_input = json.dumps({
            "type": routed.get("type"),
            "summary": summary_obj,
            "filenames": routed.get("filenames", []),
            "hint_title": routed.get("title")
        }, ensure_ascii=False)
        named = llm.chat_json(naming_system, naming_input).content or {}
        if isinstance(named.get("title"), str) and named["title"].strip():
            routed["title"] = named["title"].strip()
    except Exception:
        pass
    routed.setdefault("title", "Без названия")
    routed.setdefault("created", date.today().isoformat())
    # keep original raw text for insertion to note body
    routed.setdefault("raw_text", bundle.raw_text)
    # merge extracted URLs into attachments.links and capture Telegram entities with anchors
    try:
        import re
        def _normalize_url(u: str) -> str:
            return u.strip().strip(".,);]\'")

        links = set()
        anchors: dict[str, str] = {}
        # from routed (if any)
        for u in (routed.get("attachments", {}).get("links", []) or []):
            if isinstance(u, str) and u.startswith(("http://", "https://")):
                links.add(_normalize_url(u))
        # regex over raw text
        for m in re.finditer(r"https?://[^\s)]+", bundle.raw_text or ""):
            links.add(_normalize_url(m.group(0)))
        # telegram entities (text or caption)
        ents = message.entities if message.text is not None else message.caption_entities
        txt = message.text if message.text is not None else (message.caption or "")
        if ents:
            for ent in ents:
                start = getattr(ent, "offset", 0)
                length = getattr(ent, "length", 0)
                piece = (txt or "")[start:start+length]
                url_val = getattr(ent, "url", None) or piece
                if isinstance(url_val, str) and url_val.startswith(("http://", "https://")):
                    nurl = _normalize_url(url_val)
                    links.add(nurl)
                    anchor_text = piece.strip()
                    if anchor_text and anchor_text != url_val:
                        anchors.setdefault(nurl, anchor_text)
        routed.setdefault("attachments", {"links": [], "files": []})
        routed["attachments"]["links"] = sorted(links)
        if anchors:
            routed["links_anchors"] = [{"url": u, "text": anchors[u]} for u in sorted(anchors.keys())]
    except Exception:
        pass
    # Field fill: restrict to template fields
    try:
        enums_cfg = load_enums_config(cfg.agent_config_path)
        allowed_fields = allowed_fields_for_type(routed["type"]) or []
        field_system = load_prompt(cfg.agent_config_path, "field_fill")
        user = {
            "type": routed["type"],
            "allowed_fields": allowed_fields,
            "summary": summary_obj,
            "filenames": routed.get("filenames", []),
            "enums": {
                "namespaces_controlled": enums_cfg.namespaces_controlled,
                "common": enums_cfg.common,
                "per_type": enums_cfg.per_type,
            }
        }
        filled = llm.chat_json(field_system, json.dumps(user, ensure_ascii=False)).content or {}
        for k in allowed_fields:
            if k in filled:
                routed[k] = filled[k]
    except Exception as e:
        log.warning("field_fill failed: %s", e)

    # Tags step: generate from type, summary, attachments, enums, and filled fields
    try:
        enums_cfg = load_enums_config(cfg.agent_config_path)
        tags_system = load_prompt(cfg.agent_config_path, "tags")
        # Collect fields that were filled and may impact tags
        fields_for_tags = {}
        for k, v in routed.items():
            if k not in {"type", "title", "created", "tags", "attachments", "source", "form", "raw_text", "raw_dir"}:
                fields_for_tags[k] = v
        tags_user = {
            "type": routed.get("type"),
            "summary": summary_obj,
            "attachments": {"links": routed.get("attachments", {}).get("links", [])},
            "enums": {
                "namespaces_controlled": enums_cfg.namespaces_controlled,
                "common": enums_cfg.common,
                "per_type": enums_cfg.per_type,
            },
            "synonyms": enums_cfg.synonyms,
            "filenames": routed.get("filenames", []),
            "fields": fields_for_tags,
        }
        tag_resp = llm.chat_json(tags_system, json.dumps(tags_user, ensure_ascii=False)).content or []
        # Normalize to list of strings
        if isinstance(tag_resp, dict) and "tags" in tag_resp:
            tag_candidates = tag_resp.get("tags") or []
        else:
            tag_candidates = tag_resp if isinstance(tag_resp, list) else []
        # Normalize tags to all-English ASCII slugs (free namespaces), lower-case namespaces
        def _translit_ru(s: str) -> str:
            table = str.maketrans({
                "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"i",
                "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
                "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"shch","ы":"y","э":"e","ю":"yu","я":"ya",
                "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"e","Ж":"zh","З":"z","И":"i","Й":"i",
                "К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f",
                "Х":"h","Ц":"c","Ч":"ch","Ш":"sh","Щ":"shch","Ы":"y","Э":"e","Ю":"yu","Я":"ya",
            })
            return s.translate(table)

        def _slug_ascii(s: str) -> str:
            import re
            s = _translit_ru(s)
            s = s.lower()
            s = s.replace(" ", "-").replace("_", "-")
            s = re.sub(r"[^a-z0-9\-/]", "", s)
            s = re.sub(r"-+", "-", s).strip("-")
            return s

        tag_values = []
        for tag in tag_candidates:
            if isinstance(tag, str) and "/" in tag:
                ns, _, val = tag.strip().partition("/")
                ns = (ns or "").strip().lower()
                raw_val = (val or "").strip()
                # apply synonyms if provided for namespace (exact match, case-insensitive)
                syn_map = getattr(enums_cfg, "synonyms", {}).get(ns, {}) if 'enums_cfg' in locals() else {}
                mapped = syn_map.get(raw_val.lower())
                if mapped:
                    raw_val = mapped
                # candidate ascii slug
                cand_slug = _slug_ascii(raw_val)
                # if namespace is controlled (per config), try to map to allowed canonical values
                per_type_enums = enums_cfg.per_type.get(routed.get("type", ""), {})
                allowed_list = (enums_cfg.common.get(ns) or per_type_enums.get(ns)) or []
                is_controlled = ns in enums_cfg.namespaces_controlled
                if is_controlled and allowed_list:
                    # pick allowed value whose slug matches candidate
                    chosen = None
                    for allowed_val in allowed_list:
                        if _slug_ascii(str(allowed_val)) == cand_slug:
                            chosen = allowed_val
                            break
                    if chosen:
                        tag_values.append(f"{ns}/{chosen}")
                    else:
                        # no good match -> skip to avoid non-canonical values
                        continue
                else:
                    # free namespace
                    if ns and cand_slug:
                        tag_values.append(f"{ns}/{cand_slug}")
        # Filter controlled namespaces against enums
        filtered = []
        per_type_enums = enums_cfg.per_type.get(routed.get("type", ""), {})
        for tag in tag_values:
            ns, _, value = tag.partition("/")
            if ns in enums_cfg.namespaces_controlled:
                allowed = enums_cfg.common.get(ns) or per_type_enums.get(ns)
                if allowed and value in allowed:
                    filtered.append(tag)
            else:
                filtered.append(tag)
        routed["tags"] = sorted(dict.fromkeys(filtered))
    except Exception as e:
        logging.getLogger("kb.bot").warning("tags generation failed: %s", e)
        routed.setdefault("tags", [])

    rendered = render_note(cfg.templates_path, routed)
    _PENDING[message.from_user.id] = {"payload": routed, "rendered": rendered, "summary": summary_obj}
    folder_hint = Path(cfg.vault_path / "700_База_Данных")
    await message.answer(
        f"Готово к сохранению — тип: {routed['type']}\n" \
        f"Название: {routed['title']}",
        reply_markup=_preview_keyboard().as_markup(),
    )


async def main() -> None:
    init_logging()
    logging.getLogger("kb").info("Bot starting")
    cfg = load_config()
    if not cfg.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    bot = Bot(cfg.telegram_bot_token)
    dp = Dispatcher()
    dp.message.register(handle_message, F.text)
    dp.message.register(handle_message, F.caption)
    # Also handle media-only updates
    dp.message.register(handle_message, F.document)
    dp.message.register(handle_message, F.photo)
    dp.message.register(handle_message, F.video)
    dp.message.register(handle_message, F.video_note)
    dp.message.register(handle_message, F.audio)
    dp.message.register(handle_message, F.voice)

    async def on_cancel(cb: CallbackQuery):
        _PENDING.pop(cb.from_user.id, None)
        await cb.message.edit_text("Отменено.")
        await cb.answer()

    async def on_save(cb: CallbackQuery):
        cfg_l = load_config()
        st = _PENDING.pop(cb.from_user.id, None)
        if not st:
            await cb.answer("Нет данных", show_alert=True)
            return
        payload = st["payload"]
        rendered = st["rendered"]
        note_path = write_note(cfg_l.vault_path, payload["type"], payload["title"], rendered)
        logging.getLogger("kb.bot").info("Written note: %s", note_path)
        await cb.message.edit_text(f"✅ Создано: {note_path.relative_to(cfg_l.vault_path)}\nТип: {payload['type']}")
        await cb.answer()

    async def on_type_menu(cb: CallbackQuery):
        # Paginated type list (6 per page), with emojis
        from .settings import load_types_config
        cfg_l = load_config()
        types_cfg = load_types_config(cfg_l.agent_config_path)
        keys = list(types_cfg.types.keys())
        page = 0
        per_page = 6
        start = page * per_page
        slice_keys = keys[start:start+per_page]
        kb = InlineKeyboardBuilder()
        for k in slice_keys:
            kb.button(text=f"🔖 {k}", callback_data=f"set_type:{k}")
        # nav
        if start > 0:
            kb.button(text="◀️", callback_data=f"types:{page-1}")
        if start + per_page < len(keys):
            kb.button(text="▶️", callback_data=f"types:{page+1}")
        kb.button(text="🔙 Назад", callback_data="back")
        kb.adjust(3)
        await cb.message.edit_text("Выбрать тип (страница 1):", reply_markup=kb.as_markup())
        await cb.answer()

    async def on_set_type(cb: CallbackQuery):
        st = _PENDING.get(cb.from_user.id)
        if not st:
            await cb.answer("Нет данных", show_alert=True)
            return
        new_type = cb.data.split(":", 1)[1]
        st["payload"]["type"] = new_type
        cfg_l = load_config()
        llm_l = LLMClient(cfg_l.deepseek_api_key, cfg_l.deepseek_base_url)
        summary_l = st.get("summary")
        # Re-run naming for the new type
        try:
            naming_system = load_prompt(cfg_l.agent_config_path, "naming")
            naming_input = json.dumps({
                "type": new_type,
                "summary": summary_l,
                "filenames": st["payload"].get("filenames", []),
                "hint_title": st["payload"].get("title")
            }, ensure_ascii=False)
            named = llm_l.chat_json(naming_system, naming_input).content or {}
            if isinstance(named.get("title"), str) and named["title"].strip():
                st["payload"]["title"] = named["title"].strip()
        except Exception:
            pass
        # Re-run field_fill with restricted fields
        try:
            enums_cfg = load_enums_config(cfg_l.agent_config_path)
            allowed_fields = allowed_fields_for_type(new_type) or []
            field_system = load_prompt(cfg_l.agent_config_path, "field_fill")
            user = {
                "type": new_type,
                "allowed_fields": allowed_fields,
                "summary": summary_l,
                "filenames": st["payload"].get("filenames", []),
                "enums": {
                    "namespaces_controlled": enums_cfg.namespaces_controlled,
                    "common": enums_cfg.common,
                    "per_type": enums_cfg.per_type,
                }
            }
            filled = llm_l.chat_json(field_system, json.dumps(user, ensure_ascii=False)).content or {}
            for k in allowed_fields:
                if k in filled:
                    st["payload"][k] = filled[k]
        except Exception:
            pass
        # Re-run tags
        try:
            enums_cfg = load_enums_config(cfg_l.agent_config_path)
            tags_system = load_prompt(cfg_l.agent_config_path, "tags")
            fields_for_tags = {}
            for k, v in st["payload"].items():
                if k not in {"type", "title", "created", "tags", "attachments", "source", "form", "raw_text", "raw_dir"}:
                    fields_for_tags[k] = v
            tags_user = {
                "type": new_type,
                "summary": summary_l,
                "attachments": {"links": st["payload"].get("attachments", {}).get("links", [])},
                "enums": {
                    "namespaces_controlled": enums_cfg.namespaces_controlled,
                    "common": enums_cfg.common,
                    "per_type": enums_cfg.per_type,
                },
                "synonyms": enums_cfg.synonyms,
                "filenames": st["payload"].get("filenames", []),
                "fields": fields_for_tags,
            }
            tag_resp = llm_l.chat_json(tags_system, json.dumps(tags_user, ensure_ascii=False)).content or []
            tag_candidates = tag_resp.get("tags") if isinstance(tag_resp, dict) else (tag_resp if isinstance(tag_resp, list) else [])
            # Normalize as in main flow
            def _translit_ru(s: str) -> str:
                table = str.maketrans({
                    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"i",
                    "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
                    "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"shch","ы":"y","э":"e","ю":"yu","я":"ya",
                    "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"e","Ж":"zh","З":"z","И":"i","Й":"i",
                    "К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f",
                    "Х":"h","Ц":"c","Ч":"ch","Ш":"sh","Щ":"shch","Ы":"y","Э":"e","Ю":"yu","Я":"ya",
                })
                return s.translate(table)
            def _slug_ascii(s: str) -> str:
                import re
                s = _translit_ru(s).lower().replace(" ", "-").replace("_", "-")
                s = re.sub(r"[^a-z0-9\-/]", "", s)
                s = re.sub(r"-+", "-", s).strip("-")
                return s
            tag_values = []
            for tag in (tag_candidates or []):
                if isinstance(tag, str) and "/" in tag:
                    ns, _, val = tag.strip().partition("/")
                    ns = (ns or "").strip().lower()
                    raw_val = (val or "").strip()
                    syn_map = getattr(enums_cfg, "synonyms", {}).get(ns, {})
                    mapped = syn_map.get(raw_val.lower())
                    if mapped:
                        raw_val = mapped
                    val = _slug_ascii(raw_val)
                    if ns and val:
                        tag_values.append(f"{ns}/{val}")
            filtered = []
            per_type_enums = enums_cfg.per_type.get(new_type, {})
            for tag in tag_values:
                ns, _, value = tag.partition("/")
                if ns in enums_cfg.namespaces_controlled:
                    allowed = enums_cfg.common.get(ns) or per_type_enums.get(ns)
                    if allowed and value in allowed:
                        filtered.append(tag)
                else:
                    filtered.append(tag)
            st["payload"]["tags"] = sorted(dict.fromkeys(filtered))
        except Exception:
            pass
        st["rendered"] = render_note(cfg_l.templates_path, st["payload"])
        await cb.message.edit_text(
            f"Готово к сохранению — тип: {new_type}\nНазвание: {st['payload']['title']}",
            reply_markup=_preview_keyboard().as_markup(),
        )
        await cb.answer("Тип обновлён")

    async def on_back(cb: CallbackQuery):
        st = _PENDING.get(cb.from_user.id)
        if not st:
            await cb.answer()
            return
        await cb.message.edit_text(
            f"Готово к сохранению — тип: {st['payload']['type']}\nНазвание: {st['payload']['title']}",
            reply_markup=_preview_keyboard().as_markup(),
        )
        await cb.answer()
    
    async def on_types_page(cb: CallbackQuery):
        from .settings import load_types_config
        cfg_l = load_config()
        types_cfg = load_types_config(cfg_l.agent_config_path)
        keys = list(types_cfg.types.keys())
        try:
            page = int(cb.data.split(":", 1)[1])
        except Exception:
            page = 0
        per_page = 6
        total_pages = (len(keys) + per_page - 1) // per_page
        page = max(0, min(page, max(0, total_pages - 1)))
        start = page * per_page
        slice_keys = keys[start:start+per_page]
        kb = InlineKeyboardBuilder()
        for k in slice_keys:
            kb.button(text=f"🔖 {k}", callback_data=f"set_type:{k}")
        if page > 0:
            kb.button(text="◀️", callback_data=f"types:{page-1}")
        if page + 1 < total_pages:
            kb.button(text="▶️", callback_data=f"types:{page+1}")
        kb.button(text="🔙 Назад", callback_data="back")
        kb.adjust(3)
        await cb.message.edit_text(f"Выбрать тип (страница {page+1}/{total_pages}):", reply_markup=kb.as_markup())
        await cb.answer()
    # Register callbacks with filters explicitly
    dp.callback_query.register(on_cancel, F.data == "cancel")
    dp.callback_query.register(on_save, F.data == "save")
    dp.callback_query.register(on_type_menu, F.data == "type")
    dp.callback_query.register(on_set_type, F.data.startswith("set_type:"))
    dp.callback_query.register(on_types_page, F.data.startswith("types:"))
    dp.callback_query.register(on_back, F.data == "back")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


