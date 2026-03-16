from __future__ import annotations

import base64
from pathlib import Path

import msal

_CACHE_FILE = Path(".oauth2_token_cache.json")

_SCOPES = [
    "https://outlook.office365.com/IMAP.AccessAsUser.All",
    "https://outlook.office365.com/SMTP.Send",
]


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if _CACHE_FILE.exists():
        cache.deserialize(_CACHE_FILE.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _CACHE_FILE.write_text(cache.serialize(), encoding="utf-8")


def get_access_token(client_id: str, tenant_id: str, user: str, client_secret: str) -> str:
    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    accounts = app.get_accounts(username=user)
    if accounts:
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    # No cached token — trigger device code flow (user opens a URL once)
    flow = app.initiate_device_flow(scopes=_SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to start device flow: {flow}")

    print("\n" + "=" * 60)
    print(flow["message"])
    print("=" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"OAuth2 login failed: {result.get('error_description', result)}")

    _save_cache(cache)
    return result["access_token"]


def build_xoauth2_raw(user: str, access_token: str) -> bytes:
    """Raw (un-encoded) XOAUTH2 string — imaplib base64-encodes it internally."""
    return f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()


def build_xoauth2_bytes(user: str, access_token: str) -> bytes:
    """Base64-encoded XOAUTH2 string — for use with SMTP docmd."""
    return base64.b64encode(build_xoauth2_raw(user, access_token))
