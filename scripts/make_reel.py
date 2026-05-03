"""Generate and publish a factjot Reel from a top-tier fact.

End-to-end pipeline:
    1.  Select a quirky_score=3 fact not yet used as a Reel.
    2.  Find portrait footage via multi-source video_finder.
    3.  Synthesise voice-over via Edge TTS (en-GB-SoniaNeural).
    4.  Render PNG overlay frames (category label, hook text, fact chunks, CTA, logo).
    5.  Compose final 1080x1920 MP4 via FFmpeg.
    6.  Upload MP4 to Cloudinary (public HTTPS URL for IG).
    7.  Publish as IG Reel via Graph API.
    8.  Record in brain + log.

Usage:
    python3 scripts/make_reel.py
    python3 scripts/make_reel.py --topic space
    python3 scripts/make_reel.py --topic history --dry-run
    python3 scripts/make_reel.py --list-facts          # preview available facts
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.brain import brain
from src.core.config import load_config
from src.render.reel_composer import (
    OverlayFrame,
    compose,
    FADE_TO_BLACK_S,
    n_clips_for_duration,
)
from src.render.reel_text_renderer import (
    ReelTextRenderer,
    TextFrame,
)
from src.content.reel_title import make_title
from src.render.tts_engine import audio_duration, group_into_chunks, synthesise
from src.research.rare_fact_bank import load_all_facts
from src.research.video_finder import find_videos
from src.utils.logging_utils import configure_logging


# ------------------------------------------------------------------ #
# Outro phrase pool — one is appended to every VO script.
# Each phrase contains the word "factjot" so the compositor can sync
# the CTA card to the exact moment the narrator says the brand name.
# ------------------------------------------------------------------ #
_OUTROS = [
    "Follow factjot for more.",
    "Follow factjot for more like this.",
    "More every day. Follow factjot.",
    "Want more? Follow factjot.",
    "More where that came from. Follow factjot.",
    "Find more facts at factjot.",
]


def _append_outro(script: str) -> str:
    """Append a randomised outro phrase to the VO script."""
    script = script.rstrip()
    if not script.endswith((".", "!", "?")):
        script += "."
    return script + "  " + random.choice(_OUTROS)


# ------------------------------------------------------------------ #
# Video upload — tmpfiles.org (free, no signup, URL lives long enough
# for Meta to fetch it, which is all we need)
# ------------------------------------------------------------------ #

def _upload_video(mp4_path: Path) -> str:
    """Upload the final MP4 and return a public URL Instagram can fetch."""
    from src.publish.image_host import TmpfilesHost
    size_kb = mp4_path.stat().st_size // 1024
    host = TmpfilesHost()
    print(f"  [tmpfiles] uploading {size_kb} KB...")
    result = host.upload(mp4_path)
    print(f"  [tmpfiles] url: {result.public_url}")
    return result.public_url


def _recompress(src: Path, crf: int = 30, maxrate: str = "800k") -> Path:
    """Return a smaller re-encoded copy of the MP4 for 413 fallback."""
    import subprocess
    out = src.with_suffix(f".crf{crf}.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "slow",
        "-crf", str(crf), "-maxrate", maxrate, "-bufsize", str(int(maxrate[:-1]) * 2) + "k",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(out),
    ], check=True, capture_output=True)
    print(f"  [recompress] crf={crf} -> {out.stat().st_size // 1024} KB")
    return out


# ------------------------------------------------------------------ #
# Music selection
# ------------------------------------------------------------------ #

def _pick_music(topic: str) -> Path | None:
    music_dir = Path(__file__).resolve().parents[1] / "assets" / "music"
    # Try topic-specific, then any track
    for candidate in [music_dir / f"{topic}.mp3", music_dir / "default.mp3"]:
        if candidate.exists():
            return candidate
    # Any .mp3 in the directory
    tracks = list(music_dir.glob("*.mp3"))
    return tracks[0] if tracks else None


# ------------------------------------------------------------------ #
# Fact selection
# ------------------------------------------------------------------ #

# Hard floor on the curated reel_script length. Below this, the auto-generator
# would have produced a 22-second reel (the bug we're fixing). 70 words at
# ~140 wpm = ~30s of voice + 3.5s intro + ~2.3s tail ≈ 36s final reel.
MIN_REEL_SCRIPT_WORDS = 70


class ReelFactInvariantError(RuntimeError):
    """Raised when the picked fact violates a reel-quality invariant.

    Hard guarantees enforced by `_pick_fact`:
      1. quirky_score == 3
      2. sensitivity != 'controversial' (mirrors plan_week.py — never auto-publish flagged facts)
      3. has a curated `reel_title`        (no nonsense auto-titles like "The Story of Until Switzerland")
      4. has a curated `reel_script`       (no 22-second auto-formatted reels)
      5. reel_script word count >= MIN_REEL_SCRIPT_WORDS (length floor)
    """


def _pick_fact(topic: str | None) -> dict | None:
    """Pick the best unused fact that passes every reel-quality invariant.

    See `ReelFactInvariantError` for the full list. Facts that fail any gate
    are silently skipped here; the caller logs which gates eliminated them
    via `_log_pick_diagnostics`.
    """
    from src.research.sensitivity_guide import CONTROVERSIAL

    used_as_reel = brain.list_reel_claims()  # reads reels.jsonl fresh from disk
    all_facts = [r for r in load_all_facts() if r.get("quirky_score", 0) == 3]
    if topic:
        all_facts = [r for r in all_facts if r["topic"] == topic]

    fresh = [
        r for r in all_facts
        if not brain.is_fact_posted(r["claim"])
        and r["claim"] not in used_as_reel
        and r.get("sensitivity") != CONTROVERSIAL
        and r.get("reel_title")
        and r.get("reel_script")
        and len(r["reel_script"].split()) >= MIN_REEL_SCRIPT_WORDS
    ]
    if not fresh:
        return None
    fresh.sort(key=lambda r: r.get("quirky_score", 0), reverse=True)
    return fresh[0]


def _log_pick_diagnostics(topic: str | None) -> None:
    """Print why no fact qualified, so failures are immediately actionable."""
    from src.research.sensitivity_guide import CONTROVERSIAL
    used_as_reel = brain.list_reel_claims()
    pool = [r for r in load_all_facts() if r.get("quirky_score", 0) == 3]
    if topic:
        pool = [r for r in pool if r["topic"] == topic]

    posted = used = controversial = no_title = no_script = short_script = ok = 0
    for r in pool:
        if brain.is_fact_posted(r["claim"]):
            posted += 1; continue
        if r["claim"] in used_as_reel:
            used += 1; continue
        if r.get("sensitivity") == CONTROVERSIAL:
            controversial += 1; continue
        if not r.get("reel_title"):
            no_title += 1; continue
        if not r.get("reel_script"):
            no_script += 1; continue
        if len(r["reel_script"].split()) < MIN_REEL_SCRIPT_WORDS:
            short_script += 1; continue
        ok += 1

    print(f"  pool: {len(pool)} q3 facts  (topic={topic or 'any'})")
    print(f"    posted-elsewhere : {posted}")
    print(f"    already-as-reel  : {used}")
    print(f"    controversial    : {controversial}")
    print(f"    missing reel_title : {no_title}")
    print(f"    missing reel_script: {no_script}")
    print(f"    script < {MIN_REEL_SCRIPT_WORDS} words   : {short_script}")
    print(f"    eligible         : {ok}")


# ------------------------------------------------------------------ #
# Main pipeline
# ------------------------------------------------------------------ #

def make_reel(topic: str | None, dry_run: bool, voice: str = "en-GB-RyanNeural") -> int:
    configure_logging()
    cfg = load_config()

    # Step 1: Select fact
    fact = _pick_fact(topic)
    if not fact:
        msg = f"No reel-eligible fact found"
        if topic:
            msg += f" for topic={topic!r}"
        print(msg + ".")
        _log_pick_diagnostics(topic)
        print("\nFix: add curated reel_title + reel_script (>= "
              f"{MIN_REEL_SCRIPT_WORDS} words) to a q3 fact in rare_fact_bank.py, "
              "or run scripts/validate_reel_facts.py for the full audit.")
        return 2

    claim    = fact["claim"]
    ftopic   = fact["topic"]
    hint     = fact.get("image_hint", "")
    reel_id  = hashlib.sha1(f"reel:{ftopic}:{claim}".encode()).hexdigest()[:14]
    from src.core.paths import REELS_CACHE
    out_dir  = REELS_CACHE / reel_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nReel {reel_id}")
    print(f"  topic   : {ftopic}")
    print(f"  claim   : {claim[:100]}")
    print(f"  hint    : {hint}")

    # Early duplicate gate — abort BEFORE we spend 2-5 minutes on TTS + FFmpeg
    # if another process has already published this claim.
    from src.brain import DuplicatePostError
    try:
        brain.assert_no_duplicate([claim])
    except DuplicatePostError as e:
        print(f"\nABORTED — duplicate block (early gate):\n{e}")
        brain.append_log(f"reel BLOCKED early — duplicate claim: {claim[:80]}")
        return 8

    # Step 2: Voice-over
    # Curated reel_script is REQUIRED — auto-formatter has been removed because
    # it produces ~22-second reels from short claims (the bug fixed 2026-05-01).
    # _pick_fact already enforced reel_script + word floor; this is belt-and-braces.
    vo_body = fact["reel_script"]
    word_count = len(vo_body.split())
    if word_count < MIN_REEL_SCRIPT_WORDS:
        raise ReelFactInvariantError(
            f"reel_script for {claim[:60]!r} is {word_count} words, "
            f"below floor of {MIN_REEL_SCRIPT_WORDS}. _pick_fact should have rejected this."
        )
    print(f"\nUsing curated reel_script ({word_count} words)")

    # Append a randomised outro. Each variation contains "factjot" so the
    # compositor can sync the CTA card to the exact moment it is spoken.
    vo_script = _append_outro(vo_body)
    print(f"  outro appended — total {len(vo_script.split())} words")

    print(f"Synthesising voice-over (voice={voice})...")
    tts_backend = os.getenv("TTS_BACKEND", "elevenlabs")
    el_key = os.getenv("ELEVENLABS_API_KEY", "")
    el_voice = os.getenv("ELEVENLABS_VOICE", "george")
    tts_voice = el_voice if (tts_backend == "elevenlabs" and el_key) else voice
    mp3_path, word_beats = synthesise(vo_script, out_dir, voice=tts_voice, backend=tts_backend)
    if not word_beats:
        print("ERROR: TTS returned no word timing. Check edge-tts is installed.")
        return 4

    # Silent intro — hook title shows here, voice starts AFTER it fades.
    INTRO_S = 3.5

    padded_mp3 = out_dir / "voice_padded.mp3"
    import subprocess as _sp
    _sp.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", str(INTRO_S), "-i", "anullsrc=r=44100:cl=stereo",
        "-i", str(mp3_path),
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map", "[a]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(padded_mp3),
    ], check=True, capture_output=True)
    mp3_path = padded_mp3
    print(f"  pre-padded voice with {INTRO_S}s intro silence -> {padded_mp3.name}")

    voice_end_s = word_beats[-1].end_s + INTRO_S

    # Sync CTA to the moment the narrator says "factjot" in the outro.
    # Search word beats (which are relative to the unpadded voice track)
    # and offset by INTRO_S to get the absolute video timestamp.
    _fj_beats = [b for b in word_beats if "factjot" in b.word.lower()]
    if _fj_beats:
        cta_s = _fj_beats[-1].start_s + INTRO_S
        print(f"  CTA locked to 'factjot' word beat at {cta_s:.1f}s")
    else:
        cta_s = max(0.0, voice_end_s - 3.0)
        print(f"  CTA fallback (no 'factjot' beat found): {cta_s:.1f}s")

    # Total: voice ends + brief pause + fade to black
    total_dur = round(voice_end_s + 0.8 + FADE_TO_BLACK_S, 2)
    n_clips   = n_clips_for_duration(total_dur)

    print(f"  voice duration: {voice_end_s:.1f}s | total reel: {total_dur:.1f}s | CTA at {cta_s:.1f}s | clips: {n_clips}")

    # Hard duration gate — never publish a reel shorter than 35s.
    # Direct response to the 2026-05-01 incident where an auto-generated
    # script produced a 22.7s reel. With curated scripts this should never
    # trigger, but if TTS truncates or a future edit shortens a script
    # below the floor, fail loudly rather than ship a stub.
    MIN_REEL_TOTAL_S = 35.0
    if total_dur < MIN_REEL_TOTAL_S:
        msg = (f"Reel total duration {total_dur:.1f}s is below floor of "
               f"{MIN_REEL_TOTAL_S}s. ABORTING. Curated reel_script may have "
               f"been truncated by TTS, or word floor needs raising.")
        print(f"\nABORTED — {msg}")
        brain.append_log(f"reel ABORTED — short duration {total_dur:.1f}s for {claim[:60]}")
        return 9

    # Step 3: Find N pieces of footage (multi-clip storytelling)
    allow_archival = bool(fact.get("allow_archival", False))
    print(f"\nFinding {n_clips} footage clips (allow_archival={allow_archival})...")

    # Load global footage registry — prevents the same clip appearing in two different reels
    from src.core.paths import USED_FOOTAGE
    global_footage_registry: set[str] = set()
    if USED_FOOTAGE.exists():
        for line in USED_FOOTAGE.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    global_footage_registry.add(json.loads(line)["url"])
                except Exception:
                    pass

    footage_clips = find_videos(
        image_hint=hint, claim=claim, topic=ftopic,
        out_dir=out_dir, count=n_clips,
        allow_archival=allow_archival,
        used_source_registry=global_footage_registry,
    )
    if not footage_clips:
        print("ERROR: could not find any footage. Pre-download safety pool clips with:")
        print("  python3 scripts/setup_reel_assets.py")
        brain.append_log(f"reel FAILED no footage — fact={claim[:60]!r} hint={hint!r}")
        return 3

    # Step 4: Group words into 5-6 word chunks. FFmpeg segfaults beyond ~50
    # input streams on this build, so keep total inputs (footage + overlays)
    # comfortably under that limit. Larger chunks = fewer overlay PNGs.
    chunks = group_into_chunks(
        word_beats,
        words_per_line=6,
        max_chars=44,
        original_text=vo_script,
    )

    # Step 5: Render overlay frames via Playwright (brand-consistent typography)
    print("\nRendering overlay frames (Playwright + Instrument Serif)...")
    overlay_dir = out_dir / "overlays"
    overlay_dir.mkdir(exist_ok=True)

    overlays: list[OverlayFrame] = []
    text_frames: list[TextFrame] = []

    # 5a: Shadow overlay — persistent cinematic framing (top darken + bottom gradient + vignette)
    shadow_path = overlay_dir / "shadow.png"
    text_frames.append(TextFrame(style="overlay", text="", out_path=shadow_path))
    overlays.append(OverlayFrame(png=shadow_path, start_s=0.0, end_s=total_dur, fade_in_s=0.0, fade_out_s=0.0))

    # 5b: Category label (persistent, top-centre)
    label_path = overlay_dir / "label.png"
    text_frames.append(TextFrame(style="label", text=ftopic, out_path=label_path))
    overlays.append(OverlayFrame(png=label_path, start_s=0.0, end_s=total_dur, fade_in_s=0.6, fade_out_s=0.0))

    # 5c: Story title card — fades in during silence, fades out as voice begins.
    # Title occupies the INTRO_S window: fades in at 0, holds, then fades out
    # just as the VO starts so there's a clean handoff to subtitles.
    story_title = make_title(claim, ftopic, reel_title=fact.get("reel_title"))
    if story_title:
        print(f"  title: '{story_title}'")
        TITLE_FADE_IN  = 0.6
        TITLE_FADE_OUT = 0.8   # completes fading just before voice starts
        TITLE_HOLD     = INTRO_S - TITLE_FADE_IN - TITLE_FADE_OUT  # 3.5 - 0.6 - 0.8 = 2.1s

        title_png = overlay_dir / "title.png"
        text_frames.append(TextFrame(style="hook", text=story_title, out_path=title_png))
        overlays.append(OverlayFrame(
            png=title_png,
            start_s=0.0,
            end_s=INTRO_S,
            fade_in_s=TITLE_FADE_IN,
            fade_out_s=TITLE_FADE_OUT,
        ))
        subtitle_start_gate = INTRO_S
    else:
        subtitle_start_gate = 0.0

    # 5d: KINETIC SUBTITLES — appear from first spoken word (after title fades).
    # subtitle_start_gate is already set above by the title block.
    chunks_used = 0
    word_frame_count = 0
    for chunk_idx, chunk in enumerate(chunks):
        if chunk_idx + 1 < len(chunks):
            chunk_end = chunks[chunk_idx + 1][0].start_s
        else:
            chunk_end = chunk[-1].end_s + 0.35
        chunks_used += 1

        # One PNG per chunk (whole 2-word phrase shown together)
        text = " ".join(b.word for b in chunk)
        png = overlay_dir / f"chunk_{chunk_idx:02d}.png"
        chunk_first = chunk[0].start_s
        chunk_last_end = chunk[-1].end_s

        # Offset by intro silence; don't show until title has faded
        start = max(chunk_first + INTRO_S, subtitle_start_gate)
        end = min(chunk_end + INTRO_S, cta_s - 0.05)
        if start >= end:
            continue

        text_frames.append(TextFrame(style="subtitle", text=text, out_path=png))
        overlays.append(OverlayFrame(png=png, start_s=start, end_s=end, fade_in_s=0.0, fade_out_s=0.0))
        word_frame_count += 1
    print(f"  kinetic subtitles: {chunks_used} chunks, {word_frame_count} word frames")

    # 5d: CTA frame
    cta_path = overlay_dir / "cta.png"
    text_frames.append(TextFrame(style="cta", text="@factjot", out_path=cta_path))
    overlays.append(OverlayFrame(png=cta_path, start_s=cta_s, end_s=total_dur, fade_in_s=0.4, fade_out_s=0.0))

    # Single Playwright session renders everything
    print(f"  rendering {len(text_frames)} text frames via Playwright...")
    renderer = ReelTextRenderer()
    renderer.render_all(text_frames)

    # Step 6: Music — random start point so every Reel sounds different
    music_path = _pick_music(ftopic)
    if music_path:
        print(f"  music: {music_path.name}")
    else:
        print("  music: none found")

    # Step 7: Compose
    print("\nComposing video (FFmpeg)...")
    final_mp4 = out_dir / "final.mp4"
    try:
        compose(
            footage_paths=footage_clips,
            voice_path=mp3_path,
            music_path=music_path,
            overlays=overlays,
            out_path=final_mp4,
            total_duration_s=total_dur,
            voice_delay_s=INTRO_S,
        )
    except RuntimeError as exc:
        print(f"\nFFmpeg error:\n{exc}")
        brain.append_log(f"reel FAILED ffmpeg — fact={claim[:60]!r} error={str(exc)[:300]}")
        return 5

    # Persist global footage registry — append any newly used URLs so future reels skip them
    USED_FOOTAGE.parent.mkdir(parents=True, exist_ok=True)
    with USED_FOOTAGE.open("a") as _reg_f:
        for _url in sorted(global_footage_registry):
            _reg_f.write(json.dumps({"url": _url, "reel_id": reel_id}) + "\n")

    print(f"\nReel composed: {final_mp4}")
    print(f"  size: {final_mp4.stat().st_size / 1024 / 1024:.1f} MB")

    # Step 8: Generate thumbnail (footage frame + branded overlay) and story
    from src.render.reel_thumbnail import render_thumbnail
    from src.render.reel_story import render_story
    from src.content.reel_caption import build_reel_caption

    story_title = make_title(claim, ftopic, reel_title=fact.get("reel_title"))

    frame_jpg     = out_dir / "thumbnail_frame.jpg"
    thumbnail_png = out_dir / "thumbnail.png"
    story_png     = out_dir / "story.png"

    print("\nExtracting footage frame for thumbnail...")
    # Pull a frame from the ESTABLISHING clip at 1.0s — clean, on-subject still.
    _sp.run([
        "ffmpeg", "-y",
        "-ss", "1.0",
        "-i", str(footage_clips[0]),
        "-vframes", "1",
        "-q:v", "2",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        str(frame_jpg),
    ], check=True, capture_output=True)
    print(f"  [frame] {frame_jpg.name} ({frame_jpg.stat().st_size // 1024}KB)")

    print("Compositing thumbnail (footage frame + branded overlay)...")
    render_thumbnail(
        title=story_title or claim.split(".")[0],
        topic=ftopic,
        out_path=thumbnail_png,
        frame_path=frame_jpg,
    )

    print("Rendering story asset...")
    render_story(
        title=story_title or claim.split(".")[0],
        topic=ftopic,
        out_path=story_png,
        frame_path=frame_jpg,
    )

    caption = build_reel_caption(
        claim, ftopic,
        reel_title=story_title,
        sources=fact.get("sources", []),
    )
    print(f"  caption: {len(caption)} chars")

    if dry_run:
        print("\nDRY-RUN — skipping upload and publish.")
        print(f"  Video:     open {final_mp4}")
        print(f"  Thumbnail: open {thumbnail_png}")
        print(f"  Story:     open {story_png}")
        print(f"  Caption preview:\n---\n{caption}\n---")
        return 0

    # Final duplicate re-check just before publish — closes the race window
    # between the early gate and now (in case a parallel publish_due ran).
    from src.brain import DuplicatePostError
    try:
        brain.assert_no_duplicate([claim])
    except DuplicatePostError as e:
        print(f"\nABORTED at publish-time — duplicate block:\n{e}")
        brain.append_log(f"reel BLOCKED at publish — duplicate claim: {claim[:80]}")
        return 8

    # Step 9: Upload video + thumbnail
    from src.publish.image_host import make_image_host
    from src.publish.instagram_publisher import InstagramGraphPublisher

    print("\nUploading video...")
    try:
        video_url = _upload_video(final_mp4)
    except RuntimeError as exc:
        print(f"\nVideo upload failed: {exc}")
        brain.append_log(f"reel FAILED video upload — fact={claim[:60]!r} error={exc}")
        return 6

    print("Uploading thumbnail...")
    try:
        img_host = make_image_host()
        thumbnail_result = img_host.upload(thumbnail_png)
        cover_url = thumbnail_result.public_url
        print(f"  [thumbnail] {cover_url[:80]}")
    except Exception as exc:
        print(f"  [thumbnail] upload failed ({exc}) — publishing without cover")
        cover_url = None

    # Step 10: Publish Reel — adaptive quality: if Meta 413s, recompress and retry
    print("\nPublishing Reel to Instagram...")
    publisher = InstagramGraphPublisher(
        account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
        access_token=cfg.env["META_ACCESS_TOKEN"],
        graph_version=cfg.env["META_GRAPH_VERSION"],
        host=cfg.env["META_GRAPH_HOST"],
    )

    result = None
    for _attempt, (_crf, _rate) in enumerate([(None, None), (30, "800k"), (32, "600k")]):
        if _attempt > 0:
            print(f"  [adaptive] 413 on attempt {_attempt} — recompressing at crf={_crf}...")
            _compressed = _recompress(final_mp4, crf=_crf, maxrate=_rate)
            try:
                video_url = _upload_video(_compressed)
            except RuntimeError as _exc:
                print(f"  [adaptive] re-upload failed: {_exc}")
                break
        result = publisher.publish_reel(
            video_url=video_url,
            caption=caption,
            cover_url=cover_url,
        )
        if result.get("ok"):
            break
        if not result.get("size_error"):
            break  # non-size error — recompressing won't help

    if not result or not result.get("ok"):
        err = (result or {}).get("error", "unknown")
        print(f"\nReel publish failed: {err}")
        brain.append_log(
            f"reel FAILED publish — fact={claim[:60]!r} topic={ftopic} "
            f"video_url={video_url[:60]} error={str(err)[:200]}"
        )
        return 7

    ig_media_id = result["ig_media_id"]
    print(f"\nREEL PUBLISHED — ig_media_id: {ig_media_id}")

    # Step 11: Post Story
    print("\nUploading story image...")
    try:
        story_result = img_host.upload(story_png)
        story_url = story_result.public_url
        print(f"  [story] {story_url[:80]}")
        story_pub = publisher.post_to_stories(image_url=story_url)
        if story_pub.get("ok"):
            print(f"  [story] published ig_media_id={story_pub['ig_media_id']}")
            if story_pub.get("warning"):
                print(f"  [story] note: {story_pub['warning']}")
        else:
            print(f"  [story] publish failed: {story_pub.get('error')} (Reel is still live)")
    except Exception as exc:
        print(f"  [story] failed ({exc}) — Reel is still live")

    # Step 12: Record
    _record(reel_id, ig_media_id, claim, ftopic, out_dir,
            thumbnail_png=thumbnail_png, story_png=story_png)
    return 0


def _record(
    reel_id: str,
    ig_media_id: str,
    claim: str,
    topic: str,
    out_dir: Path,
    *,
    thumbnail_png: Path | None = None,
    story_png: Path | None = None,
) -> None:
    """Persist the Reel to the ledger and brain log.

    Order matters. The reel-specific record (reels.jsonl) is the canonical
    artefact pointer (cache dir, thumbnail, story). The shared posted.jsonl
    is the dedup pool. We write reels.jsonl FIRST so a mid-write crash never
    leaves a posted entry without its reel record. (Crash before either =
    fact is still pickable next run; crash between writes = at worst a dup
    block, never a lost reel.)
    """
    import hashlib as _h
    claim_hash = _h.sha1(claim.lower().strip().encode()).hexdigest()
    reel_record = {
        "reel_id":       reel_id,
        "ig_media_id":   ig_media_id,
        "claim":         claim,
        "claim_hash":    claim_hash,
        "topic":         topic,
        "published_at":  datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "out_dir":       str(out_dir),
        "thumbnail_png": str(thumbnail_png) if thumbnail_png else None,
        "story_png":     str(story_png) if story_png else None,
    }
    from src.core.paths import REELS_LEDGER
    ledger = REELS_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish append: open with O_APPEND, single write, fsync.
    import os as _os
    line = json.dumps(reel_record) + "\n"
    fd = _os.open(str(ledger), _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT, 0o644)
    try:
        _os.write(fd, line.encode("utf-8"))
        _os.fsync(fd)
    finally:
        _os.close(fd)
    print(f"Recorded in {ledger}")

    # Then mirror into shared dedup pool (carousels + future reels).
    brain.record_publish(
        post_id=reel_id,
        ig_media_id=ig_media_id,
        slides=[{"claim": claim, "topic": topic, "category": "REEL", "sources": []}],
    )
    brain.append_log(
        f"reel {reel_id} published ({topic}, ig_media={ig_media_id})"
    )


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and publish a factjot Reel")
    parser.add_argument("--topic", default=None, help="Restrict to: space, nature, ocean, history, tech, earth")
    parser.add_argument("--dry-run", action="store_true", help="Compose video but skip upload + publish")
    parser.add_argument("--list-facts", action="store_true", help="List available quirky_score=3 facts and exit")
    parser.add_argument("--voice", default="en-GB-RyanNeural",
                        help="Edge TTS voice. Defaults to en-GB-RyanNeural (British male). "
                             "Other good picks: en-US-AndrewMultilingualNeural, en-US-BrianNeural, "
                             "en-GB-ThomasNeural, en-GB-SoniaNeural (female).")
    args = parser.parse_args()

    if args.list_facts:
        all_q3 = [r for r in load_all_facts() if r.get("quirky_score", 0) == 3]
        if args.topic:
            all_q3 = [r for r in all_q3 if r["topic"] == args.topic]
        print(f"\n{len(all_q3)} quirky_score=3 facts:")
        for r in all_q3:
            used = "(used)" if brain.is_fact_posted(r["claim"]) else ""
            print(f"  [{r['topic']}] {r['claim'][:90]} {used}")
        return 0

    return make_reel(topic=args.topic, dry_run=args.dry_run, voice=args.voice)


if __name__ == "__main__":
    sys.exit(main())
