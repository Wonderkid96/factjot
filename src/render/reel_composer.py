"""FFmpeg-based Reel video composer.

New (multi-clip) pipeline:
  - Takes a LIST of footage clips.
  - Each clip is scaled+cropped to 1080x1920 then ken-burns zoomed.
  - Clips are concatenated with hard cuts at deterministic timestamps
    spread across the voice track (one cut per ~3s of body).
  - PNG overlays (category, hook, fact chunks, CTA, logo) overlay on top.
  - Voice + music ducked.

Why multi-clip cuts: a single static clip kills retention on Reels.
Cuts every 2-4s synced to the voice make the eye stay on screen.
"""
from __future__ import annotations

import os
import random
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Module-level reference to the active FFmpeg process.
# Lets signal handlers kill FFmpeg cleanly when the parent Python process
# is interrupted - prevents orphan FFmpeg processes eating CPU in the background.
_active_proc: "subprocess.Popen | None" = None


def _register_active(proc: "subprocess.Popen | None") -> None:
    global _active_proc
    _active_proc = proc


def _sigterm_handler(signum: int, frame: object) -> None:
    if _active_proc is not None:
        _active_proc.kill()
    raise SystemExit(1)


signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


def _pump_ffmpeg_stderr(
    proc: subprocess.Popen,
    *,
    stderr_buf: list[bytes],
    heartbeat_s: float = 25.0,
) -> None:
    """Copy FFmpeg stderr to sys.stderr and append raw chunks to stderr_buf.

    GitHub Actions only shows new lines when something is written. A plain
    blocking read(4096) yields no UI updates while FFmpeg spends minutes in
    filter graph init with no stderr. On POSIX we use select() with a timeout
    to emit a heartbeat so the job does not look frozen or empty.
    """
    import sys as _sys

    assert proc.stderr is not None

    def emit(chunk: bytes) -> None:
        if not chunk:
            return
        vis = chunk.replace(b"\r", b"\n")
        _sys.stderr.buffer.write(vis)
        _sys.stderr.buffer.flush()
        stderr_buf.append(chunk)

    fd = proc.stderr.fileno()

    if os.name != "posix":
        while True:
            chunk = proc.stderr.read(65536)
            if not chunk:
                break
            emit(chunk)
        return

    import select

    while True:
        r, _, _ = select.select([fd], [], [], heartbeat_s)
        if r:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            emit(chunk)
            continue
        if proc.poll() is not None:
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    return
                emit(chunk)
        _sys.stderr.buffer.write(
            b"\n[ffmpeg] still working (no stderr for a while; "
            b"normal during filter init or first frames)...\n"
        )
        _sys.stderr.buffer.flush()


_STILL_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})

_INTRO_PATH = Path(__file__).resolve().parents[2] / "assets" / "intros" / "factjot_intro.mov"


def _probe_intro_duration(path: Path, fallback: float = 1.37) -> float:
    """Return the duration of the intro .mov by probing it with ffprobe.

    Falls back to the known duration if the file is missing or ffprobe fails,
    so a missing ffprobe binary does not break the compose pipeline.
    """
    if not path.exists():
        return fallback
    for ffprobe in ("ffprobe", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"):
        try:
            r = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                return round(float(r.stdout.strip()), 3)
        except Exception:
            continue
    return fallback


_INTRO_DURATION: float = _probe_intro_duration(_INTRO_PATH)

_DEFAULT_GRIT_PATH = (
    "/Users/Music/Downloads/"
    "film-grain-and-scratches-overlay-on-black-backgrou-2025-12-17-07-15-10-utc (2).mov"
)


_STILL_MAX_PX = 1920


def _normalise_still(still_path: Path, out_dir: Path) -> Path:
    """Normalise a still image so FFmpeg's PNG/JPEG decoder never crashes.

    Wikimedia images arrive in any format: RGBA, P (palette), 16-bit, CMYK,
    extremely high-res (8640x5760 seen in the wild). FFmpeg's dec:png crashes
    on unusual pixel formats with error -1145393733. Pillow handles all of
    them; we convert to clean RGB JPEG capped at _STILL_MAX_PX on the long
    edge, then FFmpeg receives a perfectly standard input.
    """
    from PIL import Image  # import inside fn keeps startup fast

    img = Image.open(still_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > _STILL_MAX_PX:
        scale = _STILL_MAX_PX / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    norm_path = out_dir / f"_norm_{still_path.stem}.jpg"
    img.save(norm_path, "JPEG", quality=95)
    return norm_path


def _still_to_mp4(
    still_path: Path,
    duration_s: float,
    out_path: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Convert a still image to a fixed-duration 30 fps H264 MP4.

    Normalises the image through Pillow first (converts any pixel mode to RGB,
    caps resolution at _STILL_MAX_PX). This prevents FFmpeg's dec:png from
    crashing on RGBA, 16-bit, CMYK, or extremely large images.

    Applies a cinematic grade so archival photos feel documentary rather
    than PowerPoint:
      - Subtle desaturation (s=0.82): mutes oversaturated colours without
        going full B&W. Archival photos gain a period feel; modern photos
        are barely affected.
      - Temporal film grain (c0s=7:c0f=t): luma-only noise that changes
        each frame. Distinguishable from digital stillness; reads as film.
      - Slight contrast lift (contrast=1.04): compensates for grain wash.

    Stills fed directly into the main filter graph via -framerate 1 +
    stream_loop -1 + fps=30 deadlock the FFmpeg scheduler on macOS
    (image2 demuxer + fps filter creates a 1->30 frame imbalance that
    backs up the entire concat/overlay pipeline). Pre-rendering to a
    proper MP4 makes the still indistinguishable from any other footage
    clip in the main compose -- no special-casing, no deadlock.
    Works identically on CI and local Mac.
    """
    norm = _normalise_still(still_path, out_path.parent)
    vf = ",".join([
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "hue=s=0.82",                        # subtle desaturation
        "eq=contrast=1.04:brightness=-0.01", # slight contrast lift
        "noise=c0s=7:c0f=t",                 # temporal film grain (luma only)
    ])
    cmd = [
        ffmpeg_bin, "-y",
        "-loop", "1", "-framerate", "30", "-i", str(norm),
        "-t", f"{duration_s:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30",
        str(out_path),
    ]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True)
    size = out_path.stat().st_size if out_path.exists() else 0
    if proc.returncode != 0 or size == 0:
        err = proc.stderr.decode("utf-8", errors="replace")[-600:]
        out_path.unlink(missing_ok=True)
        norm.unlink(missing_ok=True)
        raise RuntimeError(
            f"Still pre-render failed for {still_path.name} "
            f"(exit={proc.returncode}, size={size}): {err}"
        )
    norm.unlink(missing_ok=True)
    return out_path


# Timing constants (seconds) - locked by Rule 19 (Reels Strategy)
INTRO_S            = 1.5    # silent intro window - voice starts fast, hook title overlaps
HOOK_LABEL_START   = 0.0
HOOK_TEXT_START    = 0.0    # hook hits immediately (front-loaded novelty)
HOOK_TEXT_END      = 1.5    # 0-1.5s = hook beat
MUSIC_FADEIN_DUR   = 1.0
MUSIC_VOLUME       = 0.20   # balanced under VO after per-track loudness normalization
# CTA shows for 2s after voice ends, then video fades to black.
# CTA_BEFORE_END_S = CTA display (2.0) + fade overlap (1.5) = 3.5
# VIDEO_TAIL_S = 0 - total = voice_end + 0.4 + 3.5 (no extra dead air)
CTA_BEFORE_END_S   = 3.5    # CTA visible for 2s, then 1.5s fade-to-black overlaps
VIDEO_TAIL_S       = 0.0    # no dead air after CTA - total is tight to voice + outro
FADE_TO_BLACK_S    = 1.5    # video fades to black in the last N seconds

# Total reel length band - see rule 19
TARGET_DURATION_MIN_S = 18
TARGET_DURATION_MAX_S = 28
MAX_DURATION_S        = 90
MIN_DURATION_S        = 5

# Clip cut targeting (rule 19: 1.0-2.2s band)
TARGET_CLIP_LEN_S  = 1.8    # mid of allowed band
KEN_BURNS_ZOOM     = 0.20   # 20% overscan - visible motion, not drift
KEN_BURNS_FRAMES   = 90     # frames over which zoompan computes


@dataclass
class OverlayFrame:
    png: Path
    start_s: float
    end_s: float
    fade_in_s: float = 0.3
    fade_out_s: float = 0.2
    rgba: bool = False         # True for photo inserts — preserves transparent background


def _build_case_file_join_plan(n_clips: int, total_duration_s: float) -> tuple[list[float], list[str]]:
    """Deterministic dynamic join plan for case-file style transitions.

    Returns:
      overlaps: length n_clips-1, seconds per join
      transitions: xfade transition names, length n_clips-1
    """
    if n_clips <= 1:
        return [], []
    seed = int(round(total_duration_s * 1000)) ^ (n_clips * 7919)
    rng = random.Random(seed)
    pool = ["fade", "wipeleft", "wiperight", "slideleft", "slideright"]
    overlaps: list[float] = []
    transitions: list[str] = []
    last_t = ""
    for _ in range(n_clips - 1):
        ov = round(rng.uniform(0.16, 0.32), 3)
        overlaps.append(ov)
        choices = [t for t in pool if t != last_t] or pool
        t = rng.choice(choices)
        transitions.append(t)
        last_t = t
    return overlaps, transitions


def compose(
    footage_paths: list[Path],
    voice_path: Path,
    music_path: Optional[Path],
    overlays: list[OverlayFrame],
    out_path: Path,
    *,
    total_duration_s: float,
    voice_delay_s: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Compose the final Reel MP4 from multiple footage clips."""
    if not footage_paths:
        raise RuntimeError("compose() requires at least one footage clip")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Plan: divide total duration across the clips
    clip_windows = _plan_clip_windows(len(footage_paths), total_duration_s)
    print(f"  [ffmpeg] {len(footage_paths)} clips, windows: {[(f'{a:.1f}', f'{b:.1f}') for a,b in clip_windows]}")

    # Pre-render still images to MP4 before the main compose.
    # Stills (JPEG/PNG/WebP) fed via -framerate 1 + stream_loop -1 + fps=30
    # deadlock the FFmpeg scheduler on macOS (see gotchas). A quick one-input
    # FFmpeg pass produces a proper 30fps H264 clip the main compose treats
    # identically to any other footage input -- no special-casing, no deadlock.
    rendered_footage: list[Path] = []
    for fp, (win_start, win_end) in zip(footage_paths, clip_windows):
        if fp.suffix.lower() in _STILL_IMAGE_SUFFIXES:
            dur = max(0.5, win_end - win_start)
            rendered = out_path.parent / f"still_rendered_{fp.stem}.mp4"
            if not rendered.exists():
                print(f"  [ffmpeg] pre-rendering still {fp.name} -> {rendered.name} ({dur:.1f}s)")
                _still_to_mp4(fp, dur, rendered, ffmpeg_bin)
            rendered_footage.append(rendered)
        else:
            rendered_footage.append(fp)
    footage_paths = rendered_footage

    inputs, filter_parts, map_args = _build_filter_graph(
        footage_paths=footage_paths,
        clip_windows=clip_windows,
        voice_path=voice_path,
        music_path=music_path,
        overlays=overlays,
        total_duration_s=total_duration_s,
        voice_delay_s=voice_delay_s,
    )

    # Progress reporting:
    #   -stats (forced) emits the once-per-second `frame=… time=… speed=` line
    #     even when stderr is redirected to a file (FFmpeg suppresses by default
    #     when stderr is not a TTY).
    #   -progress <file> writes structured key=value progress to a dedicated file
    #     for easy parsing / live-tail.
    # Do NOT use `-progress pipe:2` (or pipe:1). When stderr is inherited from a
    # parent whose stderr is a pipe (Cursor agent capture, some CI wrappers), the
    # pipe buffer fills, FFmpeg blocks on write(), and the job looks hung for hours.
    # Both signals go to files on disk -- never to a pipe.
    out_dir = out_path.parent
    err_log = out_dir / "ffmpeg_compose_stderr.log"
    progress_log = out_dir / "ffmpeg_progress.txt"
    filter_script = out_dir / "ffmpeg_filter_complex.txt"
    filter_script.write_text(_join_filters(filter_parts))
    cmd = [
        ffmpeg_bin, "-nostdin", "-y",
        "-stats",
        "-progress", str(progress_log),
        *inputs,
        "-filter_complex_script", str(filter_script),
        *map_args,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",          # highest practical quality for delivery
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-ar", "48000",
        "-b:a", "128k",
        "-movflags", "+faststart",
        # NO -shortest: the ProRes intro is only 1.37s. -shortest would stop
        # FFmpeg at 1.37s instead of the full reel duration.
        "-t", str(total_duration_s),
        str(out_path),
    ]

    print(f"  [ffmpeg] composing {len(overlays)} overlays, duration={total_duration_s:.1f}s")
    print(f"  [ffmpeg] stderr -> {err_log.name} (avoids pipe deadlock; tail on failure)")
    print(f"  [ffmpeg] progress -> {progress_log.name} (tail for frame/time/speed)")
    print(f"  [ffmpeg] filter script -> {filter_script.name}")
    debug_path = out_dir / "ffmpeg_debug.txt"
    debug_path.write_text(
        "FFmpeg command:\n" + " ".join(cmd) + "\n\n"
        + "Filter graph script:\n" + filter_script.read_text()
    )
    # stderr -> disk: never blocks FFmpeg; full log on failure (see gotchas: stderr pipe).
    with err_log.open("wb") as err_f:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err_f
        )
        _register_active(proc)
        proc.wait()
        _register_active(None)
    if proc.returncode != 0:
        tail = ""
        try:
            raw = err_log.read_bytes()
            tail = raw[-12000:].decode("utf-8", errors="replace")
        except OSError:
            pass
        raise RuntimeError(
            f"FFmpeg failed (exit {proc.returncode}). "
            f"See ffmpeg_debug.txt (command) and {err_log.name} (stderr tail below).\n{tail}"
        )
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  [ffmpeg] done -> {out_path.name} ({size_mb:.1f} MB)")

    # Two-pass size fit: if the draft exceeds Meta's URL download limit (~4.8MB),
    # re-encode the already-composed draft at a calculated target bitrate.
    # Two-pass VBR allocates bits optimally across the video -- complex frames
    # (transitions, motion) get more bits, static frames fewer -- so average
    # bitrate hits the target without uniformly degrading every frame.
    # Re-encoding from the draft (not the filter graph) is fast: no overlay
    # compositing, no clip scaling -- just video decode + encode.
    _META_LIMIT_MB = 4.7
    _AUDIO_KBPS    = 128
    if size_mb > _META_LIMIT_MB:
        audio_bits    = _AUDIO_KBPS * 1000 * total_duration_s
        target_bits   = _META_LIMIT_MB * 8 * 1024 * 1024
        video_kbps    = max(350, int((target_bits - audio_bits) / total_duration_s / 1000))
        print(f"  [ffmpeg] {size_mb:.1f}MB > {_META_LIMIT_MB}MB — two-pass VBR @ {video_kbps}k ...")
        passlog = out_dir / "x264_2pass"
        sized   = out_path.with_suffix(".sized.mp4")

        def _run(cmd: list[str]) -> None:
            with err_log.open("ab") as ef:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=ef
                )
                _register_active(proc)
                proc.wait()
                _register_active(None)
            if proc.returncode != 0:
                raw = err_log.read_bytes()[-4000:]
                raise RuntimeError(
                    f"Two-pass encode failed (exit {proc.returncode}).\n"
                    + raw.decode("utf-8", errors="replace")
                )

        _run([
            ffmpeg_bin, "-nostdin", "-y", "-i", str(out_path),
            "-c:v", "libx264", "-preset", "medium",
            "-b:v", f"{video_kbps}k", "-pass", "1",
            "-passlogfile", str(passlog),
            "-an", "-f", "null", "/dev/null",
        ])
        _run([
            ffmpeg_bin, "-nostdin", "-y", "-i", str(out_path),
            "-c:v", "libx264", "-preset", "medium",
            "-b:v", f"{video_kbps}k", "-pass", "2",
            "-passlogfile", str(passlog),
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(sized),
        ])
        sized.replace(out_path)
        for f in out_dir.glob("x264_2pass*"):
            f.unlink(missing_ok=True)
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"  [ffmpeg] two-pass done -> {out_path.name} ({size_mb:.1f} MB)")

    return out_path


# ------------------------------------------------------------------ #
# Clip window planning
# ------------------------------------------------------------------ #

def _plan_clip_windows(n_clips: int, total_s: float) -> list[tuple[float, float]]:
    """Divide total duration into n_clips equal-ish windows.

    First clip slightly longer (carries the hook), last clip slightly
    longer (carries the CTA tail). Middle clips are uniform.
    """
    if n_clips <= 1:
        return [(0.0, total_s)]
    # Reserve fixed leading/trailing chunks
    hook_len = max(2.5, total_s * 0.18)
    cta_len  = max(3.2, total_s * 0.20)
    middle_total = total_s - hook_len - cta_len
    middle_n = n_clips - 2
    if middle_n < 1:
        # Just two clips
        return [(0.0, hook_len), (hook_len, total_s)]
    middle_each = middle_total / middle_n
    windows: list[tuple[float, float]] = []
    t = 0.0
    windows.append((t, t + hook_len)); t += hook_len
    for _ in range(middle_n):
        windows.append((t, t + middle_each)); t += middle_each
    windows.append((t, total_s))
    return windows


# ------------------------------------------------------------------ #
# Filter graph construction
# ------------------------------------------------------------------ #

def _build_filter_graph(
    footage_paths: list[Path],
    clip_windows: list[tuple[float, float]],
    voice_path: Path,
    music_path: Optional[Path],
    overlays: list[OverlayFrame],
    total_duration_s: float,
    voice_delay_s: float = 0.0,
) -> tuple[list[str], list[str], list[str]]:
    inputs: list[str] = []
    filter_lines: list[str] = []
    texture_mode = os.getenv("REEL_TEXTURE_FINISH", "on").strip().lower()
    texture_enabled = texture_mode not in {"off", "0", "false", "no"}
    texture_intensity = os.getenv("REEL_TEXTURE_INTENSITY", "low").strip().lower()
    # User-requested visual baseline: keep animated grit around 65% when enabled.
    # Retain low/medium knobs with a slight spread for quick tuning.
    grit_opacity = 0.65 if texture_intensity != "medium" else 0.70
    grit_env = os.getenv("REEL_GRIT_OVERLAY_PATH", _DEFAULT_GRIT_PATH).strip()
    grit_path = Path(grit_env).expanduser() if grit_env else None
    use_case_file_dynamic = True  # case_file_dynamic is the only transition mode

    # Branded intro overlay - ProRes 4444 with alpha channel.
    # The circle cutout reveals footage through it; the red frame sits on top.
    # Played as a transparent overlay over the final composite, not a footage clip.
    has_intro = _INTRO_PATH.exists()
    if has_intro:
        inputs += ["-i", str(_INTRO_PATH)]
        intro_input_idx = 0
        footage_offset = 1
        print(f"  [intro] {_INTRO_PATH.name} ({_INTRO_DURATION:.3f}s alpha overlay)")
    else:
        intro_input_idx = -1
        footage_offset = 0

    # Inputs: footage clips with stream_loop -1 so any clip shorter than its
    # window is extended by looping. _MIN_CLIP_DURATION_S=8s ensures clips
    # are always longer than the longest window (~8s), so the loop content
    # never actually repeats in practice. tpad=stop=-1 was tried here but
    # caused FFmpeg's scheduler to run indefinitely on CI (44m timeout).
    for fp in footage_paths:
        inputs += ["-stream_loop", "-1", "-i", str(fp)]
    voice_idx = len(footage_paths) + footage_offset
    inputs += ["-i", str(voice_path)]

    music_idx: Optional[int] = None
    if music_path and music_path.exists():
        music_idx = voice_idx + 1
        print(f"  [music] {music_path.name}")
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        png_start_idx = music_idx + 1
    else:
        png_start_idx = voice_idx + 1

    for ov in overlays:
        inputs += ["-i", str(ov.png)]

    grit_idx: Optional[int] = None
    if texture_enabled and grit_path and grit_path.exists():
        grit_idx = png_start_idx + len(overlays)
        inputs += ["-stream_loop", "-1", "-i", str(grit_path)]
        print(f"  [texture] grit: {grit_path.name} ({texture_intensity}, screen)")
    elif texture_enabled:
        print("  [texture] grit overlay missing - skipping texture finish")

    # ------------------------------------------------------------------ #
    # Per-clip processing: scale to oversized, trim to window, then
    # animated crop (slow pan) - keeps the video PLAYING as real footage.
    #
    # Why not zoompan: zoompan is designed for still images; on video it
    # extracts one frame and zooms that, producing a static image effect.
    # Animated crop operates on the live video frames instead.
    # ------------------------------------------------------------------ #
    # How much to overscan each clip (fraction of target dimensions)
    PAN_MARGIN = KEN_BURNS_ZOOM  # 18% extra on each axis
    ow = int(1080 * (1 + PAN_MARGIN))   # 1274
    oh = int(1920 * (1 + PAN_MARGIN))   # 2265
    pan_x_range = ow - 1080              # 194 px of horizontal travel
    pan_y_mid   = (oh - 1920) // 2      # vertical centre offset

    overlaps: list[float] = []
    transition_names: list[str] = []
    if use_case_file_dynamic and len(footage_paths) > 1:
        overlaps, transition_names = _build_case_file_join_plan(len(footage_paths), total_duration_s)
        print(f"  [transitions] case_file_dynamic joins={len(overlaps)}")

    clip_labels = []
    for i, ((start, end), _) in enumerate(zip(clip_windows, footage_paths)):
        inp_idx = i + footage_offset   # shift index past intro if present
        dur = max(0.5, end - start)
        if overlaps and i < len(overlaps):
            dur += overlaps[i]
        # Alternate pan direction clip-by-clip so edits feel dynamic
        if i % 4 == 0:   # pan right
            pan_x = f"{pan_x_range}*t/{dur:.3f}"
        elif i % 4 == 1: # pan left
            pan_x = f"{pan_x_range}*(1-t/{dur:.3f})"
        elif i % 4 == 2: # pan right from mid-frame
            pan_x = f"{pan_x_range//2}+{pan_x_range//2}*t/{dur:.3f}"
        else:             # pan left from mid-frame (keeps all clips in motion)
            pan_x = f"{pan_x_range//2}*(1-t/{dur:.3f})"

        filter_lines.append(
            f"[{inp_idx}:v]"
            f"scale={ow}:{oh}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={ow}:{oh}:(iw-{ow})/2:(ih-{oh})/2,"
            f"setsar=1,"
            f"trim=duration={dur:.3f},"
            f"setpts=PTS-STARTPTS,"
            f"crop=1080:1920:x='{pan_x}':y={pan_y_mid},"
            f"fps=30,"
            f"settb=AVTB"
            f"[clip{inp_idx}]"
        )
        clip_labels.append(f"[clip{inp_idx}]")

    # Join footage clips only (intro is overlaid separately).
    if len(clip_labels) > 1 and overlaps and transition_names:
        current = "join0"
        filter_lines.append(f"{clip_labels[0]}copy[{current}]")
        elapsed = max(0.0, clip_windows[0][1] - clip_windows[0][0])
        for i, nxt in enumerate(clip_labels[1:]):
            ov = overlaps[i]
            tr = transition_names[i]
            out = "footage_concat" if i == len(clip_labels) - 2 else f"join{i+1}"
            # xfade offset is start time of transition in current timeline.
            # We align it to the end of the "base" window; overlap extends clip trims.
            xfade_offset = max(0.0, elapsed - ov)
            filter_lines.append(
                f"[{current}]{nxt}xfade=transition={tr}:duration={ov:.3f}:offset={xfade_offset:.3f}[{out}]"
            )
            elapsed += max(0.0, clip_windows[i + 1][1] - clip_windows[i + 1][0])
            current = out
    elif len(clip_labels) > 1:
        filter_lines.append(
            f"{''.join(clip_labels)}concat=n={len(clip_labels)}:v=1:a=0[footage_concat]"
        )
    else:
        filter_lines.append(f"{clip_labels[0]}copy[footage_concat]")

    # Light brightness pull-down so text reads.
    # Note: noise filter removed - temporal noise (allf=t+u) maximises per-frame
    # entropy, causing Instagram's transcoder to time out on processing.
    filter_lines.append(
        "[footage_concat]"
        "eq=brightness=-0.10:saturation=1.08:contrast=1.04"
        "[footage_dark]"
    )

    # Apply PNG overlays with simple show/hide via overlay enable expression.
    # Static PNG inputs work cleanly with the `enable` window - no looping needed.
    # (Fades disabled: the fade filter requires a multi-frame stream which
    # forces -loop on every input and creates 80+ stream deadlocks at scale.)
    prev = "footage_dark"
    for i, ov in enumerate(overlays):
        png_idx = png_start_idx + i
        cur = f"v{i}"
        enable = f"between(t,{ov.start_s:.3f},{ov.end_s:.3f})"
        # yuv420 is used for all overlays. FFmpeg's overlay filter uses the
        # alpha channel from the input PNG regardless of the output format —
        # transparent regions correctly show the background through them.
        # format=rgba is invalid in FFmpeg 4.x (Ubuntu APT package on CI).
        filter_lines.append(
            f"[{prev}][{png_idx}:v]"
            f"overlay=0:0:enable='{enable}':format=yuv420"
            f"[{cur}]"
        )
        prev = cur

    # Apply branded intro overlay (alpha - circle reveals footage, red wraps it).
    # eof_action=pass: when the 1.37s intro stream ends, the overlay passes
    # through the background instead of stalling FFmpeg for the remaining
    # 60+ seconds of the reel. Without this, FFmpeg hangs waiting for more
    # intro frames that will never arrive.
    # bilinear scaler: lanczos is high quality but ~5x slower; imperceptible
    # difference on a 1.37s branded overlay at Instagram quality.
    if has_intro:
        intro_dur = _INTRO_DURATION  # probed at module load from factjot_intro.mov
        filter_lines.append(
            f"[{intro_input_idx}:v]"
            f"scale=1080:1920:flags=bilinear,setsar=1,setpts=PTS-STARTPTS"
            f"[intro_alpha]"
        )
        filter_lines.append(
            f"[{prev}][intro_alpha]"
            f"overlay=0:0:enable='between(t,0,{intro_dur})':format=yuv420:eof_action=pass"
            f"[after_intro]"
        )
        prev = "after_intro"

    # Subtle animated grit finish (screen on luma only) for a worn archival feel.
    # Applied as a final treatment over the fully composited video.
    #
    # FFmpeg's blend=all_mode=screen on full yuv420p converts via RGB and drifts U/V
    # (pink or green wash) even when both inputs have neutral chroma. Screen-blend
    # only the Y planes, then merge original U/V back (mapping 0x001020 -> yuv420p).
    if grit_idx is not None:
        base_y = f"{prev}_tex_y"
        base_u = f"{prev}_tex_u"
        base_v = f"{prev}_tex_v"
        filter_lines.append(
            f"[{prev}]format=yuv420p,extractplanes=y+u+v"
            f"[{base_y}][{base_u}][{base_v}]"
        )
        filter_lines.append(
            f"[{grit_idx}:v]"
            "scale=1080:1920:force_original_aspect_ratio=increase:flags=bilinear,"
            "crop=1080:1920,"
            "fps=30,"
            "setpts=PTS-STARTPTS,"
            "format=yuv420p,"
            "extractplanes=y"
            "[grain_y]"
        )
        filter_lines.append(
            f"[{base_y}][grain_y]"
            f"blend=all_mode=screen:all_opacity={grit_opacity:.3f},format=gray"
            "[grain_y_scr]"
        )
        filter_lines.append(
            f"[grain_y_scr][{base_u}][{base_v}]"
            "mergeplanes=0x001020:yuv420p"
            "[textured]"
        )
        prev = "textured"

    # Fade to black in the final FADE_TO_BLACK_S seconds
    fade_start = max(0.0, total_duration_s - FADE_TO_BLACK_S)
    filter_lines.append(
        f"[{prev}]fade=t=out:st={fade_start:.3f}:d={FADE_TO_BLACK_S:.3f}[vout]"
    )

    # Audio: voice full, music ducked + faded
    music_fadeout_start = max(0.0, total_duration_s - 4.0)  # fade music earlier
    # The voice MP3 is pre-padded with silence in the caller (make_reel.py).
    # Here we just normalise loudness and trim to the total duration.
    audio_fade_out_start = max(0.0, total_duration_s - FADE_TO_BLACK_S - 0.3)

    if music_idx is not None:
        # Voice: normalise, trim, fade out with video
        filter_lines.append(
            f"[{voice_idx}:a]"
            f"loudnorm=I=-16:LRA=11:TP=-1.5,"
            f"afade=t=out:st={audio_fade_out_start:.3f}:d={FADE_TO_BLACK_S:.3f},"
            f"atrim=duration={total_duration_s}"
            f"[voice_a]"
        )
        # Music: fade in/out, duck under voice
        filter_lines.append(
            f"[{music_idx}:a]"
            f"loudnorm=I=-26:LRA=7:TP=-2.0,"
            f"volume={MUSIC_VOLUME},"
            f"afade=t=in:st=0:d={MUSIC_FADEIN_DUR},"
            f"afade=t=out:st={audio_fade_out_start:.3f}:d={FADE_TO_BLACK_S:.3f},"
            f"atrim=duration={total_duration_s}"
            f"[music_a]"
        )
        # Split voice so it feeds both the sidechain compressor and the final mix
        filter_lines.append("[voice_a]asplit=2[voice_sc][voice_mix]")
        # Music ducked by voice sidechain
        filter_lines.append(
            "[music_a][voice_sc]sidechaincompress="
            "threshold=0.015:ratio=2.5:attack=80:release=700:level_sc=0.9"
            "[music_ducked]"
        )
        filter_lines.append(
            "[voice_mix][music_ducked]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        audio_map = "[aout]"
    else:
        filter_lines.append(
            f"[{voice_idx}:a]loudnorm=I=-16:LRA=11:TP=-1.5,"
            f"atrim=duration={total_duration_s}[aout]"
        )
        audio_map = "[aout]"

    map_args = ["-map", "[vout]", "-map", audio_map]
    return inputs, filter_lines, map_args


def _join_filters(lines: list[str]) -> str:
    return ";\n".join(lines)


# ------------------------------------------------------------------ #
# Duration helpers
# ------------------------------------------------------------------ #

def compute_total_duration(voice_end_s: float) -> float:
    raw = voice_end_s + 0.4 + CTA_BEFORE_END_S + VIDEO_TAIL_S
    return round(max(MIN_DURATION_S, min(MAX_DURATION_S, raw)), 2)


def cta_start(total_duration_s: float) -> float:
    return max(0.0, total_duration_s - CTA_BEFORE_END_S - VIDEO_TAIL_S)


def n_clips_for_duration(total_s: float) -> int:
    """How many clips per Rule 19. Capped at 8 to stay under FFmpeg's
    practical input-stream limit when combined with subtitle overlays."""
    n = int(round(total_s / TARGET_CLIP_LEN_S))
    return max(5, min(8, n))
