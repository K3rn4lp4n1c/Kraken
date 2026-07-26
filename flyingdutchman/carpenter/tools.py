from . import LOGGER_HANDLER_MARKER
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Generator
from playwright.async_api import Page
from urllib.parse import urlparse

import os
import logging
import sqlite3

def configure_logger(debug: bool = False) -> None:
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
    logger = logging.getLogger("flyingdutchman")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Prevent the same record from also reaching the root logger.
    logger.propagate = False

    # Do not install the same application handler more than once.
    for existing_handler in logger.handlers:
        if getattr(existing_handler, LOGGER_HANDLER_MARKER, False):
            existing_handler.setLevel(logging.DEBUG if debug else logging.INFO)
            return

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    formatter = fancyFormatter()
    handler.setFormatter(formatter)
    setattr(handler, LOGGER_HANDLER_MARKER, True)
    logger.addHandler(handler)

def env(keys: str, defaults: str = '', delimiter: str = ",") -> tuple[str, ...]:
    """
    Retrieve environment variables.

    Args:
        - vars      (str) : variables set in the environment
        - defaults  (str) : default values for the variables, separated by the specified delimiter
        - delimiter (str) : the character used to separate default values in the defaults string
    
    Returns:
        tuple (number of arguments passed): values of environmental variables
    """
    values: list[str] = []
    l_keys = keys.split(delimiter); l_defaults = defaults.split(delimiter)
    while len(l_defaults) < len(l_keys): l_defaults.append('') # Pad defaults with empty strings if not enough provided
    for key, default in zip(l_keys, l_defaults):
        key = key.strip()
        if not key: raise ValueError("Environment variable names must not be empty.")
        value = os.getenv(key)
        if value: values.append(value)
        elif default: values.append(default.strip())
    
    if len(values) != len(l_keys):
        raise Exception(f"Some keys in {l_keys} not set in environment without defaults.")

    return tuple(values)

@contextmanager
def sqlite3_connect(path: Path) -> Generator[sqlite3.Connection]:
    """
    Establishes a connection to the SQLite3 database.
    Returns:
        sqlite3.Connection: A connection object to the SQLite3 database.
    """
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()

async def send_request(page: Page, campaign_url: str, endpoint: tuple[str, dict | None]) -> dict:
        """
        Send a request to the campaign's URL using the provided browser context.

        Args:
            url (str): The URL to send the request to.
            reqInit (dict): Optional dictionary containing request initialization parameters.

        Returns:
            dict: A dictionary containing the response status and data.
        """
        url = endpoint[0]
        alike = (
            urlparse(url).scheme == urlparse(campaign_url).scheme and
            urlparse(url).netloc == urlparse(campaign_url).netloc and
            urlparse(url).port == urlparse(campaign_url).port
        )
        if not alike:
            raise ValueError("The provided URL does not match the campaign's URL.")
        reqInit = endpoint[1] if len(endpoint) > 1 else {}
        response = await page.evaluate(
        """
        async ({ url, requestInit }) => {
            try {
                const response = await fetch(url, requestInit);
                const text = await response.text();

                let data;
                try {
                    data = JSON.parse(text);
                } catch {
                    data = text;
                }

                return {
                    status: response.status,
                    url: response.url,
                    ok: response.ok,
                    data,
                };
            } catch (error) {
                return {
                    status: 500,
                    data: {
                        error: String(error),
                    },
                };
            }
        }
        """, {"url": url, "requestInit": reqInit})
        return response