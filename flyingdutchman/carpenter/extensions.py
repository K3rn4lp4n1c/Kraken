from __future__ import annotations
from pathlib import Path
from datetime import datetime
from sqlite3 import Connection
from urllib.parse import urlparse
from dataclasses import dataclass, field
from playwright.async_api import BrowserContext, Page
from flyingdutchman.powderboy import env, send_request, PlaywrightManager as PM

import json

@dataclass
class Challenge:
    id: str
    title: str
    description: str = ""
    points: int = 0
    category: str = "unknown"
    prerequisite: Challenge | None = None
    flag: str = ""

@dataclass
class Campaign:
    id: str
    name: str
    url: str
    status: str
    datetime: datetime
    auth_path: Path
    playwright_manager: PM
    challenges: list[Challenge] = field(default_factory=list)
    _authenticated: bool = field(default=False, init=False)
    _browser_context: BrowserContext | None = field(default=None, init=False)

    async def _save_state(self) -> None:
        """
        Save the state of the campaign's browser context to a file.

        Args:
            auth_path (Path): The path to the directory where the state file will be saved.
        """
        if self._browser_context is None:
            await self.playwright_manager.remove_context(self.id)
        else:
            await self.playwright_manager.set_context(self.id, self._browser_context)
        
    async def _load_state(self) -> None:
        """
        Load the state of the campaign's browser context from a file.

        Args:
            auth_path (Path): The path to the directory where the state file is located.
        """
        context = await self.playwright_manager.get_context(self.id)
        self._browser_context = context

    def _update_status(self, conn: Connection, new_status: str) -> None:
        """
        Update the status of the campaign in the database.

        Args:
            new_status (str): The new status to set for the campaign.
        """
        table_name = env("CAMPAIGNS_TABLE")[0]
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE {} SET status = ? WHERE id = ?".format(table_name), (new_status, self.id))
            conn.commit()
        self.status = new_status
    
    async def start(self, conn: Connection, p: PM, **options) -> None:
        if self._browser_context is not None:
            raise ValueError("Browser context already started. Perhaps restart the campaign")
        self._browser_context = await p.create_context_with_callee_as_owner(**options)
        if self._browser_context is None:
            raise ValueError("Failed to create a browser context")
        await self._save_state()
        self._update_status(conn, "running")
        
    async def stop(self, conn: Connection) -> None:
        await self._load_state()
        if self._browser_context is None:
            raise ValueError("No browser context to stop. Perhaps start the campaign first")
        self._browser_context = None
        await self._save_state()
        self._update_status(conn, "stopped")
    
    async def restart(self, conn: Connection, **options) -> None:
        await self._load_state()
        if self._browser_context is not None:
            self._browser_context = None
            await self._save_state()
        self._browser_context = await self.playwright_manager.create_context_with_callee_as_owner(**options)
        if self._browser_context is None: raise ValueError("Failed to create a browser context")
        await self._save_state()
        self._update_status(conn, "running")
    
    async def pause(self, conn: Connection) -> BrowserContext:
        await self._load_state()
        if self._browser_context is None:
            raise ValueError("No browser context to pause. Perhaps start the campaign first")
        paused_context = self._browser_context
        self._browser_context = None
        self._update_status(conn, "paused")
        return paused_context
    
    async def resume(self, conn: Connection, paused_context: BrowserContext | None = None) -> None:
        if self._browser_context is not None:
            raise ValueError("Browser context already running. Perhaps pause the campaign first")
        if paused_context is None: await self._load_state()
        else: self._browser_context = paused_context
        await self._save_state()
        self._update_status(conn, "running")

    async def authenticate(self, conn: Connection, url: str, expected_codes: tuple[int, ...],
                           reqInit: dict | None = None) -> None:
        """
        Authenticate the campaign with a given browser context.

        Args:
            url (str): The URL to send the authentication request to.
            reqInit (dict): Optional dictionary containing request initialization parameters.
        """
        await self._load_state()
        if self._browser_context is None:
            raise ValueError("No browser context provided. Perhaps restart the campaign")
        table_name = env("CAMPAIGNS_TABLE")[0]
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT credentials FROM {} WHERE id = ?".format(table_name), (self.id,))
            row = cursor.fetchone()
            if row is None: raise ValueError(f"No credentials found for campaign id: {self.id}")
            credentials: dict = json.loads(row[0])
            if reqInit is None: reqInit = {}
            for key, value in credentials.items(): reqInit['body'] = str(reqInit['body']).replace(f"{{{key}}}", value)
            if '{{{' in str(reqInit['body']) and '}}}' in str(reqInit['body']):
                raise ValueError(f"Not all placeholders in body were filled: {reqInit['body']}")
            if self._browser_context is None or self._browser_context.is_closed():
                raise ValueError("No browser context provided. Perhaps restart the campaign")
            if urlparse(url).netloc != urlparse(self.url).netloc:
                raise ValueError("The provided URL does not match the campaign's URL.")
            page: Page | None = None
            for p in self._browser_context.pages:
                if p.url == url:
                    if page is not None:
                        raise ValueError(f"Multiple pages found with the same URL: {url}. Perhaps restart the campaign.")
                    page = p
            if page is None: page = await self._browser_context.new_page()
            resp = await send_request(page, url, reqInit)
            if resp["status"] not in expected_codes:
                raise ValueError(f"Authentication failed ({resp['status']}), data: {resp['data']}")
        #await self._browser_context.storage_state(path=auth_path / f"{self.id}.json")
        await self._save_state()