"""Smoke tests for src/render/reel_composer.py.

Goal: catch the historical FFmpeg compose failure modes that have hit
production repeatedly:

  - stderr backpressure deadlock (compose must write stderr to disk)
  - 96kHz audio bug (output must be 48kHz to avoid Meta rejection)
  - libvpx breakage / FFmpeg binary regression
  - file truncation / 0-byte output
  - missing intro file fallback (graceful skip rather than crash)

The tests build a tiny synthetic input set (1 image, 2-second silent
voice WAV, no music) and invoke real FFmpeg through compose(). Real
FFmpeg keeps the test honest about audio rates, container format, and
filter graph correctness; the input is small enough that the run
finishes in single-digit seconds on local Mac and CI Ubuntu.

If FFmpeg is unavailable we skip rather than fail, so this suite never
blocks PRs on a CI image without ffmpeg installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.render.reel_composer import compose, OverlayFrame  # noqa: E402


def _ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def _ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def _ffprobe_streams(path: Path) -> list[dict]:
    """Return decoded ffprobe stream entries for an MP4."""
    probe = _ffprobe_bin() or "ffprobe"
    proc = subprocess.run(
        [probe, "-v", "error", "-show_entries",
         "stream=codec_name,codec_type,sample_rate,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"ffprobe failed: {proc.stderr}"
    return json.loads(proc.stdout).get("streams", [])


def _make_voice_wav(path: Path, duration_s: float = 2.0, sample_rate: int = 48000) -> None:
    """Write a non-silent low-level tone WAV at the given duration.

    Pure silence trips FFmpeg's loudnorm filter into producing NaN
    samples, which crashes the AAC encoder ('Input contains NaN/Inf').
    A faint sine tone at -40 dBFS exercises the filter graph the same
    way real voice does, while keeping the test deterministic and small.
    """
    import math
    n_frames = int(round(sample_rate * duration_s))
    amplitude = int(0.01 * 32767)  # -40 dBFS
    freq = 440.0
    frames = bytearray()
    for i in range(n_frames):
        sample = int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
        frames += sample.to_bytes(2, byteorder="little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))


def _make_solid_image(path: Path, w: int = 1080, h: int = 1920) -> None:
    """Write a solid-colour PNG via Pillow."""
    from PIL import Image
    Image.new("RGB", (w, h), color=(20, 100, 180)).save(path, "PNG")


def _make_tiny_video(path: Path, ffmpeg: str, duration_s: float = 2.5) -> None:
    """Render a tiny synthetic colour-bars MP4 via lavfi.

    Used as a footage clip in compose() so the filter graph receives a
    real video stream rather than a still image (still-handling has its
    own pre-render path that's well-tested by existing manual runs).
    """
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"color=c=teal:s=640x1136:d={duration_s:.2f}:r=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-pix_fmt", "yuv420p",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    assert proc.returncode == 0, f"failed to build test footage: {proc.stderr.decode(errors='replace')[:600]}"


def _make_overlay_png(path: Path) -> None:
    """Write a small transparent PNG overlay.

    compose() expects 1080x1920 PNGs as overlay frames. A tiny coloured
    rectangle at the canonical size is enough to exercise the overlay
    filter chain.
    """
    from PIL import Image
    Image.new("RGBA", (1080, 1920), (255, 255, 255, 0)).save(path, "PNG")


@pytest.fixture(scope="module")
def ffmpeg() -> str:
    bin_path = _ffmpeg_bin()
    if not bin_path:
        pytest.skip("ffmpeg not on PATH; smoke tests need real FFmpeg")
    if not _ffprobe_bin():
        pytest.skip("ffprobe not on PATH; smoke tests need real ffprobe")
    return bin_path


@pytest.fixture
def tiny_inputs(tmp_path: Path, ffmpeg: str, monkeypatch) -> dict:
    """Build a minimal viable input set for compose()."""
    voice_wav = tmp_path / "voice.wav"
    _make_voice_wav(voice_wav, duration_s=2.0, sample_rate=48000)

    footage = tmp_path / "footage.mp4"
    _make_tiny_video(footage, ffmpeg, duration_s=2.5)

    overlay_png = tmp_path / "ov.png"
    _make_overlay_png(overlay_png)

    out = tmp_path / "final.mp4"
    overlays = [
        OverlayFrame(png=overlay_png, start_s=0.1, end_s=1.6),
    ]

    # Disable the grit overlay path so missing files on CI do not matter.
    # The overlay file at a hardcoded /Users/... path obviously doesn't
    # exist on Ubuntu runners; explicit off keeps the test deterministic.
    monkeypatch.setenv("REEL_TEXTURE_FINISH", "off")
    monkeypatch.delenv("REEL_GRIT_OVERLAY_PATH", raising=False)

    return {
        "footage": [footage],
        "voice": voice_wav,
        "overlays": overlays,
        "out": out,
    }


def test_compose_with_minimal_inputs_succeeds(tiny_inputs: dict, ffmpeg: str) -> None:
    """compose() runs end-to-end with one footage clip + voice + overlay."""
    out = compose(
        footage_paths=tiny_inputs["footage"],
        voice_path=tiny_inputs["voice"],
        music_path=None,
        overlays=tiny_inputs["overlays"],
        out_path=tiny_inputs["out"],
        total_duration_s=2.5,
        voice_delay_s=0.0,
        ffmpeg_bin=ffmpeg,
    )
    assert out.exists(), "compose() did not produce an output file"
    assert out.stat().st_size > 0, "output file is empty"

    streams = _ffprobe_streams(out)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    assert video is not None, "output has no video stream"
    assert audio is not None, "output has no audio stream"
    assert video.get("codec_name") == "h264", f"video codec is {video.get('codec_name')}, expected h264"
    # Hard rule: Meta rejects 44.1kHz and 96kHz. Output must be 48kHz.
    sample_rate = int(audio.get("sample_rate", "0"))
    assert sample_rate == 48000, f"audio sample rate is {sample_rate}, expected 48000"
    duration = float(video.get("duration", "0") or 0.0)
    # Allow a small tolerance: container framing rounds up by ~0.05s.
    assert 1.5 < duration < 3.5, f"video duration {duration:.2f}s outside expected band"


def test_compose_handles_missing_grit_overlay_gracefully(
    tiny_inputs: dict, ffmpeg: str, monkeypatch, tmp_path: Path
) -> None:
    """When grit overlay path does not exist, compose() must still succeed.

    REEL_TEXTURE_FINISH=on but the grit file is missing simulates a CI
    runner without the bundled grit asset. compose() should log
    'grit overlay missing' and produce a valid MP4 anyway.
    """
    monkeypatch.setenv("REEL_TEXTURE_FINISH", "on")
    monkeypatch.setenv("REEL_GRIT_OVERLAY_PATH", str(tmp_path / "does_not_exist.mov"))
    out = compose(
        footage_paths=tiny_inputs["footage"],
        voice_path=tiny_inputs["voice"],
        music_path=None,
        overlays=tiny_inputs["overlays"],
        out_path=tiny_inputs["out"],
        total_duration_s=2.5,
        voice_delay_s=0.0,
        ffmpeg_bin=ffmpeg,
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_compose_writes_diagnostic_files(tiny_inputs: dict, ffmpeg: str) -> None:
    """compose() must write stderr, progress, filter script + debug to disk.

    These are the artefacts we need on every failure to debug FFmpeg
    issues without racing pipe buffers (gotcha: stderr to a pipe blocks
    FFmpeg indefinitely under capture).
    """
    out = compose(
        footage_paths=tiny_inputs["footage"],
        voice_path=tiny_inputs["voice"],
        music_path=None,
        overlays=tiny_inputs["overlays"],
        out_path=tiny_inputs["out"],
        total_duration_s=2.5,
        voice_delay_s=0.0,
        ffmpeg_bin=ffmpeg,
    )
    out_dir = out.parent
    assert (out_dir / "ffmpeg_compose_stderr.log").exists(), "stderr log not written"
    assert (out_dir / "ffmpeg_progress.txt").exists(), "progress file not written"
    assert (out_dir / "ffmpeg_filter_complex.txt").exists(), "filter script not written"
    assert (out_dir / "ffmpeg_debug.txt").exists(), "debug file not written"

    filter_script = (out_dir / "ffmpeg_filter_complex.txt").read_text()
    # Sanity check: the filter graph for a 1-clip compose must include
    # the footage_concat label and the audio loudnorm filter.
    assert "footage_concat" in filter_script
    assert "loudnorm" in filter_script


def test_compose_rejects_empty_footage_list(tmp_path: Path, ffmpeg: str) -> None:
    """compose() with no footage clips must raise (do not silently produce 0-byte file)."""
    voice_wav = tmp_path / "voice.wav"
    _make_voice_wav(voice_wav)
    with pytest.raises(RuntimeError, match="at least one footage clip"):
        compose(
            footage_paths=[],
            voice_path=voice_wav,
            music_path=None,
            overlays=[],
            out_path=tmp_path / "out.mp4",
            total_duration_s=2.0,
            voice_delay_s=0.0,
            ffmpeg_bin=ffmpeg,
        )
