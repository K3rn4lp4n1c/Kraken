from pathlib import Path
from dataclasses import dataclass, field
from playwright.async_api import StorageState
from .extensions import Campaign, Plugin, CampaignPlugin, ChallengePlugin, InstanceAndFilesPlugin

import json
import logging

__all__ = ["PLUGINS"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIRPATH = PROJECT_ROOT.parent / "assets"
HAR_DIRPATH = ASSETS_DIRPATH / "har"

@dataclass
class _HTBAuth(CampaignPlugin):
    name: str = "htb-auth"
    description: str = """Hack The Box authentication plugin.
    The plugin extracts the access token from a HAR file generated during the HTB SSO callback
    and sets it in the browser's local storage for authenticated requests.
    This is consistent with the HTB SSO flow,
    where the access token is provided in the callback response after successful authentication.
    The plugin also modifies the request headers to include the access token for subsequent requests.
    The plugin will not navigate to a new page
    or perform any additional actions beyond setting the token in local storage
    and modifying request headers.
    The plugin is intended to be used in headed mode only because HTB flags headless browsers
    and the SSO flow may not work correctly in headless mode.
    The plugin will not set storage state for URLs outside its origin
    which defaults to https://ctf.hackthebox.com
    because local storage is scoped to the origin of the page.
    """
    tags: tuple[str, ...] = ("htb", "authentication", "sso", "token", "plugin")
    _sso_callback_url: str = "https://ctf.hackthebox.com/api/sso/callback"
    _origin_url: str = "https://ctf.hackthebox.com"
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
                    "origin": self._origin_url,
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
       if campaign.headless: raise RuntimeError(f"{self.name} plugin must be used in headed mode")
       har_path = HAR_DIRPATH / str(campaign.id) / "authentication.har"
       token = self._extract_token_from_har(har_path)
       endpoint = tuple(kwargs.get("endpoint", ()))
       reqInit = endpoint[1] if endpoint and isinstance(endpoint[1], dict) else {}
       reqInit["headers"] = reqInit.get("headers", {})
       reqInit["headers"]["Authorization"] = f"Bearer {token}"
       formatted_endpoint = (endpoint[0], reqInit) if endpoint else ()
       kwargs["endpoint"] = formatted_endpoint
       context = await campaign.pause()
       if context is None: raise RuntimeError("Browser context is not initialized")
       storage_state = self._make_storage_state(token)
       await context.set_storage_state(storage_state)
       await campaign.resume(context)
       return kwargs

    async def scout(self, campaign: Campaign, **kwargs) -> dict:
        if campaign.headless: raise RuntimeError(f"{self.name} plugin must be used in headed mode")
        har_path = HAR_DIRPATH / str(campaign.id) / "authentication.har"
        token = self._extract_token_from_har(har_path)
        endpoints: list[tuple[str, dict]] = kwargs.get("endpoints") or []
        for i, endpoint in enumerate(endpoints):
            reqInit = endpoint[1].copy() if isinstance(endpoint[1], dict) else {}
            reqInit["headers"] = reqInit.get("headers", {})
            reqInit["headers"]["Authorization"] = f"Bearer {token}"
            endpoints[i] = (endpoint[0], reqInit)
        kwargs["endpoints"] = endpoints
        return kwargs

PLUGINS: dict[str, Plugin] = {
    "htb-auth": _HTBAuth(),
}