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
import signal
import subprocess

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
from dataclasses import dataclass


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
from pathlib import Path
from typing import Optional

# Timing constants (seconds) - locked by Rule 19 (Reels Strategy)
INTRO_S            = 3.5    # silent intro window - hook title shows, voice starts after
HOOK_LABEL_START   = 0.0
HOOK_TEXT_START    = 0.0    # hook hits immediately (front-loaded novelty)
HOOK_TEXT_END      = 1.5    # 0-1.5s = hook beat
MUSIC_FADEIN_DUR   = 1.0
MUSIC_VOLUME       = 0.24   # slightly louder - audible atmosphere without drowning VO
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
KEN_BURNS_ZOOM     = 0.10   # 10% overscan - subtle travel, not shaky
KEN_BURNS_FRAMES   = 90     # frames over which zoompan computes


@dataclass
class OverlayFrame:
    png: Path
    start_s: float
    end_s: float
    fade_in_s: float = 0.3
    fade_out_s: float = 0.2
    is_subtitle: bool = False  # subtitle chunks are pre-composited into a single track


def _pre_compose_subtitles(
    subtitle_overlays: list[OverlayFrame],
    total_duration_s: float,
    out_dir: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Pre-render all subtitle PNGs into a single alpha video track.

    Runs as a fast, lightweight FFmpeg pass on a transparent source.
    The result is a single WebM/VP9 file with alpha that the main compose
    uses as one overlay instead of N sequential overlays -- cutting the
    main filter graph from 30+ stages down to a handful.
    """
    import sys as _sys
    out_path = out_dir / "subtitle_track.webm"
    dur = f"{total_duration_s:.3f}"

    inputs: list[str] = [
        "-f", "lavfi", "-i",
        f"color=c=0x00000000:s=1080x1920:r=30:d={dur}",
    ]
    filter_lines: list[str] = []
    prev = "0:v"

    for i, ov in enumerate(subtitle_overlays):
        inputs += ["-i", str(ov.png)]
        cur = f"sv{i}"
        enable = f"between(t,{ov.start_s:.3f},{ov.end_s:.3f})"
        filter_lines.append(
            f"[{prev}][{i + 1}:v]overlay=0:0:enable='{enable}':format=rgba[{cur}]"
        )
        prev = cur

    cmd = [
        ffmpeg_bin, "-y",
        *inputs,
        "-filter_complex", ";".join(filter_lines),
        "-map", f"[{prev}]",
        "-c:v", "libvpx-vp9",
        "-auto-alt-ref", "0",  # required for alpha in VP9
        "-pix_fmt", "yuva420p",
        "-deadline", "realtime",  # fastest VP9 mode
        "-cpu-used", "8",
        "-r", "30",
        "-t", dur,
        str(out_path),
    ]
    print(f"  [ffmpeg] pre-compositing {len(subtitle_overlays)} subtitles -> single track...")
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _register_active(proc)
    assert proc.stderr is not None
    for raw in proc.stderr:
        _sys.stderr.buffer.write(raw)
        _sys.stderr.buffer.flush()
    proc.wait()
    _register_active(None)
    if proc.returncode != 0:
        raise RuntimeError("Subtitle pre-composition failed")
    print(f"  [ffmpeg] subtitle track ready: {out_path.name}")
    return out_path


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
    subtitle_ass_path: Optional[Path] = None,
    fonts_dir: Optional[Path] = None,
) -> Path:
    """Compose the final Reel MP4 from multiple footage clips.

    subtitle_ass_path: if provided, subtitles are rendered via FFmpeg's
    native 'ass' filter (one filter pass) instead of chained PNG overlays.
    This is the fast path -- 20+ overlay stages collapse to 1.
    """
    if not footage_paths:
        raise RuntimeError("compose() requires at least one footage clip")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Plan: divide total duration across the clips
    clip_windows = _plan_clip_windows(len(footage_paths), total_duration_s)
    print(f"  [ffmpeg] {len(footage_paths)} clips, windows: {[(f'{a:.1f}', f'{b:.1f}') for a,b in clip_windows]}")

    inputs, filter_parts, map_args = _build_filter_graph(
        footage_paths=footage_paths,
        clip_windows=clip_windows,
        voice_path=voice_path,
        music_path=music_path,
        overlays=overlays,
        total_duration_s=total_duration_s,
        voice_delay_s=voice_delay_s,
        subtitle_ass_path=subtitle_ass_path,
        fonts_dir=fonts_dir,
    )

    cmd = [
        ffmpeg_bin, "-nostdin", "-y",
        # Global progress: must be early so FFmpeg honours it reliably on all builds.
        "-progress", "pipe:2",
        "-stats_period", "2",
        *inputs,
        "-filter_complex", _join_filters(filter_parts),
        *map_args,
        "-c:v", "libx264",
        "-preset", "ultrafast",   # CI: wall-clock; tune size via crf + maxrate (Meta ~5MB cap)
        "-crf", "30",
        "-maxrate", "800k",
        "-bufsize", "1600k",
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
    debug_path = out_path.parent / "ffmpeg_debug.txt"
    debug_path.write_text(
        "FFmpeg command:\n" + " ".join(cmd) + "\n\n"
        + "Filter graph:\n" + _join_filters(filter_parts)
    )
    # stderr=None: FFmpeg writes directly to the runner's captured output.
    # No Python buffering, no read(4096) blocking, no log delays.
    # On failure the exit code tells us it failed; ffmpeg_debug.txt has the command.
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=None)
    _register_active(proc)
    proc.wait()
    _register_active(None)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed (exit {proc.returncode}). "
            f"Check ffmpeg_debug.txt for the full command."
        )
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  [ffmpeg] done -> {out_path.name} ({size_mb:.1f} MB)")
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
    subtitle_ass_path: Optional[Path] = None,
    fonts_dir: Optional[Path] = None,
) -> tuple[list[str], list[str], list[str]]:
    inputs: list[str] = []
    filter_lines: list[str] = []

    # Branded intro overlay - ProRes 4444 with alpha channel.
    # The circle cutout reveals footage through it; the red frame sits on top.
    # Played as a transparent overlay over the final composite, not a footage clip.
    intro_path = Path(__file__).resolve().parents[2] / "assets" / "intros" / "factjot_intro.mov"
    has_intro = intro_path.exists()
    if has_intro:
        inputs += ["-i", str(intro_path)]
        intro_input_idx = 0
        footage_offset = 1
        print(f"  [intro] {intro_path.name} (alpha overlay)")
    else:
        intro_input_idx = -1
        footage_offset = 0

    # Inputs: each footage clip with stream_loop -1 so short clips can stretch
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

    clip_labels = []
    for i, ((start, end), _) in enumerate(zip(clip_windows, footage_paths)):
        inp_idx = i + footage_offset   # shift index past intro if present
        dur = max(0.5, end - start)
        # Alternate pan direction clip-by-clip so edits feel dynamic
        if i % 4 == 0:   # pan right
            pan_x = f"{pan_x_range}*t/{dur:.3f}"
        elif i % 4 == 1: # pan left
            pan_x = f"{pan_x_range}*(1-t/{dur:.3f})"
        elif i % 4 == 2: # pan right but starting mid-frame
            pan_x = f"{pan_x_range//2}+{pan_x_range//4}*t/{dur:.3f}"
        else:             # static centre (subtle rest between moves)
            pan_x = f"{pan_x_range//2}"

        # Scale video to oversized → trim so t starts at 0 → animated crop
        filter_lines.append(
            f"[{inp_idx}:v]"
            f"scale={ow}:{oh}:force_original_aspect_ratio=increase,"
            f"crop={ow}:{oh}:(iw-{ow})/2:(ih-{oh})/2,"
            f"setsar=1,"
            f"trim=duration={dur:.3f},"
            f"setpts=PTS-STARTPTS,"
            f"crop=1080:1920:x='{pan_x}':y={pan_y_mid}"
            f"[clip{inp_idx}]"
        )
        clip_labels.append(f"[clip{inp_idx}]")

    # Concat footage clips only (intro is overlaid separately)
    if len(clip_labels) > 1:
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
        filter_lines.append(
            f"[{prev}][{png_idx}:v]"
            f"overlay=0:0:enable='{enable}':format=yuv420"
            f"[{cur}]"
        )
        prev = cur

    # Native .ass subtitle render -- one filter pass for ALL subtitle text.
    # Replaces the 20+ sequential PNG overlay stages when subtitle_ass_path
    # is provided. libass is compiled into the GitHub Actions static FFmpeg.
    if subtitle_ass_path and subtitle_ass_path.exists():
        ass_arg = str(subtitle_ass_path).replace("\\", "/").replace(":", "\\:")
        fd_arg = ""
        if fonts_dir and fonts_dir.exists():
            fd = str(fonts_dir).replace("\\", "/").replace(":", "\\:")
            fd_arg = f":fontsdir={fd}"
        filter_lines.append(
            f"[{prev}]ass=filename={ass_arg}{fd_arg}[after_subs]"
        )
        prev = "after_subs"

    # Apply branded intro overlay (alpha - circle reveals footage, red wraps it).
    # eof_action=pass: when the 1.37s intro stream ends, the overlay passes
    # through the background instead of stalling FFmpeg for the remaining
    # 60+ seconds of the reel. Without this, FFmpeg hangs waiting for more
    # intro frames that will never arrive.
    # bilinear scaler: lanczos is high quality but ~5x slower; imperceptible
    # difference on a 1.37s branded overlay at Instagram quality.
    if has_intro:
        intro_dur = 1.37  # known duration of factjot_intro.mov
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
