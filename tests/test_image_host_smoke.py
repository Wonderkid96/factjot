"""Smoke tests for src/publish/image_host.py.

Goal: contract test for imgbb + tmpfiles upload behaviour and the
ChainedImageHost failover path. Uploads to real hosts during pipeline
runs; this suite mocks requests so it stays under 30s and offline.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.publish.image_host import (  # noqa: E402
    ChainedImageHost,
    CloudinaryHost,
    ImgbbHost,
    TmpfilesHost,
    make_image_host,
)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _resp(status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.ok = 200 <= status_code < 300
    m.json.return_value = json_body or {}
    m.text = ""
    return m


def _png_path(tmp_path: Path, name: str = "img.png") -> Path:
    """Write a small valid PNG to disk and return its path."""
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", (8, 8), color=(0, 0, 0)).save(p, "PNG")
    return p


# ---------------------------------------------------------------------- #
# ImgbbHost
# ---------------------------------------------------------------------- #


def test_imgbb_upload_returns_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("IMGBB_API_KEY", "stub-key")
    p = _png_path(tmp_path)

    def fake_post(url, params=None, data=None, timeout=None):
        # imgbb takes the API key as a query param and the base64 image
        # bytes as form data.
        assert "api.imgbb.com" in url
        assert params and params["key"] == "stub-key"
        assert data and "image" in data
        return _resp(200, {
            "success": True,
            "data": {
                "url": "https://i.ibb.co/abc/img.png",
                "expiration": "604800",
            },
        })

    with patch("src.publish.image_host.requests.post", side_effect=fake_post):
        host = ImgbbHost(api_key="stub-key")
        hosted = host.upload(p)
    assert hosted.public_url == "https://i.ibb.co/abc/img.png"
    assert hosted.expires_at == "604800"


def test_imgbb_upload_raises_on_http_error(tmp_path: Path) -> None:
    p = _png_path(tmp_path)
    with patch("src.publish.image_host.requests.post",
               return_value=_resp(503, {})), \
         pytest.raises(RuntimeError, match="imgbb upload failed"):
        ImgbbHost(api_key="k").upload(p)


def test_imgbb_upload_raises_on_unsuccessful_body(tmp_path: Path) -> None:
    """imgbb returns 200 but success=false on bad input."""
    p = _png_path(tmp_path)
    with patch("src.publish.image_host.requests.post",
               return_value=_resp(200, {"success": False, "error": {"message": "bad"}})), \
         pytest.raises(RuntimeError, match="not successful"):
        ImgbbHost(api_key="k").upload(p)


def test_imgbb_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("IMGBB_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="IMGBB_API_KEY"):
        ImgbbHost()


def test_imgbb_salts_each_upload_with_unique_nonce(tmp_path: Path) -> None:
    """Each upload must produce different bytes so imgbb's content-hash
    dedupe gives us a fresh URL on retry. Verifies the salt in
    `factjot-salt` PNG text chunk is present and varies."""
    p = _png_path(tmp_path)
    bytes1 = ImgbbHost._salted_png_bytes(p)
    bytes2 = ImgbbHost._salted_png_bytes(p)
    assert bytes1 != bytes2, "salted bytes must differ across calls"
    # Confirm it parses back as a valid PNG with the expected text chunk.
    from PIL import Image
    img = Image.open(BytesIO(bytes1))
    img.load()
    assert "factjot-salt" in (img.info or {})


# ---------------------------------------------------------------------- #
# TmpfilesHost
# ---------------------------------------------------------------------- #


def test_tmpfiles_upload_returns_direct_download_url(tmp_path: Path) -> None:
    """tmpfiles returns a viewer URL; upload must rewrite to the
    /dl/ direct-download path because Meta cannot fetch the viewer page."""
    p = _png_path(tmp_path)

    def fake_post(url, files=None, data=None, timeout=None):
        assert url == TmpfilesHost.UPLOAD_URL
        return _resp(200, {
            "status": "success",
            "data": {"url": "https://tmpfiles.org/12345/img.png"},
        })

    with patch("src.publish.image_host.requests.post", side_effect=fake_post):
        hosted = TmpfilesHost().upload(p)
    assert hosted.public_url == "https://tmpfiles.org/dl/12345/img.png"


def test_tmpfiles_forces_https(tmp_path: Path) -> None:
    """Even if the API returns http://, tmpfiles host must rewrite to https."""
    p = _png_path(tmp_path)

    def fake_post(url, files=None, data=None, timeout=None):
        return _resp(200, {
            "status": "success",
            "data": {"url": "http://tmpfiles.org/9/img.png"},
        })

    with patch("src.publish.image_host.requests.post", side_effect=fake_post):
        hosted = TmpfilesHost().upload(p)
    assert hosted.public_url.startswith("https://")
    assert "/dl/" in hosted.public_url


def test_tmpfiles_raises_on_failure_body(tmp_path: Path) -> None:
    p = _png_path(tmp_path)
    with patch("src.publish.image_host.requests.post",
               return_value=_resp(200, {"status": "error"})), \
         pytest.raises(RuntimeError, match="not successful"):
        TmpfilesHost().upload(p)


def test_tmpfiles_raises_on_http_error(tmp_path: Path) -> None:
    p = _png_path(tmp_path)
    with patch("src.publish.image_host.requests.post",
               return_value=_resp(500, {})), \
         pytest.raises(RuntimeError, match="tmpfiles upload failed"):
        TmpfilesHost().upload(p)


# ---------------------------------------------------------------------- #
# CloudinaryHost
# ---------------------------------------------------------------------- #


def test_cloudinary_upload_returns_secure_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "demo")
    monkeypatch.setenv("CLOUDINARY_UPLOAD_PRESET", "preset")
    p = _png_path(tmp_path)

    def fake_post(url, files=None, data=None, timeout=None):
        assert "demo" in url
        return _resp(200, {"secure_url": "https://res.cloudinary.com/demo/abc.png"})

    with patch("src.publish.image_host.requests.post", side_effect=fake_post):
        hosted = CloudinaryHost().upload(p)
    assert hosted.public_url == "https://res.cloudinary.com/demo/abc.png"


def test_cloudinary_requires_both_env_vars(monkeypatch) -> None:
    monkeypatch.delenv("CLOUDINARY_CLOUD_NAME", raising=False)
    monkeypatch.delenv("CLOUDINARY_UPLOAD_PRESET", raising=False)
    with pytest.raises(RuntimeError, match="CLOUDINARY_CLOUD_NAME"):
        CloudinaryHost()


# ---------------------------------------------------------------------- #
# ChainedImageHost: failover behaviour
# ---------------------------------------------------------------------- #


def test_chain_falls_back_to_secondary_when_primary_fails_to_construct(
    tmp_path: Path, monkeypatch,
) -> None:
    """When the first chain entry can't be constructed (missing creds),
    the chain skips it and instantiates the next entry."""
    # imgbb missing creds, tmpfiles always works (no config required).
    monkeypatch.delenv("IMGBB_API_KEY", raising=False)
    chain = ChainedImageHost(["imgbb", "tmpfiles"])
    # The cursor has advanced past imgbb to tmpfiles.
    assert chain.active_name == "tmpfiles"


def test_chain_returns_no_backends_on_all_failed(monkeypatch) -> None:
    monkeypatch.delenv("IMGBB_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDINARY_CLOUD_NAME", raising=False)
    monkeypatch.delenv("CLOUDINARY_UPLOAD_PRESET", raising=False)
    with pytest.raises(RuntimeError, match="No image host backends"):
        ChainedImageHost(["imgbb", "cloudinary"])


def test_chain_next_backend_advances_cursor(monkeypatch) -> None:
    """After a failed publish on host A, callers invoke next_backend()
    to roll forward to host B; future uploads use B."""
    monkeypatch.setenv("IMGBB_API_KEY", "k")
    chain = ChainedImageHost(["imgbb", "tmpfiles"])
    assert chain.active_name == "imgbb"
    nxt = chain.next_backend()
    assert nxt == "tmpfiles"
    assert chain.active_name == "tmpfiles"


def test_chain_next_backend_raises_when_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("IMGBB_API_KEY", "k")
    chain = ChainedImageHost(["imgbb", "tmpfiles"])
    chain.next_backend()  # imgbb -> tmpfiles
    with pytest.raises(RuntimeError, match="No image host backends"):
        chain.next_backend()  # tmpfiles -> exhausted


# ---------------------------------------------------------------------- #
# make_image_host: factory
# ---------------------------------------------------------------------- #


def test_make_image_host_default_is_imgbb(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_HOST", raising=False)
    monkeypatch.setenv("IMGBB_API_KEY", "k")
    host = make_image_host()
    assert isinstance(host, ImgbbHost)


def test_make_image_host_named_tmpfiles(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_HOST", "tmpfiles")
    host = make_image_host()
    assert isinstance(host, TmpfilesHost)


def test_make_image_host_chain_returns_chained(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_HOST", "imgbb,tmpfiles")
    monkeypatch.setenv("IMGBB_API_KEY", "k")
    host = make_image_host()
    assert isinstance(host, ChainedImageHost)
    assert host.backend_names == ["imgbb", "tmpfiles"]


def test_make_image_host_unknown_name_raises(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_HOST", "nonexistent")
    with pytest.raises(RuntimeError, match="Unknown image host"):
        make_image_host()
