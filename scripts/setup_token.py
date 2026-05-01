"""Exchange a short-lived Instagram access token for a long-lived one,
discover the Instagram account ID, and write everything to .env.

Run interactively:
    python3 scripts/setup_token.py

You will be asked for:
    1. App ID            (Meta dev dashboard → Settings → Basic → App ID)
    2. App Secret        (Meta dev dashboard → Settings → Basic → App Secret → Show)
    3. Short-lived token (just generated in API setup with Instagram login)

The script auto-detects whether the token is from the Instagram-login flow
(token prefix `IGAA`, host graph.instagram.com) or the Facebook-login flow
(token prefix `EAA`, host graph.facebook.com) and uses the right exchange
endpoint. The long-lived token + IG account ID are appended to .env. The
short-lived token is never logged.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

import requests

ENV_PATH = Path(".env")


def _ask(prompt: str, *, secret: bool = False) -> str:
    if secret:
        return getpass.getpass(prompt + ": ").strip()
    return input(prompt + ": ").strip()


def detect_flow(token: str) -> str:
    if token.startswith("IGAA") or token.startswith("IGQ"):
        return "instagram_login"
    return "facebook_login"


def exchange_long_lived(flow: str, app_id: str, app_secret: str, short_token: str) -> dict:
    if flow == "instagram_login":
        url = "https://graph.instagram.com/access_token"
        params = {
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        }
    else:
        url = "https://graph.facebook.com/v21.0/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }
    resp = requests.get(url, params=params, timeout=15)
    if not resp.ok:
        raise RuntimeError(f"token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def lookup_ig_account(flow: str, long_token: str) -> tuple[str, str | None]:
    """Return (instagram_account_id, facebook_page_id_or_None)."""
    if flow == "instagram_login":
        resp = requests.get(
            "https://graph.instagram.com/me",
            params={"fields": "id,username,user_id", "access_token": long_token},
            timeout=10,
        )
        if not resp.ok:
            raise RuntimeError(f"IG /me lookup failed: {resp.text}")
        data = resp.json()
        # `user_id` is the numeric Instagram User ID required by /media endpoints.
        ig_id = str(data.get("user_id") or data.get("id"))
        return ig_id, None
    # Facebook-login flow: walk /me/accounts → find linked IG.
    resp = requests.get(
        "https://graph.facebook.com/v21.0/me/accounts",
        params={"access_token": long_token, "fields": "id,name,instagram_business_account"},
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f"FB /me/accounts lookup failed: {resp.text}")
    data = resp.json().get("data", [])
    for page in data:
        ig = page.get("instagram_business_account")
        if ig and ig.get("id"):
            return str(ig["id"]), str(page["id"])
    raise RuntimeError("No Facebook Page in this account is linked to an Instagram Business account.")


def update_env(updates: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
    existing.update(updates)
    lines = [f"{k}={v}" for k, v in existing.items() if v]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    print("factjot — token setup\n")
    env = _read_env()
    # Pull credentials from .env when present so paste artefacts can't sneak
    # in via a masked prompt. Tolerant to common slot mix-ups: the App ID may
    # have ended up in INSTAGRAM_ACCOUNT_ID and the short token in
    # META_ACCESS_TOKEN. Pull from any reasonable source.
    app_id = (
        env.get("META_APP_ID")
        or env.get("INSTAGRAM_APP_ID")
        or env.get("INSTAGRAM_ACCOUNT_ID")
        or _ask("Meta App ID (or Instagram App ID)")
    )
    app_secret = env.get("META_APP_SECRET") or _ask("Instagram App Secret", secret=True)
    short_token = (
        env.get("META_SHORT_TOKEN")
        or env.get("META_ACCESS_TOKEN")
        or _ask("Short-lived access token (just generated in Meta dashboard)", secret=True)
    )

    # Defensive: strip whitespace and confirm length looks sane.
    app_id = app_id.strip()
    app_secret = app_secret.strip()
    short_token = short_token.strip()
    print(f"  app_id length:     {len(app_id)}")
    print(f"  app_secret length: {len(app_secret)}  (Instagram app secrets are typically 32 chars)")
    print(f"  short_token length: {len(short_token)}  (Instagram tokens are typically 100-300 chars)")

    flow = detect_flow(short_token)
    print(f"\nDetected flow: {flow}")

    print("Exchanging for long-lived token...")
    long_token: str
    try:
        exchange = exchange_long_lived(flow, app_id, app_secret, short_token)
        long_token = exchange.get("access_token", "")
        if not long_token:
            raise RuntimeError(f"exchange returned no token: {exchange}")
        expires = exchange.get("expires_in")
        if expires:
            print(f"  long-lived token issued, expires in ~{expires // 86400} days")
        else:
            print("  long-lived token issued (no expiry returned, treat as 60 days)")
    except Exception as exc:
        print(f"  exchange failed: {exc}")
        print("  falling back to the short-lived token (~1 hour life). We can re-run the exchange later.")
        long_token = short_token

    print("Looking up Instagram account ID...")
    ig_id, page_id = lookup_ig_account(flow, long_token)
    print(f"  Instagram Account ID: {ig_id}")
    if page_id:
        print(f"  Facebook Page ID:     {page_id}")

    updates = {
        "INSTAGRAM_ACCOUNT_ID": ig_id,
        "META_ACCESS_TOKEN": long_token,
        "META_GRAPH_VERSION": "v21.0",
        "META_GRAPH_HOST": "graph.instagram.com" if flow == "instagram_login" else "graph.facebook.com",
        "META_LOGIN_FLOW": flow,
    }
    if page_id:
        updates["FACEBOOK_PAGE_ID"] = page_id

    print("\nWriting to .env (existing keys preserved)...")
    update_env(updates)
    print(".env updated. Done.")
    print("\nNext: add IMGBB_API_KEY to .env (free at https://api.imgbb.com/) then run:")
    print("    python3 scripts/check_meta_setup.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
