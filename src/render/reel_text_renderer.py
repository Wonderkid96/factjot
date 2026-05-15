"""Playwright-based text overlay renderer for Reels.

Renders transparent 1080x1920 PNG overlay frames using HTML+CSS, matching
the v2.1 Instrument Serif / Space Grotesk Bold typography as the carousel
posts (kinetic subtitles use Archivo Bold 700; hooks use Archivo Black
900). Brand-consistent, pixel-perfect, italic [i]/[h] emphasis tokens
work natively.

A single Playwright browser session renders many frames per call, so the
~40 overlays per Reel cost ~6-10 seconds total instead of one cold start
per frame.

Output frames are RGBA PNGs with transparent background, ready to overlay
in FFmpeg.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #
from src.core.brand import (
    FONT_SERIF_REGULAR, FONT_SERIF_ITALIC,
    FONT_SANS_SEMIBOLD, FONT_SANS_MEDIUM,
    FONT_SANS_BOLD,
    FONT_ARCHIVO_BOLD,
    FONT_CAPTION_BLACK,
    REEL_W as _W, REEL_H as _H,
    assert_fonts_present,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Heuristic emphasis: numbers / years -> [h]...[/h] (accent italic)
# First proper noun -> [i]...[/i] (italic white)
# Max 2 highlights per chunk (per brand rule).
_NUMBER_RE = re.compile(r"\b\$?[\d,]+(?:\.\d+)?(?:%|st|nd|rd|th|s)?\b")
_YEAR_RE   = re.compile(r"\b(?:18|19|20)\d{2}s?\b")
_PROPER_RE = re.compile(r"\b([A-Z][a-z]{2,})\b")
_NOT_PROPER = frozenset({
    "Told", "Said", "Asked", "Called", "Used", "Found", "Made", "Built",
    "Created", "Born", "Died", "Lived", "Killed", "Saved", "Many", "Most",
    "Some", "Few", "When", "Where", "What", "Why", "How", "Then", "Later",
    "Today", "Now", "After", "Before", "Once", "First", "Last", "Soon",
    "Even", "Only", "Still", "Just", "Often", "Eventually", "Early", "Late",
    "The", "Their", "There", "These", "Those", "This", "That",
})


# ------------------------------------------------------------------ #
# Renderer
# ------------------------------------------------------------------ #

@dataclass
class TextFrame:
    """A single overlay frame to be rendered."""
    style: str          # "label" | "hook" | "subtitle" | "cta" | "logo"
    text: str           # plain or with [i]/[h] tokens
    out_path: Path
    hook_size: int = 124    # Hero scale - large enough to command attention
    subtitle_size: int = 84  # Archivo Bold 700 - legible on moving footage


class ReelTextRenderer:
    """Renders all text overlays for a Reel via a single Playwright session."""

    def __init__(self, emphasis_keywords: Iterable[str] | None = None) -> None:
        assert_fonts_present()   # hard fail if brand fonts are missing
        self._emphasis_keywords: set[str] = (
            {k.strip().lower() for k in (emphasis_keywords or []) if k.strip()}
        )
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=False,  # we sanitise inputs ourselves so emphasis HTML survives
        )
        self.template = self.env.get_template("reel_text_frame.html.j2")

    def render_all(self, frames: list[TextFrame]) -> list[Path]:
        """Render all frames in one Playwright session.

        Returns the list of paths in the same order as `frames`.
        """
        out_paths: list[Path] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={"width": _W, "height": _H},
                    device_scale_factor=1,
                )
                for frame in frames:
                    frame.out_path.parent.mkdir(parents=True, exist_ok=True)
                    html = self._build_html(frame)
                    page = context.new_page()
                    page.set_content(html, wait_until="networkidle")
                    page.evaluate("() => document.fonts.ready")
                    page.screenshot(
                        path=str(frame.out_path),
                        omit_background=True,  # transparent PNG
                        full_page=False,
                        clip={"x": 0, "y": 0, "width": _W, "height": _H},
                    )
                    page.close()
                    out_paths.append(frame.out_path)
            finally:
                browser.close()
        return out_paths

    def _build_html(self, frame: TextFrame) -> str:
        # Font paths come from src.core.brand - single source of truth.
        # Adding a new font requires updating brand.py first.
        return self.template.render(
            width=_W,
            height=_H,
            style=frame.style,
            text=self._format_text(frame.text, frame.style),
            hook_size=frame.hook_size,
            subtitle_size=frame.subtitle_size,
            font_serif_regular=FONT_SERIF_REGULAR.as_uri(),
            font_serif_italic=FONT_SERIF_ITALIC.as_uri(),
            font_sans_semibold=FONT_SANS_SEMIBOLD.as_uri(),
            font_sans_medium=FONT_SANS_MEDIUM.as_uri(),
            font_sans_bold=FONT_SANS_BOLD.as_uri(),
            font_archivo_bold=FONT_ARCHIVO_BOLD.as_uri(),
            font_archivo_black=FONT_CAPTION_BLACK.as_uri(),
        )

    # ------------------------------------------------------------------ #
    # Emphasis token handling - converts plain text + [i]/[h] tokens into
    # safe HTML. If the text already contains tokens we honour them; if
    # not, we apply heuristic emphasis (year/number -> [h], first proper
    # noun -> [i]) capped at the brand's max_highlights_per_slide.
    # ------------------------------------------------------------------ #

    def _format_text(self, text: str, style: str) -> str:
        if style in {"label", "logo", "cta"}:
            # These styles render text verbatim, no markup.
            return escape(text)

        # If the text has explicit markup, just convert to HTML.
        if "[h]" in text or "[i]" in text:
            return self._tokens_to_html(text)

        # Auto-apply heuristic markup (max 2 highlights per chunk).
        marked = self._auto_mark(text)
        return self._tokens_to_html(marked)

    @staticmethod
    def _tokens_to_html(text: str) -> str:
        """Convert [h]/[i] tokens into <em> tags. HTML-escape everything else."""
        out: list[str] = []
        cursor = 0
        token_re = re.compile(r"\[(/?[ih])\]")
        role = "default"
        for match in token_re.finditer(text):
            if match.start() > cursor:
                run = text[cursor: match.start()]
                out.append(_wrap_run(run, role))
            tok = match.group(1)
            if tok == "i":
                role = "i"
            elif tok == "/i":
                role = "default"
            elif tok == "h":
                role = "h"
            elif tok == "/h":
                role = "default"
            cursor = match.end()
        if cursor < len(text):
            out.append(_wrap_run(text[cursor:], role))
        return "".join(out)

    def _auto_mark(self, text: str) -> str:
        """Apply heuristic emphasis markers, max 2 per text block."""
        marks_used = 0

        # 1) Wrap first year/number in [h]...[/h]
        def _mark_h(m):
            nonlocal marks_used
            if marks_used >= 1:
                return m.group(0)
            marks_used += 1
            return f"[h]{m.group(0)}[/h]"

        text = _YEAR_RE.sub(_mark_h, text, count=1)
        if marks_used == 0:
            text = _NUMBER_RE.sub(_mark_h, text, count=1)

        # 2) Wrap first proper noun in [i]...[/i] (skip stop-list)
        i_used = False

        def _mark_i(m):
            nonlocal i_used
            if i_used:
                return m.group(0)
            word = m.group(1)
            if word in _NOT_PROPER:
                return m.group(0)
            i_used = True
            return f"[i]{word}[/i]"

        text = _PROPER_RE.sub(_mark_i, text, count=1)
        # Optional 3) Hook keyword emphasis:
        # Only apply if we did not already place [h] or [i] (avoids nested
        # tags and keeps the total highlight count bounded).
        if marks_used == 0 and not i_used and self._emphasis_keywords:
            for kw in self._emphasis_keywords:
                pattern = re.compile(rf"\b{re.escape(kw)}\b", flags=re.IGNORECASE)
                m = pattern.search(text)
                if not m:
                    continue
                text = pattern.sub(
                    lambda mm: f"[h]{mm.group(0)}[/h]",
                    text,
                    count=1,
                )
                break
        return text


def _wrap_run(text: str, role: str) -> str:
    if not text:
        return ""
    safe = escape(text)
    if role == "i":
        return f"<em>{safe}</em>"
    if role == "h":
        return f'<em class="accent">{safe}</em>'
    return safe


# ------------------------------------------------------------------ #
# Hook word picker - preserved from old overlay module
# ------------------------------------------------------------------ #

_WEAK_ENDINGS = frozenset({
    "and", "or", "but", "the", "a", "an", "in", "of", "to", "at",
    "by", "for", "on", "with", "as", "that", "this", "its", "their",
    "his", "her", "it", "was", "is", "are", "be", "been",
})


def pick_hook_words(claim: str, max_words: int = 5) -> str:
    """Pick 3-5 punchy hook words from the claim.

    Rules:
    - If the fact starts with a year, use up to 4 words around it.
    - Never end on a weak/conjunction word - walk back until we find a
      strong noun, verb or adjective to close on.
    - Fall back to first N content words if no year is found.
    """
    cleaned = re.sub(r"\[/?[ih]\]", "", claim).strip()
    cleaned = re.sub(r"(?<=\w)-(?=\w)", " ", cleaned)
    words = cleaned.split()

    # Try year-anchored hook
    for i in range(min(5, len(words))):
        if _YEAR_RE.match(words[i].strip(".,")):
            # Take a window of up to max_words starting from the word before the year
            start = max(0, i - 1)
            end = min(len(words), start + max_words)
            candidate = words[start:end]
            # Walk back from end until we land on a strong word
            while len(candidate) > 2 and candidate[-1].lower().strip(",.;:") in _WEAK_ENDINGS:
                candidate = candidate[:-1]
            return " ".join(candidate).rstrip(",.;:")

    # No year - take first max_words, strip weak endings
    candidate = words[:max_words]
    while len(candidate) > 2 and candidate[-1].lower().strip(",.;:") in _WEAK_ENDINGS:
        candidate = candidate[:-1]
    return " ".join(candidate).rstrip(",.;:")


# ------------------------------------------------------------------ #
# Photo insert renderer
# ------------------------------------------------------------------ #

def render_photo_insert(
    image_path: Path,
    out_path: Path,
    caption: str = "",
) -> Path:
    """Render a documentary-style photograph insert as a transparent PNG.

    The insert is a print photograph placed over the footage frame:
    - 65% frame width (footage visible on left/right sides)
    - Ivory border (like a developed photo print)
    - Soft drop shadow (grounds it physically)
    - Brand red left accent line
    - Film grain + vignette overlaid on the photo
    - Optional caption in Space Grotesk Bold below the image

    The PNG is 1080x1920 with transparent background -- composited
    into the reel as a regular OverlayFrame at the chosen time window.
    """
    from jinja2 import Environment, FileSystemLoader
    from playwright.sync_api import sync_playwright

    _W, _H = 1080, 1920
    border   = 14   # ivory border thickness px
    cap_pad  = 42   # bottom padding if caption present, else same as border
    frame_w  = 700  # 65% of 1080

    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    tmpl = env.get_template("reel_photo_insert.html.j2")

    x = (_W - frame_w) // 2        # centred horizontally
    y = int(_H * 0.28)              # roughly upper-third so caption stays above CTA zone

    html = tmpl.render(
        width=_W,
        height=_H,
        photo_url=image_path.as_uri(),
        caption=caption.upper()[:40] if caption else "",
        x=x,
        y=y,
        frame_w=frame_w,
        border=border,
        caption_pad=cap_pad if caption else border,
        font_sans_bold=FONT_SANS_BOLD.as_uri(),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(
                viewport={"width": _W, "height": _H},
                device_scale_factor=1,
            )
            page = ctx.new_page()
            page.set_content(html, wait_until="networkidle")
            page.screenshot(
                path=str(out_path),
                omit_background=True,
                full_page=False,
                clip={"x": 0, "y": 0, "width": _W, "height": _H},
            )
            page.close()
        finally:
            browser.close()
    return out_path


def render_case_doc(
    out_path: Path,
    label: str,
    value: str,
    body: str = "",
    x: int = 60,
    y: int = 440,
    rotation: float = -2.0,
    width: int = 480,
) -> Path:
    """Render a casefile text document as a transparent PNG overlay.

    Styled as a physical paper document: ivory background, brand red left
    accent, Space Grotesk Bold (v2.1, was JetBrains Mono). Positioned
    absolutely within the 1080x1920 canvas.
    Composited into the reel as an OverlayFrame with rgba=True.

    Args:
        label:    Small uppercase header (e.g. "SUBJECT", "DATE", "LOCATION").
        value:    Main text displayed large (entity name, year, etc.).
        body:     Optional secondary line in smaller muted type.
        x/y:      Document position within the 1080x1920 frame.
        rotation: Slight tilt in degrees (negative = lean left).
        width:    Document width in pixels.
    """
    from jinja2 import Environment, FileSystemLoader

    value_size = 22 if len(value) > 18 else (26 if len(value) > 12 else 30)

    # AI-generated content lands in `label`/`value`/`body`. Other render
    # paths in this module escape via `_tokens_to_html` and `_title_to_html`;
    # this one was inconsistent. Escape so a value containing < / > / & does
    # not break the rendered HTML or corrupt the Playwright screenshot.
    safe_label = escape(label.upper())
    safe_value = escape(value)
    safe_body  = escape(body) if body else body

    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    tmpl = env.get_template("reel_case_doc.html.j2")
    html = tmpl.render(
        width=_W, height=_H,
        font_sans_bold=FONT_SANS_BOLD.as_uri(),
        label=safe_label,
        value=safe_value,
        body=safe_body,
        x=x, y=y,
        w=width,
        rotation=rotation,
        value_size=value_size,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(
                viewport={"width": _W, "height": _H},
                device_scale_factor=1,
            )
            page = ctx.new_page()
            page.set_content(html, wait_until="networkidle")
            page.screenshot(
                path=str(out_path),
                omit_background=True,
                full_page=False,
                clip={"x": 0, "y": 0, "width": _W, "height": _H},
            )
            page.close()
        finally:
            browser.close()
    return out_path
