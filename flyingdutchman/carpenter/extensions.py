from __future__ import annotations
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode, urlparse
from dataclasses import dataclass, field
from collections.abc import AsyncGenerator, Callable, Awaitable
from playwright.async_api import Playwright, Browser, BrowserContext, Page, Response, async_playwright
from .utils import send_request, sqlite3_connect, env, does_url_match_campaign

import json
import hashlib
import asyncio
import logging

@dataclass
class PlaywrightManager:
    _playwright: Playwright | None = field(default=None, init=False)
    _browser: Browser | None = field(default=None, init=False)
    _headed_browser: Browser | None = field(default=None, init=False)

    def __post_init__(self) -> None:
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
    
    async def create_context_with_callee_as_owner(self, headless = True, **options) -> BrowserContext:
        browser = self._browser if headless else self._headed_browser

        if browser is None or not browser.is_connected():
            raise RuntimeError("PlaywrightManager has not been started")
        return await browser.new_context(**options)

@dataclass
class Plugin():
    name: str = ""
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

@dataclass
class CampaignPlugin(Plugin):
    async def authenticate(self, campaign: Campaign, **kwargs) -> dict:
        campaign_name = campaign.name
        raise NotImplementedError(f"No authentication for {self.name} on {campaign_name}: {kwargs}")
    async def scout(self, campaign: Campaign, **kwargs) -> dict:
        campaign_name = campaign.name
        raise NotImplementedError(f"No scouting for {self.name} on {campaign_name}: {kwargs}")

@dataclass
class ChallengePlugin(Plugin):
    pass

@dataclass
class InstanceAndFilesPlugin(Plugin):
    pass

@dataclass
class InstanceAndFiles:
    protocol: str
    host: str
    port: int

    async def start(self, campaign: Campaign, **kwargs) -> None:
        pass

    async def stop(self, campaign: Campaign, **kwargs) -> None:
        pass

    async def restart(self, campaign: Campaign, **kwargs) -> None:
        await self.stop(campaign, **kwargs)
        await self.start(campaign, **kwargs)

@dataclass
class Challenge:
    title: str = "N/A"
    description: str = "No description provided"
    points: int = 0
    category: str = "Unknown"
    solves: int = 0
    scout_format: tuple[str, list[tuple[str, dict]]] | None = None # (page_url, [(endpoint_url, request_init), ...])
    platform_id: str | None = None
    instance: InstanceAndFiles | None = None
    flag: str | None = None

    def __iter__(self):
        yield 'title', self.title
        yield 'description', self.description
        yield 'points', self.points
        yield 'category', self.category
        yield 'solves', self.solves
        yield 'scout_format', self.scout_format
        yield 'platform_id', self.platform_id
        yield 'instance', self.instance
        yield 'flag', self.flag

    def __post_init__(self):
        self._logger = logging.getLogger(__name__)
        self._update_lock = asyncio.Lock()

@dataclass
class Campaign:
    id: str
    name: str
    url: str
    status: str
    datetime: datetime
    paths: dict[str, Path] = field(default_factory=dict)
    challenge: str | list[str] | list[dict] | dict | list[Challenge] | None = field(default=None)
    plugins: tuple[Plugin, ...] | None = None
    headless: bool = True
    _authenticated: bool = field(default=False, init=False)
    _browser_context: BrowserContext | None = field(default=None, init=False)
    _challenges: list[Challenge] = field(default_factory=list, init=False)

    @property
    def challenges(self) -> list[Challenge]: return self._challenges

    def __iter__(self):
        yield 'id', self.id

    def __post_init__(self):
        self._logger = logging.getLogger(__name__)
        self._lifecycle_lock = asyncio.Lock()
        self._auth_path = self.paths['playwright_auth'] / str(self.id)
        self._har_dir_path = self.paths['har'] / str(self.id)
        self._db_filepath = self.paths['db']
        self._auth_path.mkdir(parents=True, exist_ok=True)
        if not self._db_filepath.exists():
            raise FileNotFoundError(f"Database file not found at {self._db_filepath}. Ensure the database is initialized.")
        self._select_plugin_methods()
        self._append(self.challenge)  # Ensure challenges are unique upon initialization

    def _select_plugin_methods(self) -> None:
        plugins = self.plugins or []
        for plugin in plugins:
            if not isinstance(plugin, CampaignPlugin):
                raise TypeError(f"Plugin {plugin.name} is not an instance of CampaignPlugin")
            if self._authenticate_plugin is None:
                authenticate: Callable[..., Awaitable[dict]] = getattr(plugin, "authenticate")
                if callable(authenticate): self._authenticate_plugin = authenticate
            if self._scout_plugin is None:
                scout: Callable[..., Awaitable[dict]] = getattr(plugin, "scout")
                if callable(scout): self._scout_plugin = scout

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
            self.headless = headless
            self._update_status("running")

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self.status == "paused":
                raise ValueError("Cannot stop a paused campaign. Use resume first")
            if self._browser_context is None:
                raise ValueError("No browser context to stop. Perhaps start the campaign first")
            await self._browser_context.close()
            self._browser_context = None
            #for c in self._challenges: c.stop()
            self._update_status("stopped")

    async def restart(self, p: PlaywrightManager, headless: bool = True, **options) -> None:
        async with self._lifecycle_lock:
            if self.status == "paused":
                raise ValueError("Cannot restart a paused campaign. Use resume first")
            if self._browser_context is not None:
                await self._browser_context.close()
                self._browser_context = None
            self._browser_context = await p.create_context_with_callee_as_owner(headless, **options)
            if self._browser_context is None:
                raise ValueError("Failed to create a browser context")
            self.headless = headless
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
            self._browser_context = paused_context
            self._update_status("running")

    async def _raise_on_http_status_code(self, resp: Response | int | None, func_name: str) -> None:
        """
        Raise an exception if the HTTP response status code indicates an error.

        Args:
            response (Response): The HTTP response object to check.
        Raises:
            ValueError: If the response status code is not in the 2xx range.
        """
        if resp is None:
            self._logger.warning(f"No response received. Possible network error or timeout in {func_name}.")
            raise ValueError(f"No response received. Possible network error or timeout in {func_name}.")
        if isinstance(resp, Response) and resp.status == 429:
            self._logger.warning(f"Possible Rate Limiting detected. Received HTTP 429 from {func_name}.")
            raise ValueError(f"Possible Rate Limiting detected. Received HTTP 429 from {func_name}.")
        if isinstance(resp, int):
            if resp == 429:
                self._logger.warning(f"Possible Rate Limiting detected. Received HTTP 429 from {func_name}.")
                raise ValueError(f"Possible Rate Limiting detected. Received HTTP 429 from {func_name}.")

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
            if isinstance(value, dict) and "$flyingdutchman" in value:
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
        if encoding == "json":
            return json.dumps(normalized_body) if normalized_body else ""
        raise ValueError(f"Unsupported encoding type: {encoding}. Supported types are 'json' and 'form'.")

    async def _authenticate(self, page_url: str, endpoint: tuple[str, dict | None],
                             expected_codes: tuple[int, ...]) -> None:
        table_name = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(self._db_filepath) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT credentials FROM {} WHERE id = ?".format(table_name), (self.id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"No credentials found for campaign id: {self.id}")
            credentials: dict = json.loads(row[0])

        reqInit = endpoint[1].copy() if endpoint[1] is not None else {}
        body: dict | str = dict(reqInit.get('body', {}) or {}).copy()
        body = self._normalize_request_body(body, {"credentials": credentials})
        reqInit['body'] = body if len(body) > 0 else None
        new_endpoint = (endpoint[0], reqInit)

        if callable(self._authenticate_plugin):
            kwargs = await self._authenticate_plugin(
                self,
                page_url=page_url,
                endpoint=new_endpoint,
                expected_codes=expected_codes,
            )
            page_url = kwargs.get("page_url", page_url)
            new_endpoint = kwargs.get("endpoint", new_endpoint)
            expected_codes = kwargs.get("expected_codes", expected_codes)

        async with self._lifecycle_lock:
            if self._browser_context is None:
                raise ValueError("No browser context provided. Perhaps restart the campaign")
            if self._browser_context.is_closed():
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
                self._logger.debug(f"No existing page found with URL: {page_url}. Creating a new page.")
                page = await self._browser_context.new_page()

            res = await page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
            await self._raise_on_http_status_code(res, "authenticate_page_goto")
            resp = await send_request(page, page_url, new_endpoint)
            await self._raise_on_http_status_code(resp["status"], "authenticate_send_request")

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

    async def _scout(self, page_url: str, force: bool, playwright: PlaywrightManager,
                      headers: dict | None = None, endpoints: list[tuple[str, dict]] | None = None,
                      ) -> tuple[bool, str, str, int]:
        context: BrowserContext | None = None
        har_file_path: Path | None = None
        recovered_via_close = False
        paused = False

        try:
            parsed_url = urlparse(page_url)
            if not does_url_match_campaign(page_url, self.url):
                return False, f"'{page_url}' does not match expected root domain for campaign {self.id}", "", 0
            har_path = hashlib.md5(parsed_url.geturl().encode()).hexdigest() + ".har"
            Path.mkdir(self._har_dir_path, parents=True, exist_ok=True)
            har_file_path = self._har_dir_path / har_path
            if har_file_path.exists() and not force:
                m_timestamp = har_file_path.stat().st_mtime
                m_time = datetime.fromtimestamp(m_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                har_size = har_file_path.stat().st_size
                har_content = har_file_path.read_text(encoding='utf-8')
                return True, f"Campaign {self.id} already scouted at {m_time}.", har_content, har_size
            har_file_path.unlink(missing_ok=True)

            if callable(self._scout_plugin):
                kwargs = await self._scout_plugin(
                    self,
                    page_url=page_url,
                    force=force,
                    playwright=playwright,
                    headers=headers,
                    endpoints=endpoints,
                )
                page_url = kwargs.get("page_url", page_url)
                force = kwargs.get("force", force)
                playwright = kwargs.get("playwright", playwright)
                headers = kwargs.get("headers", headers)
                endpoints = kwargs.get("endpoints", endpoints)

            async with self._lifecycle_lock:
                context = await self.pause()
                paused = True
                page: Page | None = None
                await context.tracing.start_har(har_file_path, mode="full", content="embed")
                for p in context.pages:
                    if p.url == page_url:
                        self._logger.debug(f"Found existing page with URL: {page_url}. Using this page for scouting.")
                        if page is not None:
                            raise ValueError(f"Multiple pages found with the same URL: {page_url}. Perhaps restart the self.")
                        page = p
                if page is None:
                    self._logger.debug(f"No existing page found with URL: {page_url}. Creating a new page.")
                    page = await context.new_page()

                if headers is None:
                    headers = {}
                await page.set_extra_http_headers(headers)
                res = await page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                await self._raise_on_http_status_code(res, "scout_page_goto")
                await page.wait_for_timeout(5_000)

                if endpoints is None:
                    endpoints = []
                for endpoint in endpoints:
                    await asyncio.sleep(5)
                    if not does_url_match_campaign(endpoint[0], self.url):
                        self._logger.warning(f"'{endpoint[0]}' does not match expected root domain for campaign '{self.id}'. Skipping...")
                        continue
                    resp = await send_request(page, page_url, endpoint)
                    await self._raise_on_http_status_code(resp["status"], "scout_send_request")
                    await page.wait_for_timeout(1_000)
                try:
                    await asyncio.wait_for(context.tracing.stop_har(), timeout=30)
                    await self.resume(context)
                except asyncio.TimeoutError:
                    self._logger.warning("stop_har() ack never arrived; forcing close to flush")
                    try:
                        storage_state = await context.storage_state()
                        await asyncio.wait_for(context.close(), timeout=30)
                        context = await playwright.create_context_with_callee_as_owner()
                        await context.set_storage_state(storage_state)
                        await self.resume(context)
                    except Exception:
                        self._logger.warning("close() also failed/timed out; proceeding to restart anyway")
                    await self.restart(playwright)
                    recovered_via_close = True
                context = None
                if not har_file_path.exists() or har_file_path.stat().st_size == 0:
                    return False, f"Failed to record HAR file for campaign '{self.id}'.", "", 0
                har_size = har_file_path.stat().st_size
                har_content = har_file_path.read_text(encoding='utf-8')
                return True, (
                    f"Campaign {self.id} scouted successfully "
                    f"{'with' if recovered_via_close else 'without'} timeout"
                ), har_content, har_size
        except (asyncio.CancelledError, asyncio.TimeoutError):
            async with self._lifecycle_lock:
                await self.restart(playwright)
            if har_file_path is None or not har_file_path.exists() or har_file_path.stat().st_size == 0:
                return False, f"After Timeout, failed to record HAR for campaign {self.id}", "", 0
            har_size = har_file_path.stat().st_size
            har_content = har_file_path.read_text(encoding='utf-8')
            self._logger.error("Timeout while scouting self. Campaign was restarted.")
            return True, "Timeout while scouting. Campaign was restarted.", har_content, har_size
        except ValueError as ve:
            self._logger.error("Error while scouting campaign: %s", str(ve))
            if paused and self._browser_context is None:
                try:
                    new_context = await playwright.create_context_with_callee_as_owner()
                    async with self._lifecycle_lock:
                        await self.resume(new_context)
                except Exception:
                    self._logger.exception("Failed to recover campaign context after ValueError")
            return False, f"Error: {str(ve)}", "", 0
        except Exception as e:
            self._logger.exception("Error while scouting campaign")
            if paused and self._browser_context is None:
                try:
                    new_context = await playwright.create_context_with_callee_as_owner()
                    async with self._lifecycle_lock:
                        await self.resume(new_context)
                except Exception:
                    self._logger.exception("Failed to recover campaign context after unexpected error")
            return False, f"Internal Server Error in fetching campaigns: {str(e)}", "", 0

    def _append(self, new_challenges: str | list[str] | list[dict] | dict | list[Challenge] | None
                ) -> None:
        """
        Append new challenges to the campaign's existing challenges.

        Args:
            new_challenges (list[Challenge]): A list of Challenge objects to be added.
        """
        challenges: list[Challenge] = []
        message_per_challenge: list[str] = []
        if new_challenges is None:
            message = "No new challenges provided. Skipping append operation."
            self._logger.warning(message)
            message_per_challenge.append(message)
            return
        if isinstance(new_challenges, dict):
            challenges = [Challenge(**new_challenges)]
        elif isinstance(new_challenges, str):
            json_loaded_challenges = json.loads(new_challenges)
            if isinstance(json_loaded_challenges, dict):
                challenges = [Challenge(**json_loaded_challenges)]
            elif isinstance(json_loaded_challenges, list):
                for i, challenge in enumerate(json_loaded_challenges):
                    if isinstance(challenge, dict): challenges[i] = Challenge(**challenge)
                    elif not isinstance(challenge, Challenge):
                        message = f"Invalid challenge type at index {i}. Expected dict or Challenge instance."
                        self._logger.warning(message)
                        message_per_challenge.append(message)
                challenges = [c for c in json_loaded_challenges if c is not None]
            else:
                message = "Invalid JSON structure for new_challenges. Expected a dict or a list of dicts."
                self._logger.warning(message)
                message_per_challenge.append(message)
                return
        elif isinstance(new_challenges, list):
            for i, challenge in enumerate(new_challenges):
                if isinstance(challenge, dict): challenges[i] = Challenge(**challenge)
                elif isinstance(challenge, Challenge): challenges.append(challenge)
        else:
            message = "Invalid type for new_challenges. Expected dict or list of dicts/Challenge instances."
            self._logger.warning(message)
            message_per_challenge.append(message)
            return
        for c in challenges:
            if any(existing_c.title.lower() == c.title.lower() for existing_c in self._challenges):
                message = f"Challenge '{c.title.lower()}' already exists. Skipping."
                self._logger.warning(message)
                message_per_challenge.append(message)
            elif any(existing_c.platform_id == c.platform_id and c.platform_id is not None for existing_c in self._challenges):
                message = f"Challenge with platform_id '{c.platform_id}' already exists. Skipping."
                self._logger.warning(message)
                message_per_challenge.append(message)
            else:
                message = f"Appending challenge '{c.title.lower()}' to campaign '{self.name}'."
                self._logger.info(message)
                message_per_challenge.append(message)
                self._challenges.append(c)

    def append(self, new_challenges: list[Challenge]) -> None:
        """
        Append new challenges to the campaign's existing challenges.

        Args:
            new_challenges (list[Challenge]): A list of Challenge objects to be added.
        """
        try:
            self._append(new_challenges)
        except Exception as e:
            self._logger.exception("Error while appending challenges to campaign '%s': %s", self.name, str(e))
            raise ValueError(f"Internal Server Error in appending challenges: {str(e)}") from e

    async def authenticate(self, page_url: str, endpoint: tuple[str, dict | None],
                           expected_codes: tuple[int, ...]) -> None:
        try:
            await self._authenticate(page_url, endpoint, expected_codes)
        except Exception as e:
            self._logger.exception("Authentication failed for campaign %s", self.name)
            raise Exception("Authentication failed for campaign") from e

    async def scout(self, page_url: str, force: bool, playwright: PlaywrightManager,
                    headers: dict | None = None, endpoints: list[tuple[str, dict]] | None = None
                    ) -> tuple[bool, str, str, int]:
        try:
            return await self._scout(page_url, force, playwright, headers, endpoints)
        except Exception as e:
            self._logger.exception("Scouting failed for campaign %s", self.name)
            return False, f"Scouting failed for campaign {self.name}: {str(e)}", "", 0


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