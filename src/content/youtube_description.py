"""Build a Shorts-shaped YouTube description (Phase F: YouTube divergence).

Per the YouTube-as-revenue principle and the Q7 audit decision, YouTube
gets its own purpose-built description rather than a verbatim copy of
the Instagram caption. The Shorts description is shorter, search-tuned,
and uses clickable URLs (not just publisher names) so YouTube's
description links act as outbound source citations.

Output shape (in order):

    Line 1-2 -- punchy hook re-statement, 1-2 sentences max.
    Blank line.
    Up to 3 source URLs, each on its own line (full URLs, clickable).
    Blank line.
    Exactly 5 hashtags: 1 broad + 3 niche + #Shorts (always last).

Voice rules from `/Users/Music/.claude/CLAUDE.md` and `CLAUDE.md` apply:
no em-dashes, British English, no clickbait shapes ("you won't believe",
"mind-blowing", "this changed everything", "did you know"). The prompt
explicitly bans those shapes; a regex post-check strips obvious
leftovers and warns.

Calls the local `claude` CLI (Sonnet, via `src.core.claude_cli`) -- not
the Anthropic API. Soft-fall ladder (every infra issue is non-fatal --
worst case YouTube gets a deterministic description rather than failing
the upload): any failure inside `call_claude_cli` (CLI missing, error,
timeout, malformed output) -> deterministic fallback. Model returned
only banned phrases or lost its required shape -> deterministic fallback.
"""
from __future__ import annotations

import re

from src.content.voice_normaliser import normalise
from src.core.claude_cli import call_claude_cli


_MODEL = "sonnet"

# Clickbait shapes that the prompt bans. Post-check stripper logs a
# warning but does not crash; the soft-fall covers the case when the
# resulting string is empty or has lost its shape.
_CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\byou\s+won'?t\s+believe\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blown\b", re.IGNORECASE),
    re.compile(r"\bmind[\s-]?blowing\b", re.IGNORECASE),
    re.compile(r"\bthis\s+changed\s+everything\b", re.IGNORECASE),
    re.compile(r"\bdid\s+you\s+know\b", re.IGNORECASE),
    re.compile(r"\bunbelievable\b", re.IGNORECASE),
    re.compile(r"\bshocking\s+truth\b", re.IGNORECASE),
    re.compile(r"\bwait\s+until\s+you\s+see\b", re.IGNORECASE),
)


def _strip_clickbait(text: str) -> tuple[str, list[str]]:
    """Remove clickbait phrases, return (cleaned, hits).

    Hits are returned so the caller can log a warning that the model ignored
    the rule. The fallback path activates when the cleaned text loses
    its required structure (no hashtags, etc.).
    """
    cleaned = text
    hits: list[str] = []
    for pat in _CLICKBAIT_PATTERNS:
        m = pat.search(cleaned)
        if m:
            hits.append(m.group(0))
            cleaned = pat.sub("", cleaned)
    # Collapse double-spaces within lines that the substitution left.
    cleaned = "\n".join(re.sub(r"  +", " ", line) for line in cleaned.split("\n"))
    return cleaned, hits


def _first_two_sentences(claim: str) -> str:
    """Return the first one or two sentences of `claim`, no more."""
    if not claim:
        return ""
    sentences = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+", claim.strip()) if s.strip()
    ]
    if not sentences:
        return claim.strip()
    return " ".join(sentences[:2])


def _deterministic_fallback(
    reel_title: str,
    claim: str,
    sources: list[str],
    topic: str,
    reason: str = "",
) -> str:
    """Return a Shorts-shaped description without calling the CLI.

    Used whenever the model call cannot run or returns garbage. Shape
    mirrors the model target: hook, sources, 5 hashtags ending in
    `#Shorts`. Keeps the YouTube upload path live even when the local
    CLI is unavailable. `reason` is logged (grep 'FALLBACK reason=') so a
    quiet rise in soft-falls is visible rather than silently shipping
    generic hashtags.
    """
    if reason:
        print(f"  [yt-desc] FALLBACK reason={reason}", flush=True)
    hook = (reel_title or "").strip().rstrip(".")
    body = _first_two_sentences(claim)

    head_lines: list[str] = []
    if hook:
        head_lines.append(hook + ".")
    if body and body.lower() != hook.lower():
        head_lines.append(body)
    head = "\n".join(head_lines).strip() or (claim or "").strip()

    src_lines: list[str] = []
    for url in (sources or [])[:3]:
        url = (url or "").strip()
        if url and url.startswith(("http://", "https://")):
            src_lines.append(url)
    src_block = "\n".join(src_lines)

    topic_tag = re.sub(r"[^A-Za-z0-9]+", "", (topic or "facts").lower()) or "facts"
    hashtags = f"#factjot #{topic_tag} #facts #learning #Shorts"

    parts: list[str] = []
    if head:
        parts.append(head)
    if src_block:
        parts.append("")
        parts.append(src_block)
    parts.append("")
    parts.append(hashtags)

    return normalise("\n".join(parts).strip())


def _has_minimum_shape(text: str) -> bool:
    """True if `text` looks like a Shorts description (some hashtags, ends with #Shorts).

    Used as a sanity gate after the model returns: if the response has no
    hashtags or doesn't include `#Shorts`, treat it as malformed and
    fall back. This guards against models that ignore the format spec.
    """
    if not text or not text.strip():
        return False
    hashtags = re.findall(r"#[A-Za-z0-9_]+", text)
    if not hashtags:
        return False
    return any(h.lower() == "#shorts" for h in hashtags)


def _build_prompt(
    reel_title: str,
    claim: str,
    sources: list[str],
    topic: str,
) -> str:
    """Compose the description-writer prompt sent to the model."""
    sources_block = "\n".join(
        f"- {u}" for u in (sources or [])[:3] if u and isinstance(u, str)
    ) or "(no sources provided)"
    return (
        "Write a YouTube Shorts description for a factjot reel.\n\n"
        f"Reel title: \"{reel_title.strip()}\"\n"
        f"Claim: \"{claim.strip()}\"\n"
        f"Sources:\n{sources_block}\n"
        f"Topic: {topic.strip() or 'facts'}\n\n"
        "Rules:\n"
        "1. LINE 1 is the most important. It appears in search results and "
        "as the collapsed preview. Start it with the specific subject or "
        "fact (keyword-first, not filler words like 'A video about...'). "
        "Keep it under 100 characters. Make it a complete, punchy sentence "
        "that works standalone.\n"
        "2. LINE 2 (optional): one short sentence that adds context or "
        "sharpens the claim. Skip it if line 1 is already complete.\n"
        "3. Blank line.\n"
        "4. Up to 3 source URLs (full clickable URLs only, one per line). "
        "If fewer than 3 sources are provided, list only what exists.\n"
        "5. Blank line.\n"
        "6. Exactly 5 hashtags on one line. Order: 2 topic-specific terms "
        "with real search volume, 1 subject-specific term, 1 broad (#facts "
        "or #history or similar), then #Shorts last. No generic spam tags.\n\n"
        "Voice:\n"
        "- British English. Short sentences. Active voice.\n"
        "- No em-dashes. No exclamation marks.\n"
        "- No clickbait: no 'you won't believe', 'mind-blowing', "
        "'this changed everything', 'did you know', 'shocking truth'.\n"
        "- Tone: confident and direct, as if stating a verified fact to a "
        "curious adult. Not breathless, not academic.\n\n"
        "Return the description text only. No preamble, no commentary."
    )


def build_shorts_description(
    reel_title: str,
    claim: str,
    sources: list[str] | None,
    topic: str,
) -> str:
    """Return a Shorts-shaped description for the YouTube upload.

    Parameters
    ----------
    reel_title
        The curated/auto reel title used as the hook frame on Instagram.
    claim
        The full fact claim. Used as the search-tuned re-statement.
    sources
        Up to 3 publisher URLs. Anything beyond the first 3 is dropped.
    topic
        Topic slug ('history', 'space', 'ocean', etc.) used in the
        deterministic fallback hashtag set.

    Returns
    -------
    str
        Description body suitable for the YouTube `snippet.description`
        field. Always non-empty when the inputs are non-empty.
    """
    sources = sources or []
    prompt = _build_prompt(reel_title, claim, sources, topic)

    envelope = call_claude_cli(prompt, model=_MODEL)
    if envelope is None:
        return _deterministic_fallback(reel_title, claim, sources, topic, "cli_unavailable")

    raw = (envelope.get("result") or "").strip()

    cleaned, hits = _strip_clickbait(raw)
    if hits:
        print(
            f"  [yt-desc] WARNING: model returned banned clickbait phrase(s): "
            f"{hits}; stripped and continuing"
        )

    if not _has_minimum_shape(cleaned):
        return _deterministic_fallback(reel_title, claim, sources, topic, "malformed_shape")

    return normalise(cleaned)
