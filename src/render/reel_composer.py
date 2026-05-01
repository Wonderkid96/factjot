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

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Timing constants (seconds) — locked by Rule 19 (Reels Strategy)
HOOK_LABEL_START   = 0.0
HOOK_TEXT_START    = 0.0    # hook hits immediately (front-loaded novelty)
HOOK_TEXT_END      = 1.5    # 0-1.5s = hook beat
MUSIC_FADEIN_DUR   = 1.0
MUSIC_VOLUME       = 0.24   # slightly louder — audible atmosphere without drowning VO
# CTA shows for 2s after voice ends, then video fades to black.
# CTA_BEFORE_END_S = CTA display (2.0) + fade overlap (1.5) = 3.5
# VIDEO_TAIL_S = 0 — total = voice_end + 0.4 + 3.5 (no extra dead air)
CTA_BEFORE_END_S   = 3.5    # CTA visible for 2s, then 1.5s fade-to-black overlaps
VIDEO_TAIL_S       = 0.0    # no dead air after CTA — total is tight to voice + outro
FADE_TO_BLACK_S    = 1.5    # video fades to black in the last N seconds

# Total reel length band — see rule 19
TARGET_DURATION_MIN_S = 18
TARGET_DURATION_MAX_S = 28
MAX_DURATION_S        = 90
MIN_DURATION_S        = 5

# Clip cut targeting (rule 19: 1.0-2.2s band)
TARGET_CLIP_LEN_S  = 1.8    # mid of allowed band
KEN_BURNS_ZOOM     = 0.10   # 10% overscan — subtle travel, not shaky
KEN_BURNS_FRAMES   = 90     # frames over which zoompan computes


@dataclass
class OverlayFrame:
    png: Path
    start_s: float
    end_s: float
    fade_in_s: float = 0.3
    fade_out_s: float = 0.2


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

    inputs, filter_parts, map_args = _build_filter_graph(
        footage_paths=footage_paths,
        clip_windows=clip_windows,
        voice_path=voice_path,
        music_path=music_path,
        overlays=overlays,
        total_duration_s=total_duration_s,
        voice_delay_s=voice_delay_s,
    )

    cmd = [
        ffmpeg_bin, "-y",
        *inputs,
        "-filter_complex", _join_filters(filter_parts),
        *map_args,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-t", str(total_duration_s),
        str(out_path),
    ]

    print(f"  [ffmpeg] composing {len(overlays)} overlays, duration={total_duration_s:.1f}s")
    # Dump command + filter graph for debugging
    debug_path = out_path.parent / "ffmpeg_debug.txt"
    debug_path.write_text(
        "FFmpeg command:\n" + " ".join(cmd) + "\n\n"
        + "Filter graph:\n" + _join_filters(filter_parts)
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Save full stderr for inspection
        (out_path.parent / "ffmpeg_stderr.txt").write_text(result.stderr)
        raise RuntimeError(
            f"FFmpeg failed (exit {result.returncode}):\n"
            f"STDERR (last 5000 chars):\n{result.stderr[-5000:]}"
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
) -> tuple[list[str], list[str], list[str]]:
    inputs: list[str] = []
    filter_lines: list[str] = []

    # Branded intro overlay — ProRes 4444 with alpha channel.
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
    # animated crop (slow pan) — keeps the video PLAYING as real footage.
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

    # Light brightness pull-down so text reads
    filter_lines.append(
        "[footage_concat]"
        "eq=brightness=-0.10:saturation=1.08:contrast=1.04,"
        "noise=alls=3:allf=t+u"    # light film grain — level 3 is barely perceptible
        "[footage_dark]"
    )

    # Apply PNG overlays with simple show/hide via overlay enable expression.
    # Static PNG inputs work cleanly with the `enable` window — no looping needed.
    # (Fades disabled: the fade filter requires a multi-frame stream which
    # forces -loop on every input and creates 80+ stream deadlocks at scale.)
    prev = "footage_dark"
    for i, ov in enumerate(overlays):
        png_idx = png_start_idx + i
        cur = f"v{i}"
        enable = f"between(t,{ov.start_s:.3f},{ov.end_s:.3f})"
        filter_lines.append(
            f"[{prev}][{png_idx}:v]"
            f"overlay=0:0:enable='{enable}':format=auto"
            f"[{cur}]"
        )
        prev = cur

    # Apply branded intro overlay (alpha — circle reveals footage, red wraps it)
    if has_intro:
        intro_dur = 1.37  # known duration of factjot_intro.mov
        filter_lines.append(
            f"[{intro_input_idx}:v]"
            f"scale=1080:1920:flags=lanczos,setsar=1,setpts=PTS-STARTPTS"
            f"[intro_alpha]"
        )
        filter_lines.append(
            f"[{prev}][intro_alpha]"
            f"overlay=0:0:enable='between(t,0,{intro_dur})':format=auto"
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
