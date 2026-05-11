"""Renderer for curated list-format carousels (films, TV, books).

Revived 2026-05-11 as part of Phase N. Caller is
pipelines/list/ship_curated_list.py via src/content/pack_resolver.py.

Distinct from `src/render/render_carousel.py:CarouselRenderer` because:
- Image source is TMDB (poster + backdrop), not stock-photo search.
- Each slide carries multiple text fields (title, year, director, hook,
  IMDb + Rotten Tomatoes scores).
- Layout is poster-card + text-column, not full-bleed-text-overlay.
- Three templates (hook / item / closing) instead of two.

Inputs are pre-built `ListSlideSpec` records — the ship script does the
TMDB lookups and asset downloads BEFORE calling render(), so this class
is a pure HTML + Playwright stage.

Font handling: `label_font_canonical` is REQUIRED in the brand kit (post
Phase H, v2.1). If the legacy `label_font` is the only key present the
renderer hard-fails rather than silently shipping JetBrains Mono Bold.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from src.render.brand_lock import assert_brand_guidelines_locked

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
LOGO_PATH = Path("assets/logo/factjot_mark.png")
ARCHIVO_BLACK_PATH = Path("assets/fonts/ArchivoBlack-Regular.ttf")
TOKEN_RE = re.compile(r"(\[/?[ih]\])")


@dataclass
class ListSlideSpec:
    """One slide's resolved input. The ship script builds these.

    Fields used per kind:
        kind = "hook":     title, subtitle, kicker, backdrop_local_path
        kind = "item":     title, year, director, hook, accent_word,
                           backdrop_local_path, poster_local_path,
                           number, total
        kind = "closing":  headline, cta, backdrop_local_path, recap_items
    """
    kind: str
    title: str = ""
    subtitle: str = ""
    kicker: str = ""
    year: str = ""
    director: str = ""
    hook: str = ""
    accent_word: str = ""
    headline: str = ""
    cta: str = ""
    number: int = 0
    total: int = 0
    backdrop_local_path: str = ""
    poster_local_path: str = ""
    recap_items: list[dict] = field(default_factory=list)
    imdb_score: str = ""        # e.g. "7.9"
    rotten_score: str = ""      # e.g. "94%"
    runtime: str = ""           # e.g. "115 MIN"
    genre: str = ""             # e.g. "SCI-FI"  (kept on spec for future reuse, no longer rendered)
    leading_cast: list[str] = field(default_factory=list)  # ["NATALIE PORTMAN", "OSCAR ISAAC"]
    watch_providers: list[str] = field(default_factory=list)  # kept on spec for future use, no longer rendered


class ListCarouselRenderer:
    def __init__(self, brand: dict, width: int = 1080, height: int = 1350,
                 output_dir: str | None = None) -> None:
        from src.core.paths import RENDERS_CACHE
        self.brand = brand
        self.width = width
        self.height = height
        self.output_dir = Path(output_dir) if output_dir else RENDERS_CACHE
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        self._tpl_hook = self.env.get_template("list_hook.html.j2")
        self._tpl_item = self.env.get_template("list_item.html.j2")
        self._tpl_closing = self.env.get_template("list_closing.html.j2")

    # ----- public --------------------------------------------------------

    def render(self, post_id: str, category: str, series: str,
               slides: list[ListSlideSpec]) -> list[str]:
        assert_brand_guidelines_locked()

        # Validate every slide carries a backdrop (rule 11 spirit).
        missing = [i for i, s in enumerate(slides, 1) if not s.backdrop_local_path]
        if missing:
            log.warning("list slides %s missing backdrop, aborting", missing)
            return []

        render_dir = self.output_dir / self._render_folder_name(post_id, category, series)
        render_dir.mkdir(parents=True, exist_ok=True)
        out_paths: list[str] = []

        total = len(slides)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                ctx = browser.new_context(
                    viewport={"width": self.width, "height": self.height},
                    device_scale_factor=2,
                )
                for i, spec in enumerate(slides, start=1):
                    spec.total = total
                    spec.number = i
                    html = self._build_html(spec, category)
                    page = ctx.new_page()
                    page.set_content(html, wait_until="networkidle")
                    out_file = render_dir / f"slide_{i:02d}.png"
                    page.screenshot(
                        path=str(out_file), omit_background=False, full_page=False,
                        clip={"x": 0, "y": 0, "width": self.width, "height": self.height},
                    )
                    page.close()
                    out_paths.append(str(out_file))
                ctx.close()
            finally:
                browser.close()
        return out_paths

    # ----- HTML build per kind ------------------------------------------

    def _build_html(self, spec: ListSlideSpec, category: str) -> str:
        ty = self.brand["typography"]
        index_label = f"{spec.number:02d} / {spec.total:02d}"
        # v2.1: templates use Space Grotesk Bold via font_sans_bold.
        # `label_font_canonical` is required - never silently fall back
        # to the legacy `label_font` (JetBrains Mono), since that's the
        # silent regression vector the 2026-05-10 audit flagged.
        if "label_font_canonical" not in ty:
            raise KeyError(
                "brand_kit.typography.label_font_canonical missing - "
                "required since v2.1; do not silently fall back to "
                "the legacy label_font (JetBrains Mono Bold)"
            )
        label_canonical = ty["label_font_canonical"]
        common = dict(
            width=self.width, height=self.height,
            font_serif_regular=self._asset_url(ty["headline_font"]),
            font_serif_italic=self._asset_url(ty["headline_italic_font"]),
            font_sans_bold=self._asset_url(label_canonical),
            font_mono_bold=self._asset_url(ty["label_font"]),
            font_archivo_black=self._asset_url(str(ARCHIVO_BLACK_PATH)) if ARCHIVO_BLACK_PATH.exists() else None,
            wordmark_image_url=self._asset_url(str(LOGO_PATH)) if LOGO_PATH.exists() else "",
            index_label=index_label,
            category=category,
        )

        if spec.kind == "hook":
            return self._tpl_hook.render(
                image_url=self._asset_url(spec.backdrop_local_path),
                title=spec.title,
                subtitle=spec.subtitle,
                kicker=spec.kicker or category,
                **common,
            )

        if spec.kind == "item":
            # Number badge always two-digit + total.
            number_label = f"{spec.number - 1:02d} / {spec.total - 2:02d}"
            # ^ subtract hook + closing from "list slot" count, so item 2 → "01/05"
            hook_html = self._hook_to_html(spec.hook, spec.accent_word)
            return self._tpl_item.render(
                backdrop_url=self._asset_url(spec.backdrop_local_path),
                poster_url=self._asset_url(spec.poster_local_path),
                title=spec.title,
                year=spec.year,
                director=spec.director,
                hook_html=hook_html,
                number_label=number_label,
                imdb_score=spec.imdb_score,
                rotten_score=spec.rotten_score,
                runtime=spec.runtime,
                genre=spec.genre,
                leading_cast=spec.leading_cast,
                **common,
            )

        if spec.kind == "closing":
            return self._tpl_closing.render(
                image_url=self._asset_url(spec.backdrop_local_path),
                headline=spec.headline,
                cta=spec.cta,
                recap_items=spec.recap_items,
                **common,
            )

        raise ValueError(f"unknown ListSlideSpec.kind: {spec.kind!r}")

    # ----- text helpers -------------------------------------------------

    def _hook_to_html(self, text: str, accent_word: str) -> str:
        """Apply factjot italic+accent treatment to a hook line.

        If `accent_word` matches a substring of `text`, that span gets
        wrapped in italic+accent. The rest is plain. We always escape first.
        """
        if not text:
            return ""
        safe = escape(text)
        if accent_word:
            safe_accent = escape(accent_word)
            # First match only, case-insensitive.
            pat = re.compile(re.escape(safe_accent), re.IGNORECASE)
            safe = pat.sub(
                lambda m: f'<em class="accent">{m.group(0)}</em>',
                safe,
                count=1,
            )
        return safe

    # ----- asset helpers ------------------------------------------------

    @staticmethod
    def _asset_url(path: str) -> str:
        if not path:
            return ""
        p = Path(path)
        if not p.exists():
            return ""
        suffix = p.suffix.lower()
        mime = {
            ".ttf": "font/ttf", ".otf": "font/otf",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def _render_folder_name(self, post_id: str, category: str, series: str) -> str:
        from datetime import datetime, timezone
        next_index = 1
        if self.output_dir.exists():
            for child in self.output_dir.iterdir():
                if not child.is_dir():
                    continue
                token = child.name.split("_", 1)[0]
                if token.isdigit():
                    next_index = max(next_index, int(token) + 1)
        date_token = datetime.now(timezone.utc).strftime("%Y%m%d")
        cat = re.sub(r"[^A-Za-z0-9]+", "_", (category or "LIST").upper()).strip("_") or "LIST"
        ser = re.sub(r"[^A-Za-z0-9]+", "_", (series or "factjot").lower()).strip("_") or "factjot"
        return f"{next_index:03d}_{date_token}_{cat}_{ser}_{post_id}"


__all__ = ["ListCarouselRenderer", "ListSlideSpec"]
