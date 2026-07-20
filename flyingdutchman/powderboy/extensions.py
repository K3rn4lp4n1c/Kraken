from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from playwright.async_api import Playwright, Browser, BrowserContext, async_playwright

import asyncio
import logging

class PlaywrightManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start Playwright and launch one shared browser."""

        async with self._lifecycle_lock:
            if self._browser is not None and self._browser.is_connected():
                return

            playwright = await async_playwright().start()

            try:
                browser = await playwright.chromium.launch(headless=True)
            except Exception:
                await playwright.stop()
                raise

            self._playwright = playwright
            self._browser = browser

    async def stop(self) -> None:
        """Close the shared browser and stop Playwright."""

        async with self._lifecycle_lock:
            browser = self._browser
            playwright = self._playwright

            self._browser = None
            self._playwright = None

        try:
            if browser is not None:
                await browser.close()
        finally:
            if playwright is not None:
                await playwright.stop()

    @asynccontextmanager
    async def create_context_with_caller_as_owner(self, options: dict = {}) -> AsyncIterator[BrowserContext]:
        """Create and automatically close an isolated browser context."""

        browser = self._browser

        if browser is None or not browser.is_connected():
            raise RuntimeError("PlaywrightManager has not been started")

        context = await browser.new_context(**options)

        try:
            yield context
        finally:
            await context.close()
    
    async def create_context_with_callee_as_owner(self, options: dict = {}) -> BrowserContext:
        browser = self._browser

        if browser is None or not browser.is_connected():
            raise RuntimeError("PlaywrightManager has not been started")

        return await browser.new_context(**options)

class fancyFormatter(logging.Formatter):
    """
    Custom logging formatter to add colors and styles to log messages based on their severity level.
    """
    grey = "\x1b[38;21m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    FORMATS = {
        logging.DEBUG: grey + fmt + reset,
        logging.INFO: grey + fmt + reset,
        logging.WARNING: yellow + fmt + reset,
        logging.ERROR: red + fmt + reset,
        logging.CRITICAL: bold_red + fmt + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)