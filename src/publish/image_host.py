"""Free image hosting for Instagram Graph API ingestion.

Two backends are supported. Pick one via the `IMAGE_HOST` environment
variable (default `imgbb`):

    IMAGE_HOST=imgbb        - primary, simple, free key
    IMAGE_HOST=cloudinary   - backup, used when imgbb's CDN gets soft-blocked
                              by Meta's media fetcher (we've seen that happen
                              after heavy upload activity in a single session)

Use `make_image_host()` to construct whichever the env asks for. Each backend
returns the same `HostedImage` shape so callers don't care which one's active.

Per-upload PNG salting
----------------------
Both backends deduplicate uploads by content hash - same bytes in, same URL
out. That's a problem during iterative work (multiple dry-runs of the same
post) because Meta's IG ingestion fetcher can blacklist a URL after a few
too many of its own retries, and we'd then be stuck with a permanently-
broken URL.

To avoid that, every upload appends a tiny PNG `tEXt` metadata chunk with a
per-call random nonce before sending. The salt is invisible to renderers
and viewers, but flips the content hash, so the host gives us a brand-new
URL on every call. Failed publishes can then retry cleanly.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, PngImagePlugin

log = logging.getLogger(__name__)


@dataclass
class HostedImage:
    local_path: Path
    public_url: str
    expires_at: str | None = None


class ImgbbHost:
    """imgbb adapter. https://api.imgbb.com/"""

    UPLOAD_URL = "https://api.imgbb.com/1/upload"

    # Default 7-day expiration: Meta usually fetches the URL within seconds
    # during the IG carousel ingest. A week is generous margin for debugging
    # plus retry. After that imgbb auto-deletes, keeping our footprint on
    # their service small and reducing the chance of anti-abuse throttling.
    # imgbb accepts 60..15552000 (60s to 6 months); pass any int to override.
    DEFAULT_EXPIRATION_SECONDS = 7 * 24 * 60 * 60  # 604800

    def __init__(self, api_key: str | None = None, expiration_seconds: int | None = None) -> None:
        self.api_key = (api_key or os.getenv("IMGBB_API_KEY", "")).strip()
        if not self.api_key:
            raise RuntimeError(
                "IMGBB_API_KEY is not set. Get a free key at https://api.imgbb.com/ and add it to .env."
            )
        # If caller passes None we still apply the default. Pass 0 to opt out.
        if expiration_seconds is None:
            expiration_seconds = self.DEFAULT_EXPIRATION_SECONDS
        self.expiration_seconds = expiration_seconds

    def upload(self, local_path: str | Path) -> HostedImage:
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(path)
        # Route by source format. PNG inputs are re-encoded with a salt
        # chunk so imgbb's content-hash dedupe issues a fresh URL on
        # retry. JPEG inputs upload raw - re-encoding through PIL would
        # discard format and re-emit as PNG (the bug that caused reel
        # covers to be silently rejected by IG, 2026-05-11). For reel
        # thumbnails the salt is unnecessary anyway: each reel produces
        # a unique frame + overlay, so imgbb dedupe is a non-issue.
        payload = base64.b64encode(self._bytes_for_upload(path)).decode("ascii")
        params = {"key": self.api_key}
        if self.expiration_seconds:
            params["expiration"] = str(self.expiration_seconds)
        resp = requests.post(self.UPLOAD_URL, params=params,
                             data={"image": payload}, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"imgbb upload failed ({resp.status_code}): {resp.text[:200]}")
        body = resp.json()
        if not body.get("success"):
            raise RuntimeError(f"imgbb upload not successful: {body}")
        data = body.get("data", {})
        url = data.get("url") or (data.get("image") or {}).get("url")
        if not url:
            raise RuntimeError(f"imgbb response missing url: {body}")
        return HostedImage(local_path=path, public_url=url,
                           expires_at=data.get("expiration"))

    def upload_many(self, local_paths: list[str | Path]) -> list[HostedImage]:
        out: list[HostedImage] = []
        for p in local_paths:
            out.append(self.upload(p))
        return out

    @staticmethod
    def _bytes_for_upload(path: Path) -> bytes:
        """Return image bytes for the imgbb upload, format-preserving.

        PNG inputs are re-encoded with a `tEXt` salt chunk so imgbb's
        content-hash dedupe doesn't hand back a stale URL on retry
        (carousel use case: cover slides can be byte-identical across
        re-renders).

        JPEG inputs upload raw. Re-encoding a JPEG via PIL.save("PNG")
        was the 2026-05-11 reel-cover bug: imgbb received PNG bytes,
        returned a `.png` URL, and IG Reels silently rejected the
        cover (Reels covers accept JPEG only). For reels the salt is
        moot anyway - each frame + overlay differs between runs.

        Unknown formats pass through raw.
        """
        suffix = path.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            return path.read_bytes()
        if suffix != ".png":
            return path.read_bytes()
        try:
            img = Image.open(path)
            img.load()
            info = PngImagePlugin.PngInfo()
            for key, value in (img.info or {}).items():
                if isinstance(value, (str, bytes)):
                    try:
                        info.add_text(key, value if isinstance(value, str) else value.decode("utf-8", "replace"))
                    except Exception:
                        pass
            info.add_text("factjot-salt", secrets.token_hex(12))
            from io import BytesIO
            buf = BytesIO()
            img.save(buf, "PNG", pnginfo=info, optimize=False)
            return buf.getvalue()
        except Exception as exc:
            log.warning("PNG salt failed for %s (%s); uploading raw bytes", path, exc)
            return path.read_bytes()

    # Back-compat alias: any external caller still reaching for the old
    # name gets the same behaviour. Remove after one cycle.
    _salted_png_bytes = _bytes_for_upload


class CloudinaryHost:
    """Cloudinary unsigned-upload adapter. https://cloudinary.com/

    Used as a fallback when imgbb is unavailable or its CDN is being
    soft-blocked by Meta. Uses unsigned uploads (no API secret needed)
    via a named upload_preset configured in the Cloudinary dashboard.

    Env vars:
        CLOUDINARY_CLOUD_NAME    - your account's cloud name (public)
        CLOUDINARY_UPLOAD_PRESET - name of an unsigned upload preset
    """

    UPLOAD_URL_TEMPLATE = "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"

    def __init__(
        self,
        cloud_name: str | None = None,
        upload_preset: str | None = None,
    ) -> None:
        self.cloud_name = (cloud_name or os.getenv("CLOUDINARY_CLOUD_NAME", "")).strip()
        self.upload_preset = (upload_preset or os.getenv("CLOUDINARY_UPLOAD_PRESET", "")).strip()
        if not self.cloud_name:
            raise RuntimeError(
                "CLOUDINARY_CLOUD_NAME is not set. Sign up at cloudinary.com "
                "and add your cloud_name to .env."
            )
        if not self.upload_preset:
            raise RuntimeError(
                "CLOUDINARY_UPLOAD_PRESET is not set. In the Cloudinary "
                "dashboard, go to Settings → Upload → Upload presets, create "
                "an UNSIGNED preset (any name), and add it to .env."
            )
        self._url = self.UPLOAD_URL_TEMPLATE.format(cloud_name=self.cloud_name)

    def upload(self, local_path: str | Path) -> HostedImage:
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(path)
        # Salt the PNG so Cloudinary's content-hash dedupe gives us a fresh
        # URL on every call (same reason as ImgbbHost).
        salted = ImgbbHost._salted_png_bytes(path)
        files = {"file": (path.name, salted, "image/png")}
        data = {"upload_preset": self.upload_preset}
        resp = requests.post(self._url, files=files, data=data, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Cloudinary upload failed ({resp.status_code}): {resp.text[:200]}")
        body = resp.json()
        url = body.get("secure_url") or body.get("url")
        if not url:
            raise RuntimeError(f"Cloudinary response missing url: {body}")
        return HostedImage(local_path=path, public_url=url, expires_at=None)

    def upload_many(self, local_paths: list[str | Path]) -> list[HostedImage]:
        return [self.upload(p) for p in local_paths]


class CloudinaryVideoHost:
    """Cloudinary video upload adapter — fallback for reel uploads.

    TmpfilesHost is primary. This is called automatically by _upload_video
    in make_reel.py when tmpfiles is unreachable, for videos ≤5 MB (Meta
    413s Cloudinary URLs on larger files).

    Env vars (same account as CloudinaryHost):
        CLOUDINARY_CLOUD_NAME    - your cloud name (public)
        CLOUDINARY_UPLOAD_PRESET - unsigned upload preset name
    """

    def __init__(self) -> None:
        self.cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
        self.upload_preset = os.getenv("CLOUDINARY_UPLOAD_PRESET", "").strip()
        if not self.cloud_name or not self.upload_preset:
            raise RuntimeError(
                "CLOUDINARY_CLOUD_NAME and CLOUDINARY_UPLOAD_PRESET must be set "
                "for video hosting. Sign up free at cloudinary.com, create an "
                "unsigned upload preset, and add both vars to .env and GitHub Secrets."
            )
        self._url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/video/upload"

    def upload(self, local_path: str | Path) -> HostedImage:
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        mime = "video/mp4" if path.suffix.lower() == ".mp4" else "video/quicktime"
        files = {"file": (path.name, data, mime)}
        resp = requests.post(
            self._url,
            files=files,
            data={"upload_preset": self.upload_preset},
            timeout=120,
        )
        if not resp.ok:
            raise RuntimeError(
                f"Cloudinary video upload failed ({resp.status_code}): {resp.text[:300]}"
            )
        body = resp.json()
        url = body.get("secure_url") or body.get("url")
        if not url:
            raise RuntimeError(f"Cloudinary video response missing url: {body}")
        return HostedImage(local_path=path, public_url=url, expires_at=None)


class TmpfilesHost:
    """tmpfiles.org adapter - anonymous, no signup, ~1h auto-expiry.

    PRIMARY video host for Reels (as of 2026-05-02). Meta fetches the video
    URL within the polling window, so the 1-hour expiry is not a problem.
    Cloudinary was the previous primary but was disabled after Meta 413'd its
    URLs. See _upload_video in make_reel.py for where this is called.
    """

    UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"

    def __init__(self) -> None:
        # No config needed - anonymous host.
        pass

    def upload(self, local_path: str | Path) -> HostedImage:
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(path)
        suffix = path.suffix.lower()
        if suffix in {".mp4", ".mov", ".webm"}:
            # Video: send raw bytes with correct MIME type
            mime = "video/mp4" if suffix == ".mp4" else "video/webm"
            data = path.read_bytes()
            files = {"file": (path.name, data, mime)}
        else:
            # Image: salt so retries produce fresh URLs (tmpfiles dedupes by hash)
            salted = ImgbbHost._salted_png_bytes(path)
            files = {"file": (path.name, salted, "image/png")}
        resp = requests.post(self.UPLOAD_URL, files=files, timeout=120)
        if not resp.ok:
            raise RuntimeError(f"tmpfiles upload failed ({resp.status_code}): {resp.text[:200]}")
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"tmpfiles upload not successful: {body}")
        viewer_url = (body.get("data") or {}).get("url", "")
        if not viewer_url:
            raise RuntimeError(f"tmpfiles response missing url: {body}")
        # tmpfiles returns a viewer URL like https://tmpfiles.org/12345/file.png
        # The direct-download URL injects /dl/ after the host. Meta can only
        # fetch the direct URL - the viewer URL serves an HTML page.
        # Also force HTTPS regardless of what the API returned.
        direct = viewer_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        if direct.startswith("http://"):
            direct = "https://" + direct[len("http://"):]
        return HostedImage(local_path=path, public_url=direct, expires_at=None)

    def upload_many(self, local_paths: list[str | Path]) -> list[HostedImage]:
        return [self.upload(p) for p in local_paths]


# Backend name → factory callable. Keep new backends here.
_HOST_FACTORIES = {
    "imgbb": ImgbbHost,
    "cloudinary": CloudinaryHost,
    "tmpfiles": TmpfilesHost,
}


def _make_named_host(name: str):
    name = name.strip().lower()
    if not name:
        name = "imgbb"
    factory = _HOST_FACTORIES.get(name)
    if factory is None:
        raise RuntimeError(
            f"Unknown image host {name!r}. Known: {sorted(_HOST_FACTORIES)}."
        )
    return factory()


def make_image_host():
    """Construct the image host (or fallback chain) named by `IMAGE_HOST`.

    Single host:
        IMAGE_HOST=imgbb        → ImgbbHost
        IMAGE_HOST=cloudinary   → CloudinaryHost
        IMAGE_HOST=tmpfiles     → TmpfilesHost

    Comma-separated chain (left to right priority):
        IMAGE_HOST=cloudinary,imgbb,tmpfiles
            → ChainedImageHost. Uploads via the FIRST host. If ship_*
              detects an IG fetch failure on those URLs, it can call
              `host.next_backend()` to swap to the next entry and re-host.

    Default (env unset): imgbb single-host. Backwards-compatible.
    """
    raw = os.getenv("IMAGE_HOST", "imgbb").strip()
    parts = [p for p in (s.strip() for s in raw.split(",")) if p]
    if not parts:
        parts = ["imgbb"]
    if len(parts) == 1:
        return _make_named_host(parts[0])
    return ChainedImageHost(parts)


class ChainedImageHost:
    """Wraps an ordered list of host backends with manual failover.

    On construction the first available backend is active. Callers upload
    normally. If an IG publish then fails with a media-fetch error, the
    caller invokes `next_backend()` to roll forward to the next host;
    subsequent uploads use that one. The chain raises StopIteration
    (caught by callers as RuntimeError) when no backends remain.

    Why not auto-detect IG failure here? Because the failure is downstream
    of upload - we only know about it when InstagramGraphPublisher returns
    an error. Keeping the failover decision in the ship script makes the
    error path explicit and easy to log.
    """

    def __init__(self, backend_names: list[str]) -> None:
        self.backend_names = list(backend_names)
        self._cursor = -1
        self._current = None
        self._instantiate_next()

    def _instantiate_next(self) -> None:
        self._cursor += 1
        while self._cursor < len(self.backend_names):
            try:
                self._current = _make_named_host(self.backend_names[self._cursor])
                return
            except RuntimeError as exc:
                log.warning(
                    "Skipping host %r in chain (%s)",
                    self.backend_names[self._cursor], exc,
                )
                self._cursor += 1
        raise RuntimeError(
            f"No image host backends available. Tried: {self.backend_names}"
        )

    @property
    def active_name(self) -> str:
        return self.backend_names[self._cursor]

    def next_backend(self) -> str:
        """Roll to the next backend; return its name. Raises if exhausted."""
        prev = self.active_name
        self._instantiate_next()
        log.warning("Image host failover: %s -> %s", prev, self.active_name)
        return self.active_name

    def upload(self, local_path):
        return self._current.upload(local_path)

    def upload_many(self, local_paths):
        return self._current.upload_many(local_paths)
