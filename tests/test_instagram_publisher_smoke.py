"""Smoke tests for src/publish/instagram_publisher.py.

Goal: catch the publish race conditions that have hit production:

  - 2026-05-05 triple-post incident: media_publish returned a falsy
    response while IG had committed; recovery fetcher must verify
    by media_type + time-window, not just 'most recent post'.
  - 2026-05-09 story container race: post_to_stories called
    media_publish before the container reached FINISHED status,
    publishing stories with missing thumbnails. Fixed in 3a366e1.
  - reel publish must poll status_code=FINISHED before media_publish
    or IG drops the upload silently.

Tests mock the Graph API at the requests layer. No network calls
made during the test run.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.publish.instagram_publisher import InstagramGraphPublisher  # noqa: E402


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _publisher() -> InstagramGraphPublisher:
    """Construct a publisher with stub credentials for tests."""
    return InstagramGraphPublisher(account_id="123456", access_token="STUB_TOKEN")


def _resp(status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    """Build a minimal requests.Response stand-in."""
    m = MagicMock()
    m.status_code = status_code
    m.ok = 200 <= status_code < 300
    m.json.return_value = json_body or {}
    m.text = ""
    return m


# ---------------------------------------------------------------------- #
# is_configured
# ---------------------------------------------------------------------- #


def test_is_configured_requires_both_id_and_token() -> None:
    assert _publisher().is_configured() is True
    assert InstagramGraphPublisher("", "").is_configured() is False
    assert InstagramGraphPublisher("123", "").is_configured() is False
    assert InstagramGraphPublisher("", "TOK").is_configured() is False


# ---------------------------------------------------------------------- #
# publish_carousel: payload shape
# ---------------------------------------------------------------------- #


def test_publish_carousel_creates_children_then_parent_then_publishes() -> None:
    """Carousel publish must POST per-image children, then a parent
    container with a comma-joined children list, poll for FINISHED,
    then call media_publish."""
    pub = _publisher()
    posts: list[tuple[str, dict]] = []
    gets: list[tuple[str, dict]] = []

    def fake_post(url, data=None, timeout=None):
        posts.append((url, data or {}))
        # Each /media POST returns an incrementing creation id; the
        # parent container creation is the one that names CAROUSEL.
        if "media_publish" in url:
            return _resp(200, {"id": "PUBLISHED_IG_ID"})
        if data and data.get("media_type") == "CAROUSEL":
            return _resp(200, {"id": "PARENT_ID"})
        return _resp(200, {"id": f"CHILD_{len(posts)}"})

    def fake_get(url, params=None, timeout=None):
        gets.append((url, params or {}))
        return _resp(200, {"status_code": "FINISHED"})

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get", side_effect=fake_get), \
         patch("src.publish.instagram_publisher.time.sleep"):
        result = pub.publish_carousel(
            ["https://example.com/img1.jpg", "https://example.com/img2.jpg"],
            "test caption",
        )

    assert result["ok"] is True
    assert result["ig_media_id"] == "PUBLISHED_IG_ID"
    # Two child POSTs + one parent POST + one media_publish POST = 4
    assert len(posts) == 4
    # Children must be flagged is_carousel_item=true.
    child_posts = [p for p in posts if "is_carousel_item" in (p[1] or {})]
    assert all(p[1]["is_carousel_item"] == "true" for p in child_posts)
    # Parent must have media_type=CAROUSEL and a comma-joined children list.
    parent_post = next(p for p in posts if (p[1] or {}).get("media_type") == "CAROUSEL")
    assert "," in parent_post[1]["children"]
    assert parent_post[1]["caption"] == "test caption"


def test_publish_carousel_rejects_more_than_ten_images() -> None:
    pub = _publisher()
    urls = [f"https://example.com/img{i}.jpg" for i in range(11)]
    result = pub.publish_carousel(urls, "caption")
    assert result["ok"] is False
    assert "10-image cap" in result["error"]


def test_publish_carousel_rejects_empty_url_list() -> None:
    pub = _publisher()
    result = pub.publish_carousel([], "caption")
    assert result["ok"] is False
    assert "No image URLs" in result["error"]


def test_publish_carousel_truncates_overlong_caption() -> None:
    """IG caps captions at 2200 chars. Publisher must truncate, not error."""
    pub = _publisher()
    long_caption = "x" * 3000

    def fake_post(url, data=None, timeout=None):
        if "media_publish" in url:
            return _resp(200, {"id": "ID"})
        if data and data.get("media_type") == "CAROUSEL":
            # Capture the caption to assert on it.
            assert len(data["caption"]) <= 2200
            return _resp(200, {"id": "PARENT"})
        return _resp(200, {"id": "CHILD"})

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get",
               return_value=_resp(200, {"status_code": "FINISHED"})), \
         patch("src.publish.instagram_publisher.time.sleep"):
        result = pub.publish_carousel(["https://example.com/a.jpg"], long_caption)

    assert result["ok"] is True


# ---------------------------------------------------------------------- #
# publish_reel: poll until FINISHED before media_publish
# ---------------------------------------------------------------------- #


def test_publish_reel_polls_until_finished_then_publishes() -> None:
    """publish_reel must wait for status_code=FINISHED before media_publish.

    This is the canonical race fix: posting before encoding finishes
    makes IG drop the upload silently.
    """
    pub = _publisher()
    poll_responses = [
        _resp(200, {"status_code": "IN_PROGRESS"}),
        _resp(200, {"status_code": "IN_PROGRESS"}),
        _resp(200, {"status_code": "FINISHED"}),
        # Subsequent gets are for the recovery /media verifier.
        _resp(200, {"data": []}),
    ]

    def fake_get(url, params=None, timeout=None):
        return poll_responses.pop(0) if poll_responses else _resp(200, {"data": []})

    posts: list[tuple[str, dict]] = []

    def fake_post(url, data=None, timeout=None):
        posts.append((url, data or {}))
        if "media_publish" in url:
            return _resp(200, {"id": "PUBLISHED_REEL_ID"})
        return _resp(200, {"id": "REEL_CONTAINER"})

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get", side_effect=fake_get), \
         patch("src.publish.instagram_publisher.time.sleep"):
        result = pub.publish_reel(
            video_url="https://example.com/v.mp4",
            caption="test reel",
            poll_timeout_s=120,
        )

    assert result["ok"] is True
    assert result["ig_media_id"] == "PUBLISHED_REEL_ID"
    # Order matters: container creation, then media_publish (no other POST in between).
    assert "media_publish" in posts[-1][0]


def test_publish_reel_fails_on_container_error_status() -> None:
    """If IG marks the container as ERROR, publish_reel must fail without
    calling media_publish."""
    pub = _publisher()
    poll_responses = [
        _resp(200, {"status_code": "IN_PROGRESS"}),
        _resp(200, {"status_code": "ERROR", "error_message": "bad video"}),
    ]

    def fake_get(url, params=None, timeout=None):
        return poll_responses.pop(0) if poll_responses else _resp(200, {})

    posts: list[tuple[str, dict]] = []

    def fake_post(url, data=None, timeout=None):
        posts.append((url, data or {}))
        return _resp(200, {"id": "REEL_CONTAINER"})

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get", side_effect=fake_get), \
         patch("src.publish.instagram_publisher.time.sleep"):
        result = pub.publish_reel("https://example.com/v.mp4", "caption", poll_timeout_s=60)

    assert result["ok"] is False
    # Only the initial container creation POST happened, no media_publish.
    assert all("media_publish" not in p[0] for p in posts)


# ---------------------------------------------------------------------- #
# post_to_stories: poll FINISHED before media_publish (2026-05-09 fix)
# ---------------------------------------------------------------------- #


def test_post_to_stories_polls_finished_before_publish() -> None:
    """The 2026-05-09 race fix: stories must poll status before publishing.

    Previously a fixed time.sleep(3) raced the IG image ingest; stories
    published with missing thumbnails. Fix: call _wait_for_finished
    before media_publish, same shape as carousel + reels.
    """
    pub = _publisher()
    poll_responses = [
        _resp(200, {"status_code": "IN_PROGRESS"}),
        _resp(200, {"status_code": "FINISHED"}),
    ]

    def fake_get(url, params=None, timeout=None):
        return poll_responses.pop(0) if poll_responses else _resp(200, {"data": []})

    posts: list[tuple[str, dict]] = []

    def fake_post(url, data=None, timeout=None):
        posts.append((url, data or {}))
        if "media_publish" in url:
            return _resp(200, {"id": "STORY_PUBLISHED_ID"})
        return _resp(200, {"id": "STORY_CONTAINER"})

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get", side_effect=fake_get), \
         patch("src.publish.instagram_publisher.time.sleep"):
        result = pub.post_to_stories(image_url="https://example.com/story.jpg")

    assert result["ok"] is True
    assert result["ig_media_id"] == "STORY_PUBLISHED_ID"
    # Polling must happen between container creation and media_publish.
    create_idx = next(i for i, p in enumerate(posts) if "media_publish" not in p[0])
    publish_idx = next(i for i, p in enumerate(posts) if "media_publish" in p[0])
    assert create_idx < publish_idx, "publish must come after container creation"


def test_post_to_stories_fails_when_container_never_finishes() -> None:
    """If polling times out, post_to_stories must NOT call media_publish."""
    pub = _publisher()

    def fake_get(url, params=None, timeout=None):
        return _resp(200, {"status_code": "IN_PROGRESS"})

    posts: list[tuple[str, dict]] = []

    def fake_post(url, data=None, timeout=None):
        posts.append((url, data or {}))
        return _resp(200, {"id": "STORY_CONTAINER"})

    # Patch time.time so the polling loop sees an instant timeout.
    times = iter([0.0, 0.0, 0.0, 0.0, 1e9, 1e9, 1e9, 1e9])

    def fake_time():
        try:
            return next(times)
        except StopIteration:
            return 1e9

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get", side_effect=fake_get), \
         patch("src.publish.instagram_publisher.time.sleep"), \
         patch("src.publish.instagram_publisher.time.time", side_effect=fake_time):
        result = pub.post_to_stories(image_url="https://example.com/story.jpg")

    assert result["ok"] is False
    assert all("media_publish" not in p[0] for p in posts), \
        "media_publish must not be called when container did not reach FINISHED"


# ---------------------------------------------------------------------- #
# Recovery: media_publish returns no id but IG actually committed
# ---------------------------------------------------------------------- #


def test_publish_recovery_uses_media_type_window() -> None:
    """When media_publish returns no id, the recovery fetcher must
    only attribute a recently-published post that matches the expected
    media_type. This is the 2026-05-05 audit fix: without the type
    filter the recovery falsely attributed an unrelated carousel."""
    pub = _publisher()

    poll_responses = [
        _resp(200, {"status_code": "FINISHED"}),
        # Recovery fetch: one stale carousel from before (wrong type and
        # too old) plus one fresh REELS post that matches.
        _resp(200, {"data": [
            {
                "id": "OLD_CAROUSEL",
                "timestamp": "2024-01-01T00:00:00+0000",
                "media_type": "IMAGE",
                "media_product_type": "FEED",
            },
            {
                "id": "FRESH_REEL",
                "timestamp": "2099-01-01T00:00:00+0000",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
            },
        ]}),
        _resp(200, {"data": []}),  # second recovery for the verify-by-media call
    ]

    def fake_get(url, params=None, timeout=None):
        return poll_responses.pop(0) if poll_responses else _resp(200, {"data": []})

    def fake_post(url, data=None, timeout=None):
        if "media_publish" in url:
            # IG returns an unhelpful error response, but the post has
            # actually committed -- the recovery flow has to find it.
            return _resp(200, {"error": {"message": "rate limit"}})
        return _resp(200, {"id": "REEL_CONTAINER"})

    with patch("src.publish.instagram_publisher.requests.post", side_effect=fake_post), \
         patch("src.publish.instagram_publisher.requests.get", side_effect=fake_get), \
         patch("src.publish.instagram_publisher.time.sleep"):
        result = pub.publish_reel("https://example.com/v.mp4", "caption", poll_timeout_s=60)

    assert result["ok"] is True
    # Must pick the FRESH_REEL (media_product_type=REELS), not OLD_CAROUSEL.
    assert result["ig_media_id"] == "FRESH_REEL"
