from __future__ import annotations

import time
from typing import Sequence

import requests


class InstagramGraphPublisher:
    def __init__(self, account_id: str, access_token: str, graph_version: str = "v21.0",
                 host: str = "graph.facebook.com") -> None:
        self.account_id = account_id
        self.access_token = access_token
        # graph.instagram.com for the Instagram-login flow,
        # graph.facebook.com for the Facebook-login flow.
        self.base_url = f"https://{host}/{graph_version}"

    def is_configured(self) -> bool:
        return bool(self.account_id and self.access_token)

    def publish_carousel(self, image_urls: Sequence[str], caption: str) -> dict:
        if not self.is_configured():
            return {"ok": False, "error": "Missing Instagram API credentials"}
        if not image_urls:
            return {"ok": False, "error": "No image URLs provided"}
        if len(image_urls) > 10:
            return {"ok": False, "error": f"Carousel exceeds Instagram's 10-image cap ({len(image_urls)})"}
        if len(caption) > 2200:
            return {"ok": False, "error": f"Caption exceeds Instagram's 2200-char cap ({len(caption)})"}

        child_creation_ids = []
        for url in image_urls:
            child = self._create_media_container(image_url=url, is_carousel_item=True)
            if not child.get("id"):
                return {"ok": False, "error": f"Child media creation failed: {child}"}
            child_creation_ids.append(child["id"])

        parent = self._create_carousel_container(child_creation_ids, caption)
        if not parent.get("id"):
            return {"ok": False, "error": f"Parent media creation failed: {parent}"}

        ready = self._wait_for_finished(parent["id"], timeout_seconds=120)
        if not ready.get("ok"):
            return {"ok": False, "error": f"Container not ready: {ready}"}

        publish_result = self._publish_container(parent["id"], expected_media_type="CAROUSEL_ALBUM")
        if "id" not in publish_result:
            return {"ok": False, "error": f"Publish failed: {publish_result}"}
        return {"ok": True, "ig_media_id": publish_result["id"]}

    def _wait_for_finished(self, creation_id: str, timeout_seconds: int = 300) -> dict:
        """Poll the container until status_code == FINISHED.

        Polls every 15 seconds — not every 3. At 3s polling and 300s timeout
        that's 100 API calls per container. With multiple containers per session
        this burns through Instagram's Graph API rate limit (code 4 / 1349210).
        At 15s polling the same 300s window costs only 20 calls.
        """
        url = f"{self.base_url}/{creation_id}"
        params = {"fields": "status_code,status", "access_token": self.access_token}
        # Initial wait — Instagram needs at least 10s to start processing
        time.sleep(10)
        deadline = time.time() + timeout_seconds
        last = {}
        while time.time() < deadline:
            try:
                last = requests.get(url, params=params, timeout=10).json()
            except requests.RequestException as exc:
                return {"ok": False, "error": f"poll error: {exc}"}
            # Handle rate limit gracefully — back off and retry rather than fail
            if last.get("error", {}).get("code") == 4:
                time.sleep(30)
                continue
            code = last.get("status_code")
            if code == "FINISHED":
                return {"ok": True}
            if code in {"ERROR", "EXPIRED"}:
                return {"ok": False, "error": last}
            time.sleep(15)
        return {"ok": False, "error": f"timeout after {timeout_seconds}s, last={last}"}

    def _create_media_container(self, image_url: str, is_carousel_item: bool = False) -> dict:
        params = {
            "image_url": image_url,
            "is_carousel_item": "true" if is_carousel_item else "false",
            "access_token": self.access_token,
        }
        url = f"{self.base_url}/{self.account_id}/media"
        return requests.post(url, data=params, timeout=20).json()

    def _create_carousel_container(self, children: Sequence[str], caption: str) -> dict:
        params = {
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
            "access_token": self.access_token,
        }
        url = f"{self.base_url}/{self.account_id}/media"
        return requests.post(url, data=params, timeout=20).json()

    def _publish_container(self, creation_id: str, expected_media_type: str | None = None) -> dict:
        """POST to media_publish. Includes recovery: IG sometimes processes
        the publish successfully but returns an error response (e.g. rate-limit
        errors returned after the commit). We wait briefly then check recent
        account media for a post that matches the expected media_type and
        appeared after this call started. Without the type+time window check,
        the recovery could falsely attribute an unrelated carousel published
        seconds earlier to this reel call (audit 2026-05-01 finding 4)."""
        params = {"creation_id": creation_id, "access_token": self.access_token}
        url = f"{self.base_url}/{self.account_id}/media_publish"
        publish_started_at = time.time()
        try:
            data = requests.post(url, data=params, timeout=20).json()
        except requests.RequestException as exc:
            data = {"error": str(exc)}
        if "id" in data:
            return data
        # Response lacked an id — but IG may have committed the post anyway.
        # Probe with a tight window starting AFTER this publish began.
        time.sleep(4)
        recovered = self._find_recently_published(
            since_ts=publish_started_at - 5,  # small backstop for clock drift
            expected_media_type=expected_media_type,
        )
        if recovered:
            return {"id": recovered, "_recovered": True}
        return data

    def post_to_stories(self, image_url: str, link_url: str | None = None) -> dict:
        """Post a single image to IG Stories.

        IMPORTANT: Instagram Graph API does not currently support publishing
        Story stickers (including link stickers) via this endpoint. We accept
        `link_url` so callers can pass intent, but the Story is posted as a
        plain story and we return a warning.

        Returns {"ok": True, "ig_media_id": "...", "link_requested": bool,
                 "link_applied": bool, "warning": "...?"}
        or {"ok": False, "error": "..."}.
        """
        try:
            create_url = f"{self.base_url}/{self.account_id}/media"
            r = requests.post(create_url, data={
                "image_url": image_url,
                "media_type": "STORIES",
                "access_token": self.access_token,
            }, timeout=20).json()
            link_requested = bool(link_url)
            link_applied = False
            warning: str | None = (
                "Instagram Graph API does not support Story link stickers; posted without tappable link."
                if link_requested else None
            )

            creation_id = r.get("id")
            if not creation_id:
                return {"ok": False, "error": f"Stories container failed: {r}"}
            time.sleep(2)
            pub = requests.post(
                f"{self.base_url}/{self.account_id}/media_publish",
                data={"creation_id": creation_id, "access_token": self.access_token},
                timeout=20,
            ).json()
            ig_id = pub.get("id")
            if not ig_id:
                return {"ok": False, "error": f"Stories publish failed: {pub}"}
            result = {
                "ok": True,
                "ig_media_id": ig_id,
                "link_requested": link_requested,
                "link_applied": link_applied,
            }
            if warning:
                result["warning"] = warning
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ig_permalink(self, ig_media_id: str) -> str | None:
        """Fetch the instagram.com/p/... permalink for a media id."""
        try:
            r = requests.get(
                f"{self.base_url}/{ig_media_id}",
                params={"fields": "permalink", "access_token": self.access_token},
                timeout=8,
            ).json()
            return r.get("permalink")
        except Exception:
            return None

    def publish_reel(
        self,
        video_url: str,
        caption: str,
        cover_url: str | None = None,
        share_to_feed: bool = True,
        poll_timeout_s: int = 300,
    ) -> dict:
        """Upload and publish a Reel via the IG Graph API.

        Args:
            video_url:      Public HTTPS URL to an MP4 (Cloudinary, etc.).
            caption:        Caption text (max 2200 chars).
            share_to_feed:  If True the Reel also appears on the profile grid.
            poll_timeout_s: Max seconds to wait for IG to process the video.

        Returns:
            {"ok": True, "ig_media_id": "..."} or {"ok": False, "error": "..."}.
        """
        if not self.is_configured():
            return {"ok": False, "error": "Missing Instagram API credentials"}
        if not video_url:
            return {"ok": False, "error": "No video_url provided"}
        if len(caption) > 2200:
            caption = caption[:2197] + "..."

        # Step 1: Create media container
        params: dict = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": self.access_token,
        }
        if cover_url:
            params["cover_url"] = cover_url
        create_url = f"{self.base_url}/{self.account_id}/media"
        try:
            r = requests.post(create_url, data=params, timeout=30).json()
        except requests.RequestException as exc:
            return {"ok": False, "error": f"Container creation request failed: {exc}"}

        creation_id = r.get("id")
        if not creation_id:
            return {"ok": False, "error": f"Reel container creation failed: {r}"}

        # Step 2: Poll until FINISHED (video encoding takes 1-5 minutes)
        print(f"  [reels] container={creation_id}, polling up to {poll_timeout_s}s...")
        ready = self._wait_for_finished(creation_id, timeout_seconds=poll_timeout_s)
        if not ready.get("ok"):
            return {"ok": False, "error": f"Reel not ready after {poll_timeout_s}s: {ready}"}

        # Step 3: Publish
        publish_result = self._publish_container(creation_id, expected_media_type="REELS")
        if "id" not in publish_result:
            return {"ok": False, "error": f"Reel publish failed: {publish_result}"}

        ig_media_id = publish_result["id"]
        recovered = publish_result.get("_recovered", False)
        print(f"  [reels] published ig_media_id={ig_media_id}" + (" (recovered)" if recovered else ""))
        return {"ok": True, "ig_media_id": ig_media_id}

    def _find_recently_published(
        self,
        since_ts: float | None = None,
        expected_media_type: str | None = None,
        within_seconds: int = 60,
    ) -> str | None:
        """Return ig_media_id of a post that appeared on the account AFTER
        `since_ts` (epoch seconds) and matches `expected_media_type` (e.g.
        'REELS', 'CAROUSEL_ALBUM', 'IMAGE'). Used to recover from false-
        failure responses on _publish_container.

        If `since_ts` is None, falls back to a 60-second lookback. The
        expected_media_type filter prevents the recovery picking up an
        unrelated post (e.g. a carousel published moments before).
        """
        import datetime
        now = time.time()
        floor_ts = since_ts if since_ts is not None else (now - within_seconds)
        try:
            url = f"{self.base_url}/{self.account_id}/media"
            r = requests.get(url, params={
                "fields": "id,timestamp,media_type,media_product_type",
                "limit": 10,
                "access_token": self.access_token,
            }, timeout=10).json()
            for post in r.get("data", []):
                ts_str = post.get("timestamp", "")
                if not ts_str:
                    continue
                ts = datetime.datetime.fromisoformat(
                    ts_str.replace("Z", "+00:00")
                ).timestamp()
                if ts < floor_ts:
                    continue
                if expected_media_type:
                    pt = post.get("media_product_type") or ""
                    mt = post.get("media_type") or ""
                    if expected_media_type not in (pt, mt):
                        continue
                return post["id"]
        except Exception:
            pass
        return None
