"""factjot HTML+Playwright renderer.

Each slide is laid out in HTML/CSS using Instrument Serif and Space Grotesk
Bold (v2.1, was JetBrains Mono), then screenshotted by headless Chromium to
a 1080x1350 PNG. This gives us real
typography (proper kerning, ligatures, baseline behaviour) and avoids the
PIL-style baseline bugs where punctuation floats.

Inline highlight markup in slide text is converted to HTML before render:

    [i]…[/i]   →  <em>…</em>                  (italic, white)
    [h]…[/h]   →  <em class="accent">…</em>   (italic, accent orange)
"""
from __future__ import annotations

import base64
import logging
import re
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from src.core.models import CarouselPost
from src.render.brand_lock import assert_brand_guidelines_locked
from src.research.image_fetcher import ImageFetcher, NoImageFound

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"(\[/?[ih]\])")
TEMPLATE_DIR = Path(__file__).parent / "templates"
LOGO_PATH = Path("assets/logo/factjot_mark.png")
ARCHIVO_BLACK_PATH = Path("assets/fonts/ArchivoBlack-Regular.ttf")


class BrandKitRenderer:
    def __init__(self, brand: dict, width: int = 1080, height: int = 1350,
                 output_dir: str | None = None) -> None:
        from src.core.paths import RENDERS_CACHE
        from src.core.brand import assert_fonts_present
        assert_fonts_present()
        self.brand = brand
        self.width = width
        self.height = height
        self.output_dir = Path(output_dir) if output_dir else RENDERS_CACHE
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.image_fetcher = ImageFetcher(target_size=(width, height))
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        self._template = self.env.get_template("slide.html.j2")
        self._closing_template = self.env.get_template("closing.html.j2")
        self._stories_template = self.env.get_template("stories_frame.html.j2")

    # ----- public API -----

    def render_post(self, post: CarouselPost) -> list[str]:
        assert_brand_guidelines_locked()
        if self._qa(post):
            post.status = "qa_failed"
            return []

        queries = list(post.image_queries) if post.image_queries else []
        while len(queries) < len(post.slides):
            queries.append(post.category.lower())

        out_paths: list[str] = []
        image_paths: list[str] = []
        image_credits: list[dict[str, str]] = []
        render_dir = self.output_dir / self._render_folder_name(post)
        render_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={"width": self.width, "height": self.height},
                    device_scale_factor=2,
                )
                # Stage 1: fetch one fresh image per slide. Rule 11: every
                # slide must have its own real photo or the post is held.
                bg_paths: list[Path] = []
                missing: list[int] = []
                for i, (slide_text, query) in enumerate(zip(post.slides, queries), start=1):
                    try:
                        bg_path, credit = self.image_fetcher.fetch(
                            query, topic=post.category,
                            seed=f"{post.post_id}:{i}",
                            post_id=post.post_id, slide_index=i,
                            intent_text=slide_text,
                        )
                    except NoImageFound:
                        log.warning(
                            "no fresh image for slide %d of %s - holding post for review",
                            i, post.post_id,
                        )
                        missing.append(i)
                        bg_paths.append(None)
                        image_credits.append({})
                        continue
                    bg_paths.append(bg_path)
                    image_paths.append(str(bg_path))
                    image_credits.append(credit)

                if missing:
                    post.status = f"qa_failed:missing_image_{','.join(str(m) for m in missing)}"
                    post.image_paths = image_paths
                    post.image_credits = image_credits
                    return []

                # Total slide count INCLUDING the closing quote slide if any.
                has_closing = bool(post.closing_quote)
                total_slides = len(post.slides) + (1 if has_closing else 0)

                # Stage 2a: render each fact slide.
                for i, (slide_text, bg_path) in enumerate(zip(post.slides, bg_paths), start=1):
                    html = self._build_html(
                        slide_text=slide_text,
                        bg_path=bg_path,
                        slide_index=i,
                        total=total_slides,
                        category=post.category,
                        is_closing=False,
                    )
                    page = context.new_page()
                    page.set_content(html, wait_until="networkidle")
                    out_file = render_dir / f"slide_{i:02d}.png"
                    page.screenshot(path=str(out_file), omit_background=False, full_page=False,
                                    clip={"x": 0, "y": 0, "width": self.width, "height": self.height})
                    page.close()
                    out_paths.append(str(out_file))

                # Stage 2b: render the closing wholesome-quote slide.
                if has_closing:
                    closing_idx = total_slides
                    html = self._build_closing_html(
                        quote=post.closing_quote,
                        attribution=post.closing_attribution,
                        bg_path=bg_paths[0],
                        slide_index=closing_idx,
                        total=total_slides,
                    )
                    page = context.new_page()
                    page.set_content(html, wait_until="networkidle")
                    out_file = render_dir / f"slide_{closing_idx:02d}.png"
                    page.screenshot(path=str(out_file), omit_background=False, full_page=False,
                                    clip={"x": 0, "y": 0, "width": self.width, "height": self.height})
                    page.close()
                    out_paths.append(str(out_file))
                context.close()
            finally:
                browser.close()

        post.image_paths = image_paths
        post.image_credits = image_credits
        return out_paths

    # ----- HTML build -----

    def _build_html(self, slide_text: str, bg_path: Path, slide_index: int,
                    total: int, category: str, is_closing: bool) -> str:
        ty = self.brand["typography"]
        headline_size, line_height = self._fit_headline_size(slide_text, ty)
        headline_html = self._markup_to_html(slide_text)
        index_label = f"{slide_index:02d} / {total:02d}"

        # v2.1: label_font_canonical (Space Grotesk Bold) is the @font-face
        # Space Grotesk source for slide.html.j2. Direct dict access (not
        # .get()) so a brand_kit edit that drops the key fails loudly on
        # the next render rather than silently reverting carousels to the
        # deprecated label_font (JetBrainsMono-Bold.ttf). brand.py:_load()
        # validates the key at import time as a second guard.
        label_canonical = ty["label_font_canonical"]
        return self._template.render(
            width=self.width,
            height=self.height,
            font_serif_regular=self._asset_url(ty["headline_font"]),
            font_serif_italic=self._asset_url(ty["headline_italic_font"]),
            font_sans_bold=self._asset_url(label_canonical),
            font_archivo_black=self._asset_url(str(ARCHIVO_BLACK_PATH)) if ARCHIVO_BLACK_PATH.exists() else None,
            image_url=self._asset_url(str(bg_path)),
            wordmark_image_url=self._asset_url(str(LOGO_PATH)) if LOGO_PATH.exists() else "",
            headline_html=headline_html,
            headline_size=headline_size,
            headline_line_height=line_height,
            index_label=index_label,
            category=category,
            show_pill=not is_closing,
            show_dot=True,
            footnote="" if is_closing else "",
        )

    def _markup_to_html(self, text: str) -> str:
        # Ensure a sentence-final period exists so we can colour it.
        stripped = text.rstrip()
        if stripped and stripped[-1] not in ".!?":
            text = stripped + "."
        out: list[str] = []
        role = "default"
        cursor = 0
        for match in TOKEN_RE.finditer(text):
            if match.start() > cursor:
                out.append(self._wrap_run(text[cursor: match.start()], role))
            tok = match.group(1)
            if tok == "[i]":
                role = "i"
            elif tok == "[/i]":
                role = "default"
            elif tok == "[h]":
                role = "h"
            elif tok == "[/h]":
                role = "default"
            cursor = match.end()
        if cursor < len(text):
            out.append(self._wrap_run(text[cursor:], role))
        html = "".join(out)
        # Wrap the trailing terminal punctuation so it renders in accent.
        html = re.sub(r"([.!?])(\s*)$", r'<span class="period">\1</span>\2', html)
        return html

    @staticmethod
    def _wrap_run(text: str, role: str) -> str:
        if not text:
            return ""
        safe = escape(text)
        if role == "i":
            return f"<em>{safe}</em>"
        if role == "h":
            return f'<em class="accent">{safe}</em>'
        return safe

    # (chars_upper_bound, font_size_px, line_height)
    # Tuned for 1080x1350 with ~936px usable text width and ~620px text block.
    SIZE_LADDER = [
        (40,  128, 0.98),
        (70,  112, 1.00),
        (110,  96, 1.02),
        (160,  82, 1.06),
        (210,  72, 1.10),
        (260,  64, 1.14),
        (320,  60, 1.18),
    ]

    def _fit_headline_size(self, slide_text: str, ty: dict) -> tuple[int, float]:
        plain = re.sub(r"\[/?[ih]\]", "", slide_text)
        chars = len(plain)
        for cap, size, lh in self.SIZE_LADDER:
            if chars <= cap:
                return size, lh
        return self.SIZE_LADDER[-1][1], self.SIZE_LADDER[-1][2]

    def _build_closing_html(self, quote: str, attribution: str, bg_path: Path,
                             slide_index: int, total: int) -> str:
        ty = self.brand["typography"]
        # Smaller-than-fact headlines so the centred composition breathes.
        chars = len(quote)
        if chars <= 50:
            size, lh = 92, 1.05
        elif chars <= 100:
            size, lh = 76, 1.10
        elif chars <= 160:
            size, lh = 62, 1.15
        else:
            size, lh = 52, 1.18

        # Colour the trailing terminal punctuation in accent.
        safe = quote.strip()
        if safe and safe[-1] not in ".!?":
            safe = safe + "."
        from html import escape
        safe = escape(safe)
        safe = re.sub(r"([.!?])(\s*)$", r'<span class="accent-period">\1</span>\2', safe)

        # See _build_html for why direct dict access (not .get()).
        label_canonical = ty["label_font_canonical"]
        return self._closing_template.render(
            width=self.width, height=self.height,
            font_serif_regular=self._asset_url(ty["headline_font"]),
            font_serif_italic=self._asset_url(ty["headline_italic_font"]),
            font_sans_bold=self._asset_url(label_canonical),
            font_archivo_black=self._asset_url(str(ARCHIVO_BLACK_PATH)) if ARCHIVO_BLACK_PATH.exists() else None,
            image_url=self._asset_url(str(bg_path)),
            wordmark_image_url=self._asset_url(str(LOGO_PATH)) if LOGO_PATH.exists() else "",
            quote_html=safe,
            quote_size=size,
            quote_line_height=lh,
            attribution=attribution.strip(),
            index_label=f"{slide_index:02d} / {total:02d}",
        )

    @staticmethod
    def _asset_url(path: str) -> str:
        """Inline assets as data URLs so Playwright doesn't need a local web server."""
        p = Path(path)
        if not p.exists():
            return ""
        suffix = p.suffix.lower()
        mime = {
            ".ttf": "font/ttf",
            ".otf": "font/otf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def render_stories_frame(self, post: CarouselPost, bg_path: Path | None = None) -> str | None:
        """Render a 9:16 (1080x1920) Stories frame for the post.

        The frame shows the first slide's content in a centred card against a
        blurred version of the same background image. Renders to a PNG next to
        the carousel renders folder.

        Returns the output path string, or None on failure.
        """
        assert_brand_guidelines_locked()
        ty = self.brand["typography"]
        slide_text = post.slides[0] if post.slides else ""
        headline_html = self._markup_to_html(slide_text)
        headline_size, line_height = self._fit_headline_size(slide_text, ty)
        # Scale down slightly for the card: it's ~89% width so text can be a touch larger
        headline_size = min(headline_size + 8, 96)

        # See _build_html for why direct dict access (not .get()).
        label_canonical = ty["label_font_canonical"]
        html = self._stories_template.render(
            width=1080,
            height=1920,
            font_serif_regular=self._asset_url(ty["headline_font"]),
            font_serif_italic=self._asset_url(ty["headline_italic_font"]),
            font_sans_bold=self._asset_url(label_canonical),
            image_url=self._asset_url(str(bg_path)),
            wordmark_image_url=self._asset_url(str(LOGO_PATH)) if LOGO_PATH.exists() else "",
            headline_html=headline_html,
            headline_size=headline_size,
            headline_line_height=line_height,
            category=post.category,
        )

        render_dir = self.output_dir / self._render_folder_name(post)
        out_file = render_dir / "stories_frame.png"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                ctx = browser.new_context(
                    viewport={"width": 1080, "height": 1920},
                    device_scale_factor=2,
                )
                page = ctx.new_page()
                page.set_content(html, wait_until="networkidle")
                page.screenshot(
                    path=str(out_file), omit_background=False, full_page=False,
                    clip={"x": 0, "y": 0, "width": 1080, "height": 1920},
                )
                page.close()
                ctx.close()
            finally:
                browser.close()
        return str(out_file)

    # ----- QA -----

    MAX_QA_WORDS = 60
    MAX_QA_CHARS = 320

    def _qa(self, post: CarouselPost) -> list[str]:
        issues: list[str] = []
        for i, slide in enumerate(post.slides, start=1):
            plain = re.sub(r"\[/?[ih]\]", "", slide)
            if len(plain.split()) > self.MAX_QA_WORDS:
                issues.append(f"slide_{i}_too_long_words")
            if len(plain) > self.MAX_QA_CHARS:
                issues.append(f"slide_{i}_too_long_chars")
            if any(term in plain.lower() for term in ("cure", "guaranteed", "miracle")):
                issues.append(f"slide_{i}_banned_claim")
        return issues

    def _render_folder_name(self, post: CarouselPost) -> str:
        # Format: 2026-05-05_14-30_SPACE_abc123
        # Sorts chronologically in Finder, category is immediately readable.
        raw_dt = post.created_at or ""
        if raw_dt:
            # created_at is ISO: 2026-05-05T14:30:00Z
            date_part = raw_dt[:10]                          # 2026-05-05
            time_part = raw_dt[11:16].replace(":", "-")      # 14-30
            dt_token  = f"{date_part}_{time_part}"
        else:
            from datetime import datetime, timezone
            dt_token = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
        category = re.sub(r"[^A-Za-z0-9]+", "_", (post.category or "FACT").upper()).strip("_") or "FACT"
        return f"{dt_token}_{category}_{post.post_id[:8]}"
