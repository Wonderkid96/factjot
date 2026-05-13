"""Generate and publish a factjot Reel from a Claude-authored script.

End-to-end pipeline:
    1.  Take the autonomous agent's --script + --title (legacy fact-bank
        selection retired in audit Phase G.1; --script is mandatory).
    2.  Find portrait footage via multi-source video_finder.
    3.  Synthesise voice-over via ElevenLabs (edge-tts fallback).
    4.  Render PNG overlay frames (category label, hook text, fact chunks, CTA, logo).
    5.  Compose final 1080x1920 MP4 via FFmpeg.
    6.  Upload MP4 to tmpfiles.org (1-hr public URL, Meta fetches within polling window).
    7.  Publish as IG Reel via Graph API.
    8.  Record in brain + log.

Usage (manual smoke runs):
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 -u pipelines/reel/make_reel.py \\
        --script "..." --title "..." --topic earth --dry-run

The autonomous workflow calls this via the agent's `run_reel` tool, which
always supplies --script and --title.

Logs (each full run): output/reel/<reel_id>/pipeline.log and logs/reel_runs/<UTC>_<reel_id>.log
Stale local jobs: scripts/kill_local_reel_jobs.sh
Only one local encoder at a time: second run exits 10 (fcntl lock on output/reel/.make_reel.lock).
Each run removes prior reel build directories under output/reel/ so no footage or frames are reused
from an older run (ledger files under data/ledgers/ are unchanged; they only record what already posted).
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

sys.path.append(str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

from src.brain import brain
from src.core.config import load_config
from src.render.reel_composer import (
    OverlayFrame,
    compose,
    FADE_TO_BLACK_S,
    INTRO_S,
    n_clips_for_duration,
)
from src.render.reel_text_renderer import (
    ReelTextRenderer,
    TextFrame,
)
from src.content.reel_title import make_title
from src.render.tts_engine import group_into_chunks, synthesise
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
# TTS voice resolution
# ------------------------------------------------------------------ #
# Single source of truth for "which voice will this reel use?". The
# autonomous workflow writes ELEVENLABS_VOICE from a GitHub Secret;
# this helper makes that the binding decision when TTS_BACKEND is
# elevenlabs (the default). The `--voice` CLI flag is only used by
# local CLI runs that opt into edge-tts via TTS_BACKEND=edge.
#
# Surfacing this as a pure function so a regression test can assert
# that the env override path is wired and that the hardcoded George
# default in `src/render/tts_engine.py:55` is NEVER reached from the
# autonomous path. That regression was the root cause of the 2026-05-11
# voice confusion (where Claude inferred the production voice from a
# stale local .env that did not match the GitHub Secret).

class _TtsConfigError(RuntimeError):
    """Raised when the TTS backend requires env config that is missing."""


def _resolve_tts_voice(cli_voice: str) -> tuple[str, str]:
    """Resolve the TTS voice + backend at runtime.

    Returns (resolved_voice, backend). When TTS_BACKEND=elevenlabs
    (the default), ELEVENLABS_VOICE env overrides `cli_voice` and is
    the authoritative value. When TTS_BACKEND=edge, `cli_voice` is
    returned as-is.

    Raises _TtsConfigError when TTS_BACKEND=elevenlabs but
    ELEVENLABS_API_KEY or ELEVENLABS_VOICE is missing or blank.
    """
    backend = os.getenv("TTS_BACKEND", "elevenlabs")
    if backend == "elevenlabs":
        el_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        el_voice = os.getenv("ELEVENLABS_VOICE", "").strip()
        if not el_key:
            raise _TtsConfigError(
                "ELEVENLABS_API_KEY missing while TTS_BACKEND=elevenlabs"
            )
        if not el_voice:
            raise _TtsConfigError(
                "ELEVENLABS_VOICE missing while TTS_BACKEND=elevenlabs"
            )
        return el_voice, backend
    return cli_voice, backend


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


# Still inputs passed directly to FFmpeg (no video track) must not use a
# late seek; some builds error on -ss 1.0 for a single-frame source.
_THUMB_STILL_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})


_IG_COVER_TARGET_BYTES = 450 * 1024  # IG Reels cover_url hard cap is ~0.5MB; 0.45MB gives margin.


def _shrink_thumbnail_to_ig_jpeg(src_png: Path, dst_jpg: Path) -> None:
    """Convert a rendered thumbnail PNG to a single IG-compliant JPEG.

    IG Reels cover_url accepts JPEG only and rejects images over ~0.5MB.
    YouTube's 2MB cap is looser, so the IG-shaped JPEG works for both
    surfaces (Phase E.4 "one asset, two surfaces"). Tries q=85 -> q=75 ->
    q=65 to land under the IG cap. The PNG is kept on disk for archive
    and dry-run preview; the JPEG is what ships.

    Raises RuntimeError if Pillow is missing or every quality pass still
    overshoots the cap — the caller treats that as a hard reel failure
    rather than silently uploading a too-large file IG would discard.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to shrink the thumbnail to an IG-compliant JPEG"
        ) from exc

    last_size = -1
    for quality in (85, 75, 65):
        with Image.open(src_png) as im:
            im.convert("RGB").save(
                dst_jpg, format="JPEG", quality=quality,
                optimize=True, progressive=True,
            )
        last_size = dst_jpg.stat().st_size
        if last_size <= _IG_COVER_TARGET_BYTES:
            print(
                f"  [thumbnail-jpg] q={quality} {last_size // 1024}KB "
                f"(<= {_IG_COVER_TARGET_BYTES // 1024}KB)"
            )
            return
    raise RuntimeError(
        f"thumbnail JPEG still {last_size // 1024}KB after q=65; "
        f"target <= {_IG_COVER_TARGET_BYTES // 1024}KB"
    )


def _extract_reel_thumbnail_frame(
    ffmpeg_bin: str,
    thumb_src: Path,
    frame_jpg: Path,
) -> None:
    """Extract one full-portrait JPG for the branded thumbnail and story.

    Tries multiple start times for real video (short clips can fail at 1s).
    Raises RuntimeError only if every attempt fails.
    """
    import subprocess

    is_still = thumb_src.suffix.lower() in _THUMB_STILL_EXTS
    seek_sequence = ("0",) if is_still else ("1.0", "0.5", "0.25", "0")
    last_err: Exception | None = None
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"

    for seek in seek_sequence:
        frame_jpg.unlink(missing_ok=True)
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", seek,
            "-i", str(thumb_src),
            "-vframes", "1",
            "-q:v", "2",
            "-vf", vf,
            str(frame_jpg),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_err = exc
            continue
        if frame_jpg.is_file() and frame_jpg.stat().st_size > 512:
            if seek != seek_sequence[0]:
                print(f"  [frame] used -ss {seek}s (fallback)")
            return
        last_err = RuntimeError(f"thumbnail frame too small after -ss {seek}")

    tail = ""
    if isinstance(last_err, subprocess.CalledProcessError):
        tail = (last_err.stderr or b"").decode("utf-8", errors="replace")[-400:]
    raise RuntimeError(
        f"could not extract thumbnail frame from {thumb_src.name}: {last_err!r} {tail}"
    ) from last_err


def _recompress(
    src: Path,
    crf: int = 30,
    maxrate: str = "800k",
    *,
    ffmpeg_bin: str,
) -> Path:
    """Return a smaller re-encoded copy of the MP4 for 413 fallback."""
    import subprocess
    out = src.with_suffix(f".crf{crf}.mp4")
    subprocess.run([
        ffmpeg_bin, "-y", "-i", str(src),
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

def _pick_music(topic: str, tone: str = "curious") -> Path | None:
    music_dir = Path(__file__).resolve().parents[2] / "assets" / "music"

    # Mood map: (topic, tone) -> preferred filename stem, then fallbacks.
    # Tracks live in assets/music/ as {stem}.mp3.
    # Priority: exact topic+tone > topic-only > tone-only > default.
    _MOOD_MAP: dict[tuple[str, str], str] = {
        ("history",    "shocking"): "dark",
        ("history",    "sober"):    "sober",
        ("history",    "curious"):  "investigations",
        ("space",      "curious"):  "ambient_space",
        ("space",      "shocking"): "dark",
        ("ocean",      "curious"):  "ambient_ocean",
        ("ocean",      "shocking"): "dark",
        ("biology",    "curious"):  "investigations",
        ("biology",    "shocking"): "dark",
        ("earth",      "curious"):  "ambient_earth",
        ("earth",      "shocking"): "dark",
        ("technology", "curious"):  "investigations",
        ("technology", "shocking"): "dark",
        ("science",    "curious"):  "investigations",
        ("science",    "shocking"): "dark",
    }
    _TONE_FALLBACK: dict[str, str] = {
        "shocking":   "dark",
        "sober":      "sober",
        "curious":    "investigations",
        "wholesome":  "ambient_earth",
    }

    candidates = []
    exact = _MOOD_MAP.get((topic, tone))
    if exact:
        candidates.append(music_dir / f"{exact}.mp3")
    tone_fb = _TONE_FALLBACK.get(tone)
    if tone_fb:
        candidates.append(music_dir / f"{tone_fb}.mp3")
    candidates += [
        music_dir / f"{topic}.mp3",
        music_dir / "default.mp3",
    ]
    for c in candidates:
        if c.exists():
            return c
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.webm"))
    return tracks[0] if tracks else None


# ------------------------------------------------------------------ #
# Footage dedup ledger
# ------------------------------------------------------------------ #

def _append_footage_ledger(
    *,
    dry_run: bool,
    ledger_path: Path,
    registry: set[str],
    footage_clips: list[Path],
    reel_id: str,
    reel_title: str,
    topic: str,
) -> bool:
    """Append used-footage entries for a successful reel.

    DRY-RUN does not write — preview renders must not permanently mark
    footage as used. Existing keys (url, filename, reel_id) are kept for
    backwards compatibility; new optional metadata is additive.

    Returns True if the ledger was written, False on dry-run skip.
    """
    if dry_run:
        print("  [footage] DRY-RUN — not writing footage dedup ledger")
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as fh:
        for url in sorted(registry):
            entry: dict = {
                "url": url,
                "reel_id": reel_id,
                "reel_title": reel_title,
                "topic": topic,
                "published_at": now_iso,
            }
            # Provider-prefixed registry entries (e.g. "pexels:12345") carry
            # the provider and id; raw http(s) URLs do not.
            if ":" in url and not url.startswith(("http://", "https://")):
                provider, _, vid_id = url.partition(":")
                if provider and vid_id:
                    entry["provider"] = provider
                    entry["provider_video_id"] = vid_id
            fh.write(json.dumps(entry) + "\n")
        for clip in footage_clips:
            fh.write(json.dumps({
                "filename": clip.stem,
                "reel_id": reel_id,
                "reel_title": reel_title,
                "topic": topic,
                "published_at": now_iso,
            }) + "\n")
    return True


# ------------------------------------------------------------------ #
# Main pipeline
# ------------------------------------------------------------------ #

def make_reel(topic: str | None, dry_run: bool, voice: str = "en-GB-RyanNeural",
              _autonomous: dict | None = None) -> int:
    """Run the reel pipeline.

    _autonomous: if provided, bypasses fact selection entirely and uses the
    supplied dict as the fact. Must contain: claim, reel_script, reel_title,
    topic, tone, image_hint. Used by make_autonomous_reel.py.
    """
    configure_logging()
    cfg = load_config()

    from src.core.paths import REELS_CACHE, REEL_RUN_LOGS, ensure_dirs
    from src.utils.reel_run_logger import (
        ReelRunLogger,
        acquire_local_make_reel_lock,
        release_local_make_reel_lock,
    )

    _locked = False
    rlog = None
    try:
        try:
            acquire_local_make_reel_lock(REELS_CACHE)
        except RuntimeError as exc:
            print(f"\n{exc}")
            return 10
        _locked = True

        from src.core.ffmpeg_bin import assert_reel_ffmpeg_ready

        try:
            ff_bin = assert_reel_ffmpeg_ready()
        except RuntimeError as exc:
            print(f"\n{exc}")
            return 5
        print(f"  [ffmpeg] binary: {ff_bin}")

        # Step 1: Use autonomously generated content. The legacy fact-bank
        # selection path (_pick_fact) was retired in audit Phase G.1: the
        # autonomous agent always supplies --script via run_reel, so callers
        # without a script are misuse, not a fallback.
        if _autonomous is None:
            print(
                "ERROR: --script is required. The autonomous flow always "
                "passes it; manual runs must too. See pipelines/reel/make_reel.py --help."
            )
            return 12
        fact = _autonomous
        print(f"\n[AUTONOMOUS] Claude-generated reel")

        claim    = fact["claim"]
        ftopic   = fact["topic"]
        hint     = fact.get("image_hint", "")
        # Include a timestamp so every run gets a unique cache directory.
        # Without this, re-running the same fact reuses the same cache dir
        # and serves stale footage from a previous test or deleted reel.
        import time as _t, os as _os
        reel_id  = hashlib.sha1(
            f"reel:{ftopic}:{claim}:{_t.time_ns()}:{_os.urandom(4).hex()}".encode()
        ).hexdigest()[:14]
        out_dir  = REELS_CACHE / reel_id
        # Fresh tree every run: remove all previous build dirs under output/reel/
        # so video_finder downloads and FFmpeg outputs never mix with an older
        # reel_id. Advisory lock above prevents a concurrent run from deleting
        # an active directory. Preserve only the lock file.
        import shutil as _sh
        REELS_CACHE.mkdir(parents=True, exist_ok=True)
        _lock_keep = ".make_reel.lock"
        for _entry in list(REELS_CACHE.iterdir()):
            if _entry.name == _lock_keep:
                continue
            if _entry.is_dir():
                _sh.rmtree(_entry, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        print(
            f"  [cache] clean reel workspace -> {out_dir} "
            f"(removed other build dirs under {REELS_CACHE})"
        )
        ensure_dirs()
        rlog = ReelRunLogger(reel_id=reel_id, out_dir=out_dir, run_logs_dir=REEL_RUN_LOGS)
        rlog.emit(f"dry_run={dry_run} voice={voice!r}")
        rlog.emit(f"topic={ftopic} claim={claim[:200]!r}")
        rlog.emit(f"cache_dir={out_dir}")
        rlog.emit("FFmpeg compose logs: ffmpeg_debug.txt + ffmpeg_compose_stderr.log in cache dir")

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

        # Step 2: Voice-over. Autonomous scripts bypass word-count floors:
        # Claude owns quality, the legacy fact-bank floor was retired with
        # _pick_fact in Phase G.1.
        vo_body = fact.get("reel_script", "")
        print(f"\n[AUTONOMOUS] script: {len(vo_body.split())} words")

        # Append a randomised outro. Each variation contains "factjot" so the
        # compositor can sync the CTA card to the exact moment it is spoken.
        vo_script = _append_outro(vo_body)
        print(f"  outro appended — total {len(vo_script.split())} words")

        # D.1 fact verification gate. Runs BEFORE TTS so a contradictory or
        # "fictional"-framed reel is rejected for ~$0.001 instead of paying
        # the full TTS + FFmpeg + upload bill on a post that cannot ship.
        # Both checks fail-OPEN on infra issues (no api_key, Wikipedia down)
        # and fail-CLOSED on real quality issues. Print prefix matches the
        # autonomous agent's `fact_verification_failed` sentinel.
        from src.verification.fact_checker import verify_anchors, verify_consistency
        anth_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        consistency_brief = {
            "title": fact.get("reel_title", ""),
            "claim": vo_script,
        }
        consistency = verify_consistency(consistency_brief, api_key=anth_key)
        if not consistency["ok"]:
            print(
                f"ERROR: fact verification failed (consistency): "
                f"{consistency['reason']}"
            )
            brain.append_log(
                f"reel BLOCKED - fact verification (consistency): "
                f"{consistency['reason'][:80]} - claim={claim[:60]}"
            )
            return 11
        anchors = verify_anchors([vo_script], api_key=anth_key)
        if not anchors["ok"]:
            flagged = "; ".join(
                f"{f['claim'][:60]} ({f['reason']})"
                for f in anchors["flagged"][:3]
            )
            print(f"ERROR: fact verification failed (anchors): {flagged}")
            brain.append_log(
                f"reel BLOCKED - fact verification (anchors): "
                f"{flagged[:80]} - claim={claim[:60]}"
            )
            return 11

        print(f"Synthesising voice-over (voice={voice})...")
        try:
            tts_voice, tts_backend = _resolve_tts_voice(cli_voice=voice)
        except _TtsConfigError as exc:
            print(f"ERROR: {exc}")
            return 4
        if tts_backend == "elevenlabs":
            print(f"  [tts] enforcing ElevenLabs voice from env: {tts_voice}")
        mp3_path, word_beats = synthesise(vo_script, out_dir, voice=tts_voice, backend=tts_backend, tone=fact.get("tone", "curious"))
        if not word_beats:
            print("ERROR: TTS returned no word timing. Check edge-tts is installed.")
            return 4
        rlog.emit(f"TTS ok -> {mp3_path.name} ({mp3_path.stat().st_size // 1024} KB)")

        # Silent intro - hook title shows here, voice starts AFTER it fades.
        padded_mp3 = out_dir / "voice_padded.mp3"
        import subprocess as _sp
        # ElevenLabs (and many MP3 paths) are 44.1 kHz; anullsrc is 48 kHz. Raw concat
        # keeps 44.1 kHz on the muxed file (see gotchas: Meta rejects 44.1). Resample
        # both legs to 48 kHz mono before concat so voice_padded.mp3 is safe end-to-end.
        _pad_filter = (
            "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono[sil];"
            "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono[vo];"
            "[sil][vo]concat=n=2:v=0:a=1[a]"
        )
        _sp.run([
            ff_bin, "-y",
            "-f", "lavfi", "-t", str(INTRO_S), "-i", "anullsrc=r=48000:cl=mono",
            "-i", str(mp3_path),
            "-filter_complex", _pad_filter,
            "-map", "[a]",
            "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000",
            str(padded_mp3),
        ], check=True, capture_output=True)
        mp3_path = padded_mp3
        print(f"  pre-padded voice with {INTRO_S}s intro silence -> {padded_mp3.name}")

        voice_end_s = word_beats[-1].end_s + INTRO_S

        # Sync CTA to the moment the narrator says "factjot" in the outro.
        # ElevenLabs sometimes renders "factjot" as two tokens: "fact" + "jot".
        # Check for both: single word containing "factjot", or consecutive "fact"+"jot".
        _fj_beats = [b for b in word_beats if "factjot" in b.word.lower()]
        if not _fj_beats:
            for _i, _b in enumerate(word_beats[:-1]):
                _nxt = word_beats[_i + 1]
                if _b.word.lower().startswith("fact") and _nxt.word.lower().startswith("jot"):
                    _fj_beats = [_b]
                    break
        if _fj_beats:
            cta_s = _fj_beats[-1].start_s + INTRO_S
            print(f"  CTA locked to 'factjot' word beat at {cta_s:.1f}s")
        else:
            cta_s = max(0.0, voice_end_s - 3.5)
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
        # Keep a hard floor, but avoid false aborts in the 34-35s band when
        # TTS timing comes in slightly faster than expected.
        MIN_REEL_TOTAL_S = 33.5
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

        # Load global footage registry. This prevents the same clip appearing in
        # different reels. Do not auto-clear this ledger based on reels.jsonl state;
        # if a genuine reset is needed, truncate manually:
        #     : > data/ledgers/used_footage_urls.jsonl
        from src.core.paths import USED_FOOTAGE
        global_footage_registry: set[str] = set()   # blocked URLs + video IDs
        blocked_footage_filenames: set[str] = set() # blocked filename stems

        # Primary source: ledger
        if USED_FOOTAGE.exists():
            for line in USED_FOOTAGE.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "url" in entry:
                        global_footage_registry.add(entry["url"])
                    if "filename" in entry:
                        blocked_footage_filenames.add(entry["filename"])
                except Exception as exc:
                    # A corrupt ledger line silently passing through means
                    # a previously-used clip can leak back into eligibility.
                    # Surface so the corruption is fixable.
                    print(
                        f"  [footage] skipping corrupt ledger line "
                        f"({exc}): {line[:80]!r}",
                        flush=True,
                    )

        print(f"  [footage] blocking {len(blocked_footage_filenames)} URLs/IDs from previous reels (ledger)")

        footage_clips = find_videos(
            image_hint=hint, claim=claim, topic=ftopic,
            out_dir=out_dir, count=n_clips,
            allow_archival=allow_archival,
            used_source_registry=global_footage_registry,
            blocked_filenames=blocked_footage_filenames,
            reel_script=vo_body,
        )
        if not footage_clips:
            print("ERROR: could not find any footage. Pre-download safety pool clips with:")
            print("  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 pipelines/reel/setup_reel_assets.py")
            brain.append_log(f"reel FAILED no footage — fact={claim[:60]!r} hint={hint!r}")
            return 3

        rlog.emit(f"footage ok: {len(footage_clips)} clips -> {[p.name for p in footage_clips]}")

        # Step 4: Group words into 5-6 word chunks. FFmpeg segfaults beyond ~50
        # input streams on this build, so keep total inputs (footage + overlays)
        # comfortably under that limit. Larger chunks = fewer overlay PNGs.
        chunks = group_into_chunks(
            word_beats,
            words_per_line=4,
            max_chars=28,
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

        # 5d: KINETIC SUBTITLES via PNG overlays — one PNG per subtitle chunk.
        # Each chunk is a static image shown during its word-beat window.
        # Simpler than libass and avoids the ass filter deadlock on macOS ffmpeg-full.
        _sub_count = 0
        for _ci, _chunk in enumerate(chunks):
            _raw_start = _chunk[0].start_s + INTRO_S
            if _ci + 1 < len(chunks):
                _raw_end = chunks[_ci + 1][0].start_s + INTRO_S
            else:
                _raw_end = _chunk[-1].end_s + INTRO_S + 0.35
            _start = max(_raw_start, subtitle_start_gate)
            _end = min(_raw_end, cta_s - 0.05)
            if _start >= _end:
                continue
            _text = " ".join(b.word for b in _chunk)
            # Skip chunks that contain "factjot" — the CTA logo appears
            # immediately after and showing it twice is jarring.
            if "factjot" in _text.lower():
                continue
            _chunk_path = overlay_dir / f"chunk_{_ci:02d}.png"
            text_frames.append(TextFrame(style="subtitle", text=_text, out_path=_chunk_path))
            overlays.append(OverlayFrame(png=_chunk_path, start_s=_start, end_s=_end, fade_in_s=0.0, fade_out_s=0.0))
            _sub_count += 1
        print(f"  kinetic subtitles: {len(chunks)} chunks -> {_sub_count} subtitle PNGs")

        # 5e: Info line — single Space Grotesk Bold uppercase line in the upper-mid
        # zone showing "ENTITY · YEAR" (or just topic). Appears briefly early in
        # the reel to give context without competing with subtitles.
        from src.research.narrative_beats import extract_entities as _ext_ents
        import re as _re

        _claim_ents = _ext_ents(claim)
        _year_m = _re.search(r'\b(1[0-9]{3}|20[0-9]{2})\b', claim)
        _year_str = _year_m.group(0) if _year_m else ""

        # Filter proper nouns: require > 5 chars and exclude common words that
        # appear capitalised at sentence starts (Around, After, While, etc.)
        _CAPS_NOISE = {
            "around", "after", "before", "while", "which", "where", "there",
            "their", "these", "those", "every", "still", "found", "earth",
            "world", "first", "other", "since", "until", "about", "above",
        }
        _strong_nouns = [
            n for n in _claim_ents.proper_nouns
            if len(n) > 5 and n.lower() not in _CAPS_NOISE
        ]
        _entity_name = _strong_nouns[0] if _strong_nouns else ""

        _info_parts = []
        if _entity_name:
            _info_parts.append(_entity_name.upper())
        if _year_str:
            _info_parts.append(_year_str)
        if not _info_parts:
            _info_parts.append(ftopic.upper())
        _info_text = " · ".join(_info_parts)

        _info_start = INTRO_S + 0.8
        _info_end   = _info_start + 3.0
        if _info_text and _info_end < cta_s - 1.0:
            print(f"  [info] '{_info_text}' @ {_info_start:.1f}–{_info_end:.1f}s")
            _info_png = overlay_dir / "info.png"
            text_frames.append(TextFrame(style="info", text=_info_text, out_path=_info_png))
            overlays.append(OverlayFrame(png=_info_png, start_s=_info_start, end_s=_info_end, fade_in_s=0.3, fade_out_s=0.4))

        # 5f: CTA frame
        cta_path = overlay_dir / "cta.png"
        text_frames.append(TextFrame(style="cta", text="@factjot", out_path=cta_path))
        overlays.append(OverlayFrame(png=cta_path, start_s=cta_s, end_s=total_dur, fade_in_s=0.4, fade_out_s=0.0))

        # Single Playwright session renders everything
        print(f"  rendering {len(text_frames)} text frames via Playwright...")
        renderer = ReelTextRenderer()
        renderer.render_all(text_frames)

        # Step 6: Music — random start point so every Reel sounds different
        music_path = _pick_music(ftopic, tone=fact.get("tone", "curious"))
        if music_path:
            print(f"  music: {music_path.name}")
        else:
            print("  music: none found")

        # Step 7: Compose
        print("\nComposing video (FFmpeg)...")
        rlog.emit("starting FFmpeg compose (see ffmpeg_compose_stderr.log in cache dir)")
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
                ffmpeg_bin=ff_bin,
            )
        except RuntimeError as exc:
            print(f"\nFFmpeg error:\n{exc}")
            brain.append_log(f"reel FAILED ffmpeg — fact={claim[:60]!r} error={str(exc)[:300]}")
            return 5

        # Persist footage dedup ledger — log both URLs and filenames so future
        # reels can block by content (filename) not just by source URL.
        # DRY-RUN does NOT write (see _append_footage_ledger).
        _append_footage_ledger(
            dry_run=dry_run,
            ledger_path=USED_FOOTAGE,
            registry=global_footage_registry,
            footage_clips=list(footage_clips),
            reel_id=reel_id,
            reel_title=fact.get("reel_title") or "",
            topic=ftopic,
        )

        print(f"\nReel composed: {final_mp4}")
        print(f"  size: {final_mp4.stat().st_size / 1024 / 1024:.1f} MB")
        rlog.emit(
            f"compose done -> {final_mp4.name} {final_mp4.stat().st_size / 1024 / 1024:.1f} MB"
        )

        # Phase F (Q7): higher-bitrate variant for YouTube. The Meta-shaped
        # `final.mp4` is encoded for the 5 MB URL-fetch ceiling; YouTube has
        # no such ceiling and rewards a sharper upload. We re-encode the
        # already-composed MP4 (keeping the same filter graph + audio) at
        # crf 22 / maxrate 4M so the second pass costs ~5-10s, not a full
        # re-render. Soft-fail: if this pass errors the upload script falls
        # back to `final.mp4` (legacy behaviour).
        youtube_mp4: Path | None = out_dir / "final_youtube.mp4"
        youtube_encode_cmd = [
            ff_bin,
            "-i", str(final_mp4),
            "-c:v", "libx264",
            "-crf", "22",
            "-maxrate", "4M",
            "-bufsize", "8M",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y", str(youtube_mp4),
        ]
        try:
            import subprocess as _yt_sp
            _yt_sp.run(
                youtube_encode_cmd,
                check=True,
                capture_output=True,
                timeout=120,
            )
            yt_kb = youtube_mp4.stat().st_size // 1024
            print(f"  [encode] YouTube variant: {youtube_mp4.name} ({yt_kb} KB)")
            rlog.emit(
                f"YouTube variant encoded -> {youtube_mp4.name} ({yt_kb} KB)"
            )
        except Exception as exc:
            print(f"  [encode] YouTube variant failed (non-fatal): {exc}")
            rlog.emit(f"YouTube variant FAILED (non-fatal): {str(exc)[:200]}")
            youtube_mp4 = None

        # Step 8: Generate thumbnail (Haiku-picked frame + brand overlay) and story
        # E.4 (2026-05-10): the previous footage_clips[0] heuristic is replaced
        # with thumbnail_picker.pick_best_thumbnail (3 candidate frames, scored
        # by Haiku 4.5 vision). The chosen frame is then rendered via the
        # story template (full-bleed frame + centred Archivo Black headline
        # + red "New Reel" pill). The same story-style asset feeds the IG
        # Reel cover, the YouTube Short cover, and the IG Stories crosspost.
        from src.render.reel_story import render_story
        from src.content.reel_caption import build_reel_caption
        from src.render.thumbnail_picker import pick_best_thumbnail

        story_title = make_title(claim, ftopic, reel_title=fact.get("reel_title"))

        frame_jpg     = out_dir / "thumbnail_frame.jpg"
        thumbnail_png = out_dir / "thumbnail.png"
        thumbnail_jpg = out_dir / "thumbnail.jpg"
        story_png     = out_dir / "story.png"

        # When footage_clips[0] is a still, prefer the pre-rendered MP4
        # for the picker so frame extraction is consistent across mixed
        # footage. Stills get seek=0 anyway via the planner.
        picker_clips: list[Path] = []
        for fc in footage_clips:
            if fc.suffix.lower() in _THUMB_STILL_EXTS:
                _still_rendered = out_dir / f"still_rendered_{fc.stem}.mp4"
                picker_clips.append(
                    _still_rendered if _still_rendered.exists() else fc
                )
            else:
                picker_clips.append(fc)

        print("\nExtracting + scoring 3 candidate thumbnail frames...")
        cand_dir = out_dir / "thumb_candidates"
        anth_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        try:
            chosen_frame, picker_meta = pick_best_thumbnail(
                footage_clips=picker_clips,
                claim=claim,
                reel_title=story_title or "",
                api_key=anth_key,
                candidate_dir=cand_dir,
                ffmpeg_bin=ff_bin,
            )
        except RuntimeError as exc:
            print(f"\nERROR: reel FAILED thumbnail picker: {exc}")
            brain.append_log(
                f"reel FAILED thumbnail picker — fact={claim[:60]!r} "
                f"error={str(exc)[:300]}"
            )
            return 9

        # Persist the chosen frame as thumbnail_frame.jpg for downstream use
        # (story renderer + debug). Keep the original PNG too under
        # thumb_candidates/ for ledger archaeology.
        try:
            from PIL import Image
            with Image.open(chosen_frame) as im:
                im.convert("RGB").save(frame_jpg, format="JPEG", quality=92)
        except Exception as exc:
            # Soft-fall: copy the PNG bytes if PIL is missing or fails.
            print(f"  [thumb] PIL JPEG conversion failed ({exc}); copying PNG bytes")
            frame_jpg.write_bytes(chosen_frame.read_bytes())
        print(
            f"  [frame] chosen={chosen_frame.name} -> {frame_jpg.name} "
            f"({frame_jpg.stat().st_size // 1024}KB) "
            f"haiku_cost=${picker_meta.get('total_cost_usd', 0.0):.5f}"
        )

        # Cover + story share the story-style layout: full-bleed frame,
        # centred Archivo Black headline (full reel title), red "New Reel"
        # pill. The IG Reel cover, the YouTube Short cover, and the IG
        # Stories crosspost are all rendered from reel_story.html.j2 so
        # the three surfaces stay visually consistent.
        print("Rendering thumbnail (story-style cover)...")
        render_story(
            title=story_title or claim.split(".")[0],
            topic=ftopic,
            out_path=thumbnail_png,
            frame_path=frame_jpg,
        )

        # IG Reels cover_url accepts JPEG only and is hard-capped under
        # ~0.5MB. YouTube's 2MB cap is looser. Emit one IG-compliant JPEG
        # so both surfaces consume the same artefact. YouTube prefers
        # thumbnail.jpg when present and falls back to PNG-conversion only
        # for older runs.
        _shrink_thumbnail_to_ig_jpeg(thumbnail_png, thumbnail_jpg)

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
            rlog.emit("DRY-RUN finished (no upload/publish)")
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

        if not thumbnail_png.is_file() or thumbnail_png.stat().st_size < 1000:
            print("\nERROR: reel FAILED thumbnail — PNG missing or too small after render")
            brain.append_log(f"reel FAILED thumbnail file — fact={claim[:60]!r}")
            return 9
        if not thumbnail_jpg.is_file() or thumbnail_jpg.stat().st_size < 1000:
            print("\nERROR: reel FAILED thumbnail — JPEG missing or too small after shrink")
            brain.append_log(f"reel FAILED thumbnail jpeg — fact={claim[:60]!r}")
            return 9

        print("Uploading thumbnail...")
        img_host = make_image_host()
        cover_url = None
        for attempt in (1, 2):
            try:
                thumbnail_result = img_host.upload(thumbnail_jpg)
                cover_url = thumbnail_result.public_url
                print(f"  [thumbnail] {cover_url[:80]}")
                break
            except Exception as exc:
                print(f"  [thumbnail] upload failed (attempt {attempt}/2): {exc}")
                if attempt == 1:
                    time.sleep(2.0)
                else:
                    print("  [thumbnail] publishing without cover (IG auto-picks frame)")

        # Step 10: Publish Reel
        # compose() already handles size: crf 23 first pass, two-pass VBR if >4.7MB.
        # The 413 retry loop below is a last-resort safety net only.
        print("\nPublishing Reel to Instagram...")
        publisher = InstagramGraphPublisher(
            account_id=cfg.env["INSTAGRAM_ACCOUNT_ID"],
            access_token=cfg.env["META_ACCESS_TOKEN"],
            graph_version=cfg.env["META_GRAPH_VERSION"],
            host=cfg.env["META_GRAPH_HOST"],
            # Defence-in-depth: the publisher itself re-reads the dedup
            # ledger from disk just before the Graph API call, so any
            # path that reaches publish_reel without a caller-level
            # check still cannot post a duplicate. (Audit R6.)
            dedup_check=brain.assert_no_duplicate,
        )

        result = None
        for _attempt, (_crf, _rate) in enumerate([(None, None), (33, "600k"), (35, "500k")]):
            if _attempt > 0:
                print(f"  [adaptive] 413 on attempt {_attempt} — recompressing at crf={_crf}...")
                _compressed = _recompress(final_mp4, crf=_crf, maxrate=_rate, ffmpeg_bin=ff_bin)
                try:
                    video_url = _upload_video(_compressed)
                except RuntimeError as _exc:
                    print(f"  [adaptive] re-upload failed: {_exc}")
                    break
            result = publisher.publish_reel(
                video_url=video_url,
                caption=caption,
                cover_url=cover_url,
                dedup_subjects=[claim],
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
        rlog.emit(f"REEL PUBLISHED ig_media_id={ig_media_id}")

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
        _record(
            reel_id,
            ig_media_id,
            claim,
            ftopic,
            out_dir,
            thumbnail_png=thumbnail_png,
            story_png=story_png,
            tone=fact.get("tone", "curious"),
            reel_title=fact.get("reel_title", ""),
            subject_key=fact.get("subject_key", ""),
            word_count=len(vo_script.split()),
            caption=caption,
            # Telemetry: True when both thumbnail upload attempts failed
            # and the reel shipped letting IG auto-pick a frame. Lets us
            # query "how many reels lost their custom thumbnail" without
            # re-parsing the workflow log (which masks/expires).
            cover_missing=(cover_url is None),
        )
        return 0

    finally:
        if rlog is not None:
            try:
                rlog.emit("=== pipeline: end (finally) ===")
            except Exception:
                pass
            rlog.close()
        if _locked:
            release_local_make_reel_lock()


def _record(
    reel_id: str,
    ig_media_id: str,
    claim: str,
    topic: str,
    out_dir: Path,
    *,
    thumbnail_png: Path | None = None,
    story_png: Path | None = None,
    tone: str = "curious",
    reel_title: str = "",
    subject_key: str = "",
    word_count: int = 0,
    caption: str = "",
    cover_missing: bool = False,
) -> None:
    """Persist the Reel to the ledger and brain log.

    Order matters. The reel-specific record (reels.jsonl) is the canonical
    artefact pointer (cache dir, thumbnail, story). The shared posted.jsonl
    is the dedup pool. We write reels.jsonl FIRST so a mid-write crash never
    leaves a posted entry without its reel record. (Crash before either =
    fact is still pickable next run; crash between writes = at worst a dup
    block, never a lost reel.)
    """
    from src.brain import claim_hash as _claim_hash
    claim_hash_val = _claim_hash(claim)
    # Capture the slot context so the performance ledger can answer
    # "which slot performs best" without a backfill (audit Phase H.2).
    # POST_MODE is set by the autonomous workflow; for local manual runs
    # without a slot context the field defaults to `unknown`.
    slot = (os.environ.get("POST_MODE", "") or "").strip() or "unknown"
    reel_record = {
        "reel_id":       reel_id,
        "ig_media_id":   ig_media_id,
        "claim":         claim,
        "claim_hash":    claim_hash_val,
        "topic":         topic,
        "tone":          tone,
        "reel_title":    reel_title,
        "word_count":    word_count,
        "slot":          slot,
        "published_at":  datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "out_dir":       str(out_dir),
        "thumbnail_png": str(thumbnail_png) if thumbnail_png else None,
        "story_png":     str(story_png) if story_png else None,
        "caption":       caption,
    }
    # Only write the flag when it actually fired - keeps the common
    # success-case ledger rows compact.
    if cover_missing:
        reel_record["cover_missing"] = True
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
    # Pass through reel_title so the title-based subject fingerprint in
    # autonomous_agent.build_history_summary works for reel entries read
    # from posted.jsonl (not just reels.jsonl).
    brain.record_publish(
        post_id=reel_id,
        ig_media_id=ig_media_id,
        slides=[{
            "claim":      claim,
            "topic":      topic,
            "category":   "REEL",
            "sources":    [],
            "reel_title": reel_title,
        }],
        subject_key=subject_key,
    )
    brain.append_log(
        f"reel {reel_id} published ({topic}, ig_media={ig_media_id})"
    )


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and publish a factjot Reel")
    parser.add_argument(
        "--topic",
        default=None,
        help="Topic tag for the reel. One of: space, nature, ocean, history, tech, earth, biology, technology, science.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compose video but skip upload + publish")
    parser.add_argument("--force", action="store_true", help="Bypass today's duplicate guard (use when posting a second reel intentionally)")
    parser.add_argument("--voice", default="en-GB-RyanNeural",
                        help="Edge TTS voice. Defaults to en-GB-RyanNeural (British male). "
                             "Other good picks: en-US-AndrewMultilingualNeural, en-US-BrianNeural, "
                             "en-GB-ThomasNeural, en-GB-SoniaNeural (female).")
    # Autonomous agent flags — script + title are mandatory after Phase G.1
    # retired the legacy fact-bank selection path.
    parser.add_argument("--script", default=None,
                        help="Voice-over script for the reel. REQUIRED. The autonomous agent supplies this via run_reel.")
    parser.add_argument("--title", default=None,
                        help="Hook card title for the reel. REQUIRED with --script.")
    parser.add_argument("--hint", default=None,
                        help="Image hint for footage search (used with --script).")
    parser.add_argument("--tone-override", default="curious",
                        choices=["shocking", "curious", "sober", "wholesome"],
                        help="Tone override for TTS voice settings (used with --script).")
    parser.add_argument("--subject-key", default="",
                        help="Canonical subject key for permanent dedup (e.g. 'radium-girls').")
    args = parser.parse_args()

    # Per-day reel cap removed: the autonomous agent is now the single
    # poster and runs its own duplicate guard via the post bank summary.
    # Capping reels at 1/day here prevented legitimate format choices
    # made after a same-day blocked attempt.

    if not args.script:
        print(
            "ERROR: --script is required (autonomous flow always passes it; "
            "manual runs must too)."
        )
        return 12
    if not args.title:
        print("ERROR: --script requires --title")
        return 1

    autonomous_fact = {
        "claim":        args.script[:300],
        "reel_script":  args.script,
        "reel_title":   args.title,
        "topic":        args.topic or "history",
        "tone":         args.tone_override,
        "image_hint":   args.hint or "",
        "quirky_score": 3,
        "allow_archival": False,
        "sources":      [],
        "autonomous":   True,
        "subject_key":  args.subject_key or "",
    }
    return make_reel(topic=None, dry_run=args.dry_run, voice=args.voice,
                     _autonomous=autonomous_fact)


if __name__ == "__main__":
    sys.exit(main())
