"""Thumbnail Haiku-pick (Phase E.4).

Render 3 candidate thumbnail frames per reel from different footage clips,
ask Haiku 4.5 vision to score each on stop-scroll-strength, return the
strongest. The chosen frame becomes the IG cover frame AND the YouTube
custom thumbnail (one asset, two surfaces, per Q6 decision).

Soft-fail policy (consistent with `entity_image_validator`):

- Missing api_key: return footage_clips[0] first frame, reason="api_key_missing".
- Anthropic call raises: return best-extracted candidate, reason="api_error:<short>".
- Response cannot be parsed: skip that candidate's score, average the rest.
- FFmpeg cannot extract any frame: raise (caller retries or aborts).

The 3 extracted frames live under `data/cache/reels/<reel_id>/thumb_candidates/`.
After the chosen one is moved to the final location, the cache dir can be
cleaned up by the caller (we leave it on disk for debug).
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_PRICING_IN_PER_M = 1.00   # Haiku 4.5: $1 / 1M input tokens
_PRICING_OUT_PER_M = 5.00  # Haiku 4.5: $5 / 1M output tokens

# Frame extraction config
_STILL_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_MAX_CANDIDATES = 3
_FRAME_VF = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
_FRAME_TIMEOUT_S = 60

# Position mix: extract at 25%, 50%, 75% of clip duration. Spread across
# the timeline so we get visually different candidates instead of three
# near-identical frames from the same moment.
_POSITION_FRACTIONS: tuple[float, ...] = (0.25, 0.5, 0.75)


@dataclass(frozen=True)
class _CandidatePlan:
    """One planned frame extraction: which clip, at what time."""
    clip: Path
    seek_seconds: float
    label: str  # e.g. "c0@25%" — used in filename and metadata


def _probe_duration_s(ffmpeg_bin: str, clip: Path) -> float:
    """Return duration of a video clip in seconds, or 0.0 on failure.

    Uses `ffmpeg -i` because ffprobe is not always alongside ffmpeg in our
    fallback paths. Output goes to stderr; we parse "Duration: HH:MM:SS.cc".
    Returns 0.0 for stills and on any parse failure (caller treats 0.0 as
    "use seek=0").
    """
    if clip.suffix.lower() in _STILL_EXTS:
        return 0.0
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", str(clip)],
            capture_output=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0.0
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
    if not m:
        return 0.0
    try:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    except ValueError:
        return 0.0
    return h * 3600.0 + mn * 60.0 + s


def _plan_candidates(
    footage_clips: list[Path], ffmpeg_bin: str,
) -> list[_CandidatePlan]:
    """Choose up to 3 (clip, seek-time) pairs spread across the available footage.

    Strategy:
        - With >= 3 clips: pick 3 distinct clips (first, middle, last) and
          extract at 25%, 50%, 75% of each clip's duration. Different clip
          AND different position maximises visual variety.
        - With 2 clips: clip0@25%, clip1@50%, clip0@75%.
        - With 1 clip: same clip at 25%, 50%, 75% — three different moments.
        - Stills get seek=0 regardless of the chosen fraction.

    Returns at most _MAX_CANDIDATES plans, in decreasing-priority order so
    the caller can drop the tail if Haiku is unavailable.
    """
    n = len(footage_clips)
    if n == 0:
        return []

    # Pick up to 3 clip indexes — first, middle, last for variety.
    if n == 1:
        clip_indexes = [0, 0, 0]
    elif n == 2:
        clip_indexes = [0, 1, 0]
    else:
        clip_indexes = [0, n // 2, n - 1]

    plans: list[_CandidatePlan] = []
    for i, (clip_idx, frac) in enumerate(zip(clip_indexes, _POSITION_FRACTIONS)):
        clip = footage_clips[clip_idx]
        dur = _probe_duration_s(ffmpeg_bin, clip)
        # Stills: seek=0 always. Videos: clamp the seek to [0, dur-0.05]
        # so we never seek past the end (FFmpeg returns the last frame
        # silently in that case but it slows the call).
        if dur <= 0.0:
            seek = 0.0
        else:
            seek = min(max(0.0, frac * dur), max(0.0, dur - 0.05))
        plans.append(_CandidatePlan(
            clip=clip,
            seek_seconds=seek,
            label=f"c{clip_idx}@{int(frac * 100)}",
        ))
    return plans


def _extract_frame(
    ffmpeg_bin: str,
    clip: Path,
    seek_seconds: float,
    out_path: Path,
) -> bool:
    """Extract one 1080x1920 PNG frame at `seek_seconds`. Return True on success.

    Mirrors the multi-fallback behaviour of
    `_extract_reel_thumbnail_frame` in `pipelines/reel/make_reel.py` —
    short clips can fail at the requested seek, so we try a sequence of
    fallback positions before giving up.
    """
    is_still = clip.suffix.lower() in _STILL_EXTS
    if is_still:
        seek_seq: tuple[str, ...] = ("0",)
    else:
        primary = f"{seek_seconds:.2f}"
        seek_seq = (primary, "1.0", "0.5", "0.25", "0")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    for seek in seek_seq:
        out_path.unlink(missing_ok=True)
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", seek,
            "-i", str(clip),
            "-vframes", "1",
            "-vf", _FRAME_VF,
            str(out_path),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=_FRAME_TIMEOUT_S,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        if out_path.is_file() and out_path.stat().st_size > 1024:
            return True
    return False


def _build_score_prompt(claim: str, reel_title: str) -> str:
    """Strict-JSON prompt asking Haiku to score one candidate frame."""
    claim_clean = (claim or "").strip()
    title_clean = (reel_title or "").strip()
    return (
        "You are scoring an Instagram Reels / YouTube Shorts thumbnail "
        "candidate on stop-scroll strength.\n\n"
        f"Reel topic claim: \"{claim_clean}\"\n"
        f"Reel title: \"{title_clean}\"\n\n"
        "Look at the image and rate it 1 to 10 as a Shorts thumbnail. "
        "Higher means more likely to make a viewer stop scrolling. "
        "Consider:\n"
        "- Subject clarity (a clear subject beats a busy abstract frame)\n"
        "- Visual contrast (bold light/dark beats washed-out mid-tones)\n"
        "- Framing (centred or rule-of-thirds beats off-balance)\n"
        "- Recognisability (does the frame match the claim's subject)\n"
        "- Reject thumbnails that are mostly black, mostly text, or "
        "show watermarks / channel logos.\n\n"
        "Return strict JSON only:\n"
        "{\"score\": 1-10, \"reason\": \"<short explanation, max 12 words>\"}\n\n"
        "Be calibrated: most usable thumbnails score 5-7. Reserve 8-10 for "
        "frames that are genuinely visually striking. Reserve 1-3 for "
        "frames that are unusable (black, blurry, off-subject)."
    )


def _parse_score_response(raw_text: str) -> tuple[int | None, str]:
    """Extract (score, reason) from a Haiku response. None on failure."""
    if not raw_text:
        return None, "empty_response"
    m = re.search(r"\{[\s\S]*\}", raw_text)
    if not m:
        return None, f"no_json:{raw_text[:60]}"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return None, f"json_decode:{str(exc)[:40]}"
    score = data.get("score")
    reason = str(data.get("reason", "")).strip()[:120]
    try:
        score_i = int(score)
    except (TypeError, ValueError):
        return None, f"invalid_score:{score!r}"
    score_i = max(1, min(10, score_i))
    return score_i, reason or "scored"


def _compute_cost(usage: Any) -> float:
    """Compute Haiku 4.5 cost in USD for one response. 0.0 on missing usage."""
    try:
        cost = (
            usage.input_tokens / 1_000_000 * _PRICING_IN_PER_M
            + usage.output_tokens / 1_000_000 * _PRICING_OUT_PER_M
        )
    except (AttributeError, TypeError):
        return 0.0
    return round(float(cost), 6)


def _detect_media_type(data: bytes) -> str:
    """Return Anthropic-compatible media_type for the given image bytes."""
    if not data:
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _score_candidate(
    frame_path: Path,
    claim: str,
    reel_title: str,
    api_key: str,
) -> dict:
    """Ask Haiku to score one candidate frame. Returns dict with score/reason/cost.

    On any infra failure (no SDK, no key, network error) returns
    {"score": None, "reason": "<short>", "cost_usd": 0.0}. The caller
    treats score=None as "could not score" and falls back per its own
    policy.
    """
    if not api_key:
        return {"score": None, "reason": "api_key_missing", "cost_usd": 0.0}

    try:
        img_bytes = frame_path.read_bytes()
    except OSError as exc:
        return {"score": None, "reason": f"read_failed:{str(exc)[:60]}", "cost_usd": 0.0}
    if len(img_bytes) < 64:
        return {"score": None, "reason": "frame_too_small", "cost_usd": 0.0}

    media_type = _detect_media_type(img_bytes)
    b64 = base64.standard_b64encode(img_bytes).decode("ascii")

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"score": None, "reason": "anthropic_sdk_missing", "cost_usd": 0.0}

    prompt = _build_score_prompt(claim, reel_title)

    try:
        client = Anthropic(api_key=api_key)
        res = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=120,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except Exception as exc:
        return {"score": None, "reason": f"api_error:{str(exc)[:80]}", "cost_usd": 0.0}

    cost = _compute_cost(getattr(res, "usage", None))
    raw_text = ""
    try:
        raw_text = res.content[0].text or ""
    except (AttributeError, IndexError):
        raw_text = ""

    score, reason = _parse_score_response(raw_text)
    if score is None:
        return {"score": None, "reason": f"parse_failed:{reason}", "cost_usd": cost}
    return {"score": score, "reason": reason, "cost_usd": cost}


def _soft_fallback(
    footage_clips: list[Path],
    candidate_dir: Path,
    ffmpeg_bin: str,
    reason: str,
) -> tuple[Path, dict]:
    """Return footage_clips[0] first frame as the chosen thumbnail.

    Used when Haiku is unavailable, when no candidates could be extracted,
    or when every candidate's Haiku call failed. The pipeline still ships;
    the thumbnail is just the legacy first-frame heuristic.
    """
    if not footage_clips:
        raise RuntimeError("no footage clips available for thumbnail fallback")
    fallback_clip = footage_clips[0]
    fallback_frame = candidate_dir / "fallback_first_frame.png"
    if not _extract_frame(ffmpeg_bin, fallback_clip, 0.0, fallback_frame):
        raise RuntimeError(
            f"fallback frame extraction failed for {fallback_clip.name}"
        )
    return fallback_frame, {
        "chosen_frame": str(fallback_frame),
        "candidates": [{
            "frame": str(fallback_frame),
            "score": None,
            "reason": "fallback:" + reason,
            "label": "fallback",
        }],
        "total_cost_usd": 0.0,
        "fallback_reason": reason,
    }


def pick_best_thumbnail(
    footage_clips: list[Path],
    claim: str,
    reel_title: str,
    api_key: str,
    *,
    candidate_dir: Path,
    ffmpeg_bin: str,
) -> tuple[Path, dict]:
    """Pick the best thumbnail frame from up to 3 candidates.

    Parameters
    ----------
    footage_clips
        Mix of MP4 video clips and still images, in the same order the
        reel composer received them. The picker spreads candidates across
        first / middle / last clip when possible.
    claim
        Plain-text claim from the reel brief; passed to Haiku for context.
    reel_title
        The curated or auto-generated reel title; passed to Haiku for context.
    api_key
        Anthropic API key. Empty -> soft-fall to footage_clips[0] first frame.
    candidate_dir
        Directory to write the 3 candidate PNGs (created if missing).
        Recommended: `data/cache/reels/<reel_id>/thumb_candidates/`.
    ffmpeg_bin
        Path to the ffmpeg binary; pass `src.core.ffmpeg_bin.assert_reel_ffmpeg_ready()`.

    Returns
    -------
    (chosen_frame_path, metadata_dict). Metadata shape:
        {
            "chosen_frame": "<absolute path>",
            "candidates": [
                {"frame": "<path>", "score": <int|None>, "reason": "<short>", "label": "<id>"},
                ...
            ],
            "total_cost_usd": <float>,
            "fallback_reason": "<str>" (only present if soft-fell),
        }

    Raises
    ------
    RuntimeError
        If every frame-extraction attempt (including the fallback) fails.
        Image-pipeline §1.5: never accept an empty / placeholder thumbnail.
    """
    candidate_dir.mkdir(parents=True, exist_ok=True)

    if not footage_clips:
        raise RuntimeError("pick_best_thumbnail called with empty footage_clips")

    # 1. Plan + extract candidate frames
    plans = _plan_candidates(footage_clips, ffmpeg_bin)
    candidates: list[dict] = []
    for plan in plans:
        out_png = candidate_dir / f"cand_{plan.label}.png"
        ok = _extract_frame(ffmpeg_bin, plan.clip, plan.seek_seconds, out_png)
        if not ok:
            print(
                f"  [thumb-pick] {plan.label} extraction failed "
                f"(clip={plan.clip.name}, seek={plan.seek_seconds:.2f}s)"
            )
            continue
        candidates.append({
            "frame": out_png,
            "label": plan.label,
            "clip": plan.clip.name,
            "seek": plan.seek_seconds,
        })

    # No frames extracted at all — try the fallback (clip[0] @ seek=0) one
    # last time. If even that fails we have no usable thumbnail and must raise.
    if not candidates:
        return _soft_fallback(
            footage_clips, candidate_dir, ffmpeg_bin,
            reason="no_candidates_extracted",
        )

    # 2. Soft-fall when no api_key — first extracted candidate wins
    if not api_key:
        chosen = candidates[0]
        return chosen["frame"], {
            "chosen_frame": str(chosen["frame"]),
            "candidates": [
                {
                    "frame": str(c["frame"]),
                    "score": None,
                    "reason": "api_key_missing",
                    "label": c["label"],
                }
                for c in candidates
            ],
            "total_cost_usd": 0.0,
            "fallback_reason": "api_key_missing",
        }

    # 3. Score each candidate with Haiku 4.5 vision (cap: _MAX_CANDIDATES calls)
    total_cost = 0.0
    scored: list[dict] = []
    for cand in candidates[:_MAX_CANDIDATES]:
        result = _score_candidate(
            frame_path=cand["frame"],
            claim=claim,
            reel_title=reel_title,
            api_key=api_key,
        )
        total_cost += float(result.get("cost_usd", 0.0))
        scored.append({
            "frame": cand["frame"],
            "label": cand["label"],
            "score": result.get("score"),
            "reason": result.get("reason", ""),
        })
        # Print one line per candidate for grep-able pipeline.log entries
        sc = result.get("score")
        print(
            f"  [thumb-pick] {cand['label']}: "
            f"score={'-' if sc is None else sc}/10 "
            f"reason={result.get('reason', '')[:60]}"
        )

    # 4. Pick the highest-scored candidate. None scores sort below real scores.
    def _sort_key(item: dict) -> tuple[int, int]:
        sc = item.get("score")
        # (has_score, score) so None drops to the bottom
        return (1 if sc is not None else 0, sc if sc is not None else -1)

    scored_sorted = sorted(scored, key=_sort_key, reverse=True)
    best = scored_sorted[0]

    # If every score is None (all calls failed), soft-fall — but use the
    # first extracted candidate (already on disk, no extra ffmpeg call).
    if best["score"] is None:
        chosen_frame = candidates[0]["frame"]
        return chosen_frame, {
            "chosen_frame": str(chosen_frame),
            "candidates": [
                {
                    "frame": str(s["frame"]),
                    "score": s["score"],
                    "reason": s["reason"],
                    "label": s["label"],
                }
                for s in scored
            ],
            "total_cost_usd": round(total_cost, 6),
            "fallback_reason": "all_haiku_calls_failed",
        }

    chosen_frame = best["frame"]
    print(
        f"  [thumb-pick] chosen: {best['label']} score={best['score']}/10 "
        f"({total_cost*100:.3f}p across {len(scored)} candidates)"
    )

    return chosen_frame, {
        "chosen_frame": str(chosen_frame),
        "candidates": [
            {
                "frame": str(s["frame"]),
                "score": s["score"],
                "reason": s["reason"],
                "label": s["label"],
            }
            for s in scored
        ],
        "total_cost_usd": round(total_cost, 6),
    }
