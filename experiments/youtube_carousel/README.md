## YouTube Carousel Test Pipeline (Playwright-only frames)

Location:
`tests/youtube_carousel_pipeline.py`

This test pipeline is intentionally isolated under `tests/` to avoid collisions
with production reel/carousel functions.

What it does:

1. Downloads timed captions from YouTube (`yt-dlp`)
2. Compresses full transcript into exactly 8-10 slides via Claude (Haiku default)
3. Captures one relevant frame per slide using Playwright from local video
4. Renders final black-background carousel slide PNGs using Playwright + HTML

No ffmpeg is used in this script.

## Install (repo venv)

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m pip install -r tests/youtube_carousel_pipeline_requirements.txt
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 -m playwright install chromium
```

## Run

```bash
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 tests/youtube_carousel_pipeline.py \
  --url "https://www.youtube.com/watch?v=C65iqOSCZOY" \
  --slides 8 \
  --project-name "asml-playwright-test"
```

Outputs:
`tests/output/<project-name>/`

- `captions_raw.vtt`
- `transcript.json`
- `slides.json`
- `video.mp4`
- `frames/slide_XX.jpg`
- `slides/slide_XX.png`
