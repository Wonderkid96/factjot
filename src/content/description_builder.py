from __future__ import annotations


def _credit_label(credit: dict[str, str], index: int) -> str:
    provider = str(credit.get("provider", "")).strip()
    name = str(credit.get("name", "")).strip()
    url = str(credit.get("url", "")).strip()
    if name:
        if provider:
            return f"Slide {index}: {name} ({provider})"
        return f"Slide {index}: {name}"
    if provider:
        return f"Slide {index}: {provider}"
    if url:
        return f"Slide {index}: {url}"
    return ""


def build_instagram_description(
    *,
    base_caption: str,
    hashtags: list[str],
    image_credits: list[dict[str, str]] | None = None,
    max_chars: int = 2200,
) -> str:
    caption = base_caption.strip()
    credits = image_credits or []

    credit_lines: list[str] = []
    for idx, credit in enumerate(credits, start=1):
        label = _credit_label(credit, idx)
        if label:
            credit_lines.append(label)

    credit_block = ""
    if credit_lines:
        credit_block = "Photo credits (slide order):\n" + "\n".join(credit_lines)

    hashtag_block = " ".join(hashtags).strip() if hashtags else ""

    parts = [caption]
    if credit_block:
        parts.append(credit_block)
    if hashtag_block:
        parts.append(hashtag_block)
    built = "\n\n".join(p for p in parts if p).strip()
    if len(built) <= max_chars:
        return built

    # Keep hashtag block intact, trim credits first.
    trimmed_credit_lines = list(credit_lines)
    while trimmed_credit_lines:
        maybe_credit_block = "Photo credits (slide order):\n" + "\n".join(trimmed_credit_lines)
        parts = [caption, maybe_credit_block]
        if hashtag_block:
            parts.append(hashtag_block)
        built = "\n\n".join(p for p in parts if p).strip()
        if len(built) <= max_chars:
            return built
        trimmed_credit_lines.pop()

    # If still too long, remove credits and trim caption hard.
    base_parts = [caption]
    if hashtag_block:
        base_parts.append(hashtag_block)
    built = "\n\n".join(p for p in base_parts if p).strip()
    if len(built) <= max_chars:
        return built

    reserve = len(hashtag_block) + (2 if hashtag_block else 0)
    room = max_chars - reserve - 1
    room = max(room, 0)
    trimmed_caption = caption[:room].rstrip()
    if trimmed_caption and len(trimmed_caption) < len(caption):
        trimmed_caption = trimmed_caption.rstrip(".!,;:") + "..."
    final_parts = [trimmed_caption]
    if hashtag_block:
        final_parts.append(hashtag_block)
    return "\n\n".join(p for p in final_parts if p).strip()
