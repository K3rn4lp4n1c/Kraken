from __future__ import annotations
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode
from dataclasses import dataclass, field
from collections.abc import AsyncGenerator
from playwright.async_api import Playwright, Browser, BrowserContext, Page, async_playwright
from .tools import send_request, sqlite3_connect, env, does_url_match_campaign

import asyncio
import json
import logging

class PlaywrightManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._headed_browser: Browser | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)

    async def start(self, **options) -> None:
        """Start Playwright and launch one shared browser."""

        async with self._lifecycle_lock:
            if self._browser is not None and self._browser.is_connected():
                self._logger.warning("PlaywrightManager is already started.")
                return

            playwright = await async_playwright().start()

            try:
                browser = await playwright.chromium.launch(headless=True, **options)
            except Exception:
                await playwright.stop()
                raise

            self._playwright = playwright
            self._browser = browser

    async def start_headed(self, **options) -> None:
        """Start Playwright and launch one shared headed browser."""

        async with self._lifecycle_lock:
            if self._headed_browser is not None and self._headed_browser.is_connected():
                self._logger.warning("Headed Browser is already started.")
                return

            if self._playwright is None:
                raise RuntimeError("PlaywrightManager has not been started. Call start() first.")
            playwright = self._playwright

            try:
                headed_browser = await playwright.chromium.launch(headless=False, **options)
            except Exception:
                await playwright.stop()
                raise

            self._headed_browser = headed_browser

    async def stop(self) -> None:
        """Close all contexts, close the browser, and stop Playwright."""

        async with self._lifecycle_lock:
            if self._browser is None and self._playwright is None:
                self._logger.warning("PlaywrightManager is already stopped.")
                return

            browser = self._browser
            playwright = self._playwright

            self._browser = None
            self._playwright = None

            try:
                if browser is not None:
                    for context in list(browser.contexts):
                        try: await context.close()
                        except Exception: self._logger.exception("Failed to close browser context.")
                    await browser.close()
            finally:
                if playwright is not None: await playwright.stop()

    async def stop_headed(self) -> None:
        """Close all contexts, close the headed browser, and stop Playwright."""

        async with self._lifecycle_lock:
            if self._headed_browser is None:
                self._logger.warning("Headed Browser is already stopped.")
                return

            headed_browser = self._headed_browser
            self._headed_browser = None

            try:
                if headed_browser is not None:
                    for context in list(headed_browser.contexts):
                        try: await context.close()
                        except Exception: self._logger.exception("Failed to close browser context.")
                    await headed_browser.close()
            except Exception:
                self._logger.exception("Failed to stop headed browser.")
                raise

    async def create_context_with_caller_as_owner(self, headless: bool = True,
                                                **options) -> AsyncGenerator[BrowserContext]:
        """Create and automatically close an isolated browser context."""

        browser = self._browser if headless else self._headed_browser

        if browser is None or not browser.is_connected():
            raise RuntimeError("PlaywrightManager has not been started")

        context = await browser.new_context(**options)

        try:
            yield context
        finally:
            await context.close()
    
    async def create_context_with_callee_as_owner(self, headless = True,
                                                **options) -> BrowserContext:
        browser = self._browser if headless else self._headed_browser

        if browser is None or not browser.is_connected():
            raise RuntimeError("PlaywrightManager has not been started")
        return await browser.new_context(**options)

@dataclass
class Challenge:
    id: str
    name: str
    url: str
    method: str
    headers: dict
    body: dict | None = None

@dataclass
class Campaign:
    id: str
    name: str
    url: str
    status: str
    datetime: datetime
    paths: dict[str, Path] = field(default_factory=dict)
    challenges: list[Challenge] = field(default_factory=list)
    _logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__), init=False)
    _authenticated: bool = field(default=False, init=False)
    _browser_context: BrowserContext | None = field(default=None, init=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self._auth_path = self.paths['playwright_auth'] / str(self.id)
        self._db_filepath = self.paths['db']
        self._auth_path.mkdir(parents=True, exist_ok=True)
        if not self._db_filepath.exists():
            raise FileNotFoundError(f"Database file not found at {self._db_filepath}. Ensure the database is initialized.")

    def _update_status(self, new_status: str) -> None:
        """
        Update the status of the campaign in the database.

        Args:
            new_status (str): The new status to set for the campaign.
        """
        table_name = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(self._db_filepath) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE {} SET status = ? WHERE id = ?".format(table_name), (new_status, self.id))
            conn.commit()
            self.status = new_status
    
    async def start(self, p: PlaywrightManager, headless: bool = True, **options) -> None:
        async with self._lifecycle_lock:
            if self._browser_context is not None:
                raise ValueError("Browser context already started. Perhaps restart the campaign")
            if self.status == "paused":
                raise ValueError("Cannot start a paused campaign. Use resume instead")
            self._browser_context = await p.create_context_with_callee_as_owner(headless, **options)
            if self._browser_context is None:
                raise ValueError("Failed to create a browser context")
            self._update_status("running")
        
    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self.status == "paused":
                raise ValueError("Cannot stop a paused campaign. Use resume first")
            if self._browser_context is None:
                raise ValueError("No browser context to stop. Perhaps start the campaign first")
            await self._browser_context.close()
            self._browser_context = None
            self._update_status("stopped")
    
    async def restart(self, p: PlaywrightManager, headless: bool = True, **options) -> None:
        async with self._lifecycle_lock:
            if self.status == "paused":
                raise ValueError("Cannot restart a paused campaign. Use resume first")
            if self._browser_context is not None:
                await self._browser_context.close()
                self._browser_context = None
            self._browser_context = await p.create_context_with_callee_as_owner(headless, **options)
            if self._browser_context is None: raise ValueError("Failed to create a browser context")
            self._update_status("running")
    
    async def pause(self) -> BrowserContext:
        async with self._lifecycle_lock:
            if self._browser_context is None:
                raise ValueError("No browser context to pause. Perhaps start the campaign first")
            paused_context = self._browser_context
            self._browser_context = None
            self._update_status("paused")
            return paused_context
    
    async def resume(self, paused_context: BrowserContext) -> None:
        async with self._lifecycle_lock:
            if self._browser_context is not None:
                raise ValueError("Browser context already running. Perhaps pause the campaign first")
            else: self._browser_context = paused_context
            self._update_status("running")

    def _normalize_request_body(self, body: dict, interpolated_values: dict) -> str:
        """
        Normalize the request body by replacing placeholders with actual credential values.

        Args:
            body (dict): The original request body containing placeholders.
            interpolated_values (dict): A dictionary containing the actual values to replace the placeholders.

        Returns:
            dict: The normalized request body with placeholders replaced by actual values.
        """
        normalized_body = {}
        encoding = str(body.get("encoding", "json"))
        fields = dict(body.get("fields", {}))
        for key, value in fields.items():
            # Key like "name" or "password"
            if isinstance(value, dict) and "$flyingdutchman" in value:
                # Value like {"$flyingdutchman": {"kind": "credentials", "name": "name"}}
                sub_dict = dict(value["$flyingdutchman"])
                if sub_dict["kind"] in interpolated_values:
                    normalized_body[key] = interpolated_values[sub_dict["kind"]][sub_dict["name"]]
                else:
                    raise ValueError(f"Unknown kind '{sub_dict['kind']}' in request body normalization.")
            else:
                normalized_body[key] = value
        if encoding == "form":
            return urlencode(normalized_body, doseq=True)
        if encoding == "query":
            return '&'.join(f"{k}={v}" for k, v in normalized_body.items())
        if encoding == "text":
            return '\n'.join(f"{k}={v}" for k, v in normalized_body.items())
        elif encoding == "json":
            return json.dumps(normalized_body)
        else:
            raise ValueError(f"Unsupported encoding type: {encoding}. Supported types are 'json' and 'form'.")

    async def authenticate(self, page_url: str, endpoint: tuple[str, dict|None],
                           expected_codes: tuple[int, ...]) -> None:
        """
        Authenticate the campaign with a given browser context.

        Args:
            page_url (str): The URL of the page to authenticate.
            endpoint (tuple[str, dict|None]): A tuple containing the endpoint URL and optional request initialization parameters.
            expected_codes (tuple[int, ...]): A tuple of expected HTTP status codes for successful authentication.
        Raises:
            ValueError: If the browser context is not available, if the provided URL does not match
        """
        async with self._lifecycle_lock:
            if self._browser_context is None:
                raise ValueError("No browser context provided. Perhaps restart the campaign")
            table_name = env("CAMPAIGNS_TABLE")[0]
            with sqlite3_connect(self._db_filepath) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT credentials FROM {} WHERE id = ?".format(table_name), (self.id,))
                row = cursor.fetchone()
                if row is None: raise ValueError(f"No credentials found for campaign id: {self.id}")
                credentials: dict = json.loads(row[0])
                reqInit = endpoint[1].copy() if endpoint[1] is not None else {}
                body: dict | str = dict(reqInit.get('body', {})).copy()
                body = self._normalize_request_body(body, {"credentials": credentials})
                reqInit['body'] = body
                new_endpoint = (endpoint[0], reqInit)
                if self._browser_context is None or self._browser_context.is_closed():
                    raise ValueError("No browser context provided. Perhaps restart the campaign")
                if not does_url_match_campaign(page_url, self.url):
                    raise ValueError("The provided URL does not match the campaign's URL.")
                page: Page | None = None
                for p in self._browser_context.pages:
                    if p.url == page_url:
                        if page is not None:
                            raise ValueError(f"Multiple pages have the same URL: {page_url}. Perhaps restart the campaign.")
                        page = p
                if page is None:
                    page = await self._browser_context.new_page()
                    resp = await page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                resp = await send_request(page, page_url, new_endpoint)
                            
                resp_ok = resp.get("ok")
                if resp_ok is not None and not resp_ok:
                    self._logger.warning(f"Failed to send HTTP request: Response data:"
                                        f"{str(resp['data'])[:200]}")
                    raise ValueError(f"Authentication failed ({resp['status']}): {str(resp['data'])}")
                if resp["status"] not in expected_codes:
                    self._logger.warning(f"Authentication failed ({resp['status']}). "
                                       f"Expected codes: {expected_codes}. "
                                       f"Response data: {str(resp['data'])[:200]}..."
                                    )
                    raise ValueError(f"Authentication failed ({resp['status']}): {str(resp['data'])}...")
            self._authenticated = True

@dataclass
class CampaignManager:
    _campaigns: dict[str, Campaign] = field(default_factory=dict, init=False)
    _logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__), init=False)

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        return self._campaigns.get(campaign_id, None)

    def add_campaign(self, campaign: Campaign) -> None:
        if str(campaign.id) in self._campaigns:
            raise ValueError(f"Campaign with id {campaign.id} already exists. Remove it first")
        self._campaigns[str(campaign.id)] = campaign

    async def remove_campaign(self, campaign_id: str) -> None:
        if campaign_id not in self._campaigns:
            raise ValueError(f"Campaign with id {campaign_id} does not exist. Add it first")
        await self._campaigns[campaign_id].stop()
        del self._campaigns[campaign_id]

    async def clear(self) -> None:
        for campaign_id in list(self._campaigns.keys()): await self.remove_campaign(campaign_id)