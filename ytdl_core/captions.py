from urllib.parse import parse_qs, urlparse


def is_hebrew_lang(lang: str) -> bool:
    return lang.startswith("he") or lang == "iw"


def is_english_lang(lang: str) -> bool:
    return lang.startswith("en")


def is_translated_caption_format(fmt: dict) -> bool:
    url = fmt.get("url") or ""
    if url:
        query = parse_qs(urlparse(url).query)
        if "tlang" in query:
            return True

    text_fields = " ".join(str(fmt.get(key, "")) for key in ("name", "format", "format_note"))
    return "auto-translated" in text_fields.lower()


def has_original_caption_format(formats: list) -> bool:
    if not formats:
        return False
    return any(not is_translated_caption_format(fmt) for fmt in formats)


def choose_lang_from_map(caption_map: dict, predicate, original_only: bool = False):
    for lang in sorted(caption_map.keys()):
        if predicate(lang) and (not original_only or has_original_caption_format(caption_map.get(lang) or [])):
            return lang
    return None


def build_subs_config(selected_lang: str | None, source: str | None) -> dict:
    if not selected_lang or not source:
        return {"writesubtitles": False, "writeautomaticsub": False}

    return {
        "writesubtitles": source == "manual",
        "writeautomaticsub": source == "auto",
        "subtitleslangs": [selected_lang],
        "subtitlesformat": "best",
    }


def has_subtitles_enabled(subs_config: dict) -> bool:
    return bool(subs_config.get("writesubtitles") or subs_config.get("writeautomaticsub"))


def get_best_subs_config(info: dict, want_subs: bool = True) -> dict:
    if not want_subs:
        return {"writesubtitles": False, "writeautomaticsub": False}

    subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}
    original_auto_subs = {
        lang: formats
        for lang, formats in auto_subs.items()
        if has_original_caption_format(formats or [])
    }
    translated_auto_langs = set(auto_subs.keys()) - set(original_auto_subs.keys())
    
    if not subs and not original_auto_subs:
        print("   (No subtitles found)")
        return {"writesubtitles": False, "writeautomaticsub": False}

    selected_lang = None
    selected_source = None
    
    # 1. Prefer real Hebrew subtitles over auto-translated Hebrew.
    selected_lang = choose_lang_from_map(subs, is_hebrew_lang)
    if selected_lang:
        selected_source = "manual"
        print(f"   (Found manual Hebrew subtitles: {selected_lang})")

    if not selected_lang:
        selected_lang = choose_lang_from_map(original_auto_subs, is_hebrew_lang, original_only=True)
        if selected_lang:
            selected_source = "auto"
            print(f"   (Found original Hebrew automatic subtitles: {selected_lang})")

    # 2. Then prefer English, because many videos expose fake translated iw entries.
    if not selected_lang:
        selected_lang = choose_lang_from_map(subs, is_english_lang)
        if selected_lang:
            selected_source = "manual"
            print(f"   (Found manual English subtitles: {selected_lang})")

    if not selected_lang:
        selected_lang = choose_lang_from_map(original_auto_subs, is_english_lang, original_only=True)
        if selected_lang:
            selected_source = "auto"
            print(f"   (Found original English automatic subtitles: {selected_lang})")
    
    # 3. Other real/manual or original automatic captions.
    if not selected_lang:
        selected_lang = sorted(subs.keys())[0] if subs else None
        if selected_lang:
            selected_source = "manual"
            print(f"   (Fallback manual subtitle language: {selected_lang})")

    if not selected_lang and original_auto_subs:
        selected_lang = sorted(original_auto_subs.keys())[0]
        selected_source = "auto"
        print(f"   (Fallback original automatic subtitle language: {selected_lang})")

    if not selected_lang:
        if translated_auto_langs:
            print(f"   (Only auto-translated subtitles found; skipping: {', '.join(sorted(translated_auto_langs)[:5])})")
        return {"writesubtitles": False, "writeautomaticsub": False}
    
    return build_subs_config(selected_lang, selected_source)
