from . import navigator
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urlsplit
from playwright.async_api import async_playwright
from flyingdutchman import DB_DIRPATH, HAR_DIRPATH
from flyingdutchman.powderboy import *

import logging
import hashlib

CAMPAIGNS_DB_PATH = DB_DIRPATH / "chronicles.sqlite3"

async def _scout_campaign(id: str, url: str, force: bool = False) -> tuple[bool, str, str]:
    """
    Records a HAR file for a given campaign by visiting the provided URL.
    If the HAR file already exists and force is set to True, it will overwrite the existing file.
    It also checks if the provided URL matches the expected domain for the campaign.

    Args:
        id (str): The ID of the campaign.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    try:
        campaigns_table = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(CAMPAIGNS_DB_PATH) as conn:
            cursor = conn.cursor()
            query = "SELECT url from {} WHERE id = ?".format(campaigns_table)
            cursor.execute(query, (id,))
            row = cursor.fetchone()
            if row is None:
                return False, f"No campaign found with id: {id}", ""
            exp_url = row[0]
            if not isinstance(exp_url, str) or not exp_url:
                return False, f"Invalid URL for campaign id: {id}", ""
            parsed_url = urlparse(url)
            if parsed_url.netloc != urlsplit(exp_url).netloc:
                return False, f"'{url}' does not match expected domain for campaign id: {id}", ""
            har_dir = HAR_DIRPATH / id
            har_path = hashlib.md5(parsed_url.geturl().encode()).hexdigest() + ".har"
            Path.mkdir(har_dir, parents=True, exist_ok=True)
            har_file_path = har_dir / har_path
            if har_file_path.exists() and not force:
                m_timestamp = har_file_path.stat().st_mtime
                m_time = datetime.fromtimestamp(m_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                har_content = har_file_path.read_text(encoding='utf-8')
                return True, f"Campaign '{id}' already scouted at {m_time}.", har_content
            har_file_path.unlink(missing_ok=True)
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                browser_context_args: dict = {
                    "record_har_path": har_file_path,
                    "record_har_content": "embed", # NOTE: This is going to be a large one, hehe
                    "record_har_mode": "full", # NOTE: We want everything, no?
                }
                context = await browser.new_context(**browser_context_args)
                try:
                    page = await context.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    await page.wait_for_timeout(5_000)
                finally:
                    await context.close()
                    await browser.close()
                if not har_file_path.exists():
                    return False, f"Failed to record HAR file for campaign '{id}'.", ""
                har_content = har_file_path.read_text(encoding='utf-8')
            return True, f"Campaign '{id}' scouted successfully.", har_content
    except Exception as e:
        logging.exception("Error scouting campaign: %s", str(e))
        return False, f"Internal Server Error in fetching campaigns", ""

@navigator.tool()
async def scout_campaign(id: str, url: str, force: bool = False) -> dict:
    """
    Records a HAR file for a given campaign by visiting the provided URL.
    If the HAR file already exists and force is set to True, it will overwrite the existing file.
    It also checks if the provided URL matches the expected domain for the campaign.

    Args:
        id (str): The ID of the campaign.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    success, message, har_content = await _scout_campaign(id, url, force)
    return {"success": success, "message": message, "har_content": har_content}

async def triage() -> tuple[list[str], list[bool]]:
    configure_logger(__name__, debug=True)
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []
    # NOTE: Challenges are autoincremented as they are inserted starting from 1, so use 0 ;)
    id, url = "1", "https://ctf.defsec.club"

    checklist.append("Scouting the campaign")
    try:
        success, message, _ = await _scout_campaign(id, url)
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.error(f"Error scouting campaign: {str(e)}")
    return checklist, checks