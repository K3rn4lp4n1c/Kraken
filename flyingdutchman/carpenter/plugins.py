from pathlib import Path
from dataclasses import dataclass, field
from playwright.async_api import StorageState
from .extensions import Campaign, Plugin

import json
import logging

__all__ = ["PLUGINS"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIRPATH = PROJECT_ROOT.parent / "assets"
HAR_DIRPATH = ASSETS_DIRPATH / "har"

@dataclass
class _HTB(Plugin):
    _sso_callback_url: str = "https://ctf.hackthebox.com/api/sso/callback"
    _logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    def _extract_token_from_har(self, har_path: Path) -> str:
        if not har_path.exists(): raise FileNotFoundError(f"Auth HAR file is missing {har_path}")
        with open(har_path, "r") as f: har = json.load(f)
        for entry in har["log"]["entries"]:
            request: dict[str, str] = dict(entry["request"])
            response: dict[str, dict] = dict(entry["response"])

            if (request["url"].startswith(self._sso_callback_url) and response["status"] == 200):
                body = response.get("content", {}).get("text", "")
                payload = dict(json.loads(body))

                token = payload.get("access_token")
                if token:
                    return token

        raise ValueError("No successful HTB SSO callback token found")

    def _make_storage_state(self, token: str) -> StorageState:
        return {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://ctf.hackthebox.com",
                    "localStorage": [
                        {
                            "name": "ctf-token",
                            "value": token,
                        }
                    ],
                }
            ],
        }
    
    async def authenticate(self, campaign: Campaign, **kwargs) -> dict:
       har_path = HAR_DIRPATH / str(campaign.id) / "authentication.har"
       token = self._extract_token_from_har(har_path)
       endpoint = tuple(kwargs.get("endpoint", ()))
       reqInit = endpoint[1] if endpoint and isinstance(endpoint[1], dict) else {}
       reqInit["headers"] = reqInit.get("headers", {})
       reqInit["headers"]["Authorization"] = f"Bearer {token}"
       formatted_endpoint = (endpoint[0], reqInit) if endpoint else ()
       kwargs["endpoint"] = formatted_endpoint
       browser = campaign._browser_context
       if browser is None: raise RuntimeError("Browser context is not initialized")
       storage_state = self._make_storage_state(token)
       await browser.set_storage_state(storage_state)
       return kwargs

PLUGINS: dict[str, Plugin] = {
    "htb": _HTB("htb"),
}