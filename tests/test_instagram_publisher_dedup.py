"""Tests for the defence-in-depth dedup hook on InstagramGraphPublisher.

Behavioural contract: when the publisher is constructed with a
`dedup_check` hook AND a caller passes `dedup_subjects` to a publish
method, the hook runs immediately before the first Graph API call. If
the hook raises, no API call is made.

This is the last line of defence: any code path that reaches the
publisher (orchestrator agent, manual CLI, future webhook, ad-hoc
retry) goes through the same final check. Per audit /debatemax 001 R6.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brain import DuplicatePostError  # noqa: E402
from src.publish.instagram_publisher import InstagramGraphPublisher  # noqa: E402


class _PostCounter:
    """Monkeypatch target for requests.post. Counts calls so a test can
    assert that the dedup hook fired BEFORE any HTTP request.
    """
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, *args, **kwargs):
        self.calls.append((url, kwargs))

        class _Resp:
            def json(self):
                return {"id": "fake_media_id"}
        return _Resp()


# ----- publish_carousel ---------------------------------------------

def test_dedup_hook_raises_blocks_publish_carousel(monkeypatch):
    """A dedup_check that raises must prevent any HTTP call."""
    counter = _PostCounter()
    monkeypatch.setattr("src.publish.instagram_publisher.requests.post", counter)

    def reject_everything(subjects):
        raise DuplicatePostError(f"already posted: {subjects[0][:30]}")

    pub = InstagramGraphPublisher(
        account_id="acct",
        access_token="tok",
        dedup_check=reject_everything,
    )

    with pytest.raises(DuplicatePostError):
        pub.publish_carousel(
            image_urls=["https://example.com/a.jpg"],
            caption="cap",
            dedup_subjects=["manual:abc:my-subject"],
        )

    assert counter.calls == [], (
        "publisher must NOT make any HTTP request when the dedup hook raises"
    )


def test_dedup_hook_passing_allows_publish_carousel(monkeypatch):
    """Hook that returns cleanly does not block publish."""
    counter = _PostCounter()
    monkeypatch.setattr("src.publish.instagram_publisher.requests.post", counter)
    monkeypatch.setattr(
        "src.publish.instagram_publisher.requests.get",
        lambda *a, **k: type("R", (), {"json": lambda self: {"status_code": "FINISHED"}})(),
    )

    def pass_everything(subjects):
        return None

    pub = InstagramGraphPublisher(
        account_id="acct",
        access_token="tok",
        dedup_check=pass_everything,
    )
    # Stub the wait-loop so the test doesn't sleep.
    pub._wait_for_finished = lambda creation_id, timeout_seconds=120: {"ok": True}
    pub._publish_container = lambda *a, **k: {"id": "media_999"}

    result = pub.publish_carousel(
        image_urls=["https://example.com/a.jpg"],
        caption="cap",
        dedup_subjects=["manual:abc:my-subject"],
    )
    assert result["ok"] is True
    assert len(counter.calls) >= 1, "publish must make at least one HTTP call when not blocked"


def test_no_dedup_check_is_back_compat(monkeypatch):
    """Publisher constructed WITHOUT a dedup_check ignores dedup_subjects
    entirely (back-compat with any caller not yet updated).
    """
    counter = _PostCounter()
    monkeypatch.setattr("src.publish.instagram_publisher.requests.post", counter)
    monkeypatch.setattr(
        "src.publish.instagram_publisher.requests.get",
        lambda *a, **k: type("R", (), {"json": lambda self: {"status_code": "FINISHED"}})(),
    )

    pub = InstagramGraphPublisher(account_id="acct", access_token="tok")
    pub._wait_for_finished = lambda creation_id, timeout_seconds=120: {"ok": True}
    pub._publish_container = lambda *a, **k: {"id": "media_999"}

    # Even with dedup_subjects set, no hook = no check.
    result = pub.publish_carousel(
        image_urls=["https://example.com/a.jpg"],
        caption="cap",
        dedup_subjects=["any-subject"],
    )
    assert result["ok"] is True


def test_no_dedup_subjects_skips_hook(monkeypatch):
    """A caller that does not pass dedup_subjects must NOT trigger the
    hook (back-compat with callers we may have missed in the update).
    """
    counter = _PostCounter()
    monkeypatch.setattr("src.publish.instagram_publisher.requests.post", counter)
    monkeypatch.setattr(
        "src.publish.instagram_publisher.requests.get",
        lambda *a, **k: type("R", (), {"json": lambda self: {"status_code": "FINISHED"}})(),
    )

    hook_calls: list = []

    def hook(subjects):
        hook_calls.append(subjects)

    pub = InstagramGraphPublisher(
        account_id="acct",
        access_token="tok",
        dedup_check=hook,
    )
    pub._wait_for_finished = lambda creation_id, timeout_seconds=120: {"ok": True}
    pub._publish_container = lambda *a, **k: {"id": "media_999"}

    result = pub.publish_carousel(
        image_urls=["https://example.com/a.jpg"],
        caption="cap",
    )
    assert result["ok"] is True
    assert hook_calls == [], "hook must not fire when caller omits dedup_subjects"


# ----- publish_reel -------------------------------------------------

def test_dedup_hook_raises_blocks_publish_reel(monkeypatch):
    counter = _PostCounter()
    monkeypatch.setattr("src.publish.instagram_publisher.requests.post", counter)

    def reject_everything(subjects):
        raise DuplicatePostError("dup")

    pub = InstagramGraphPublisher(
        account_id="acct",
        access_token="tok",
        dedup_check=reject_everything,
    )

    with pytest.raises(DuplicatePostError):
        pub.publish_reel(
            video_url="https://example.com/r.mp4",
            caption="cap",
            dedup_subjects=["The reel script body..."],
        )
    assert counter.calls == []


# ----- caller wiring ------------------------------------------------

def test_make_reel_wires_dedup_check_into_publisher():
    """Static check: pipelines/reel/make_reel.py constructs the publisher
    with dedup_check=brain.assert_no_duplicate and passes dedup_subjects
    on publish_reel. Verified by reading the source so we catch a future
    edit that removes the wiring.
    """
    src = (Path(__file__).resolve().parents[1] / "pipelines" / "reel" / "make_reel.py").read_text()
    assert (
        "dedup_check=brain.assert_no_duplicate" in src
        or "dedup_check=_brain.assert_no_duplicate" in src
    ), "make_reel.py must wire brain.assert_no_duplicate into the publisher"
    assert "dedup_subjects=[claim]" in src, (
        "make_reel.py must pass dedup_subjects on publish_reel"
    )


def test_ship_manual_wires_dedup_check_into_publisher():
    """Same contract for the manual carousel pipeline."""
    src = (Path(__file__).resolve().parents[1] / "pipelines" / "manual" / "ship_manual_post.py").read_text()
    assert "dedup_check=brain.assert_no_duplicate" in src
    assert "dedup_subjects=[editorial_claim]" in src
