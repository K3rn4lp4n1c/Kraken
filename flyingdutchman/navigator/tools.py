from . import navigator
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urlsplit
from flyingdutchman import DB_PATH, HAR_DIRPATH, playwright, PlaywrightManager as PM
from flyingdutchman.powderboy import env, sqlite3_connect, send_request

import logging
import hashlib

async def _scout_campaign(p: PM, id: str, url: str, force: bool,
                        endpoints: list[tuple[str, dict]] = []) -> tuple[bool, str, str]:
    """
    Records a HAR file for a given campaign by visiting the provided URL.
    If the HAR file already exists and force is set to True, it will overwrite the existing file.
    It also checks if the provided URL matches the expected domain for the campaign.

    Args:
        p (PM): An instance of PlaywrightManager to manage the browser context.
        id (str): The ID of the campaign.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    logger = logging.getLogger(__name__)
    try:
        campaigns_table = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(DB_PATH) as conn:
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
            browser_context_args: dict = {
                    "record_har_path": har_file_path,
                    "record_har_content": "embed", # NOTE: This is going to be a large one, hehe
                    "record_har_mode": "full", # NOTE: We want everything, no?
            }
            async with p.create_context_with_caller_as_owner(browser_context_args) as context:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(5_000)
                for endpoint, reqInit in endpoints:
                    await send_request(page, endpoint, reqInit)
                    await page.wait_for_timeout(1_000)
            if not har_file_path.exists():
                return False, f"Failed to record HAR file for campaign '{id}'.", ""
            har_content = har_file_path.read_text(encoding='utf-8')
            return True, f"Campaign '{id}' scouted successfully.", har_content
    except Exception as e:
        logger.exception("Error scouting campaign: %s", str(e))
        return False, f"Internal Server Error in fetching campaigns", ""

@navigator.tool()
async def scout_campaign(id: str, url: str, force: bool = False,
                        endpoints: list[tuple[str, dict]] = [],) -> dict:
    """
    Records a HAR file for a given campaign by visiting the provided URL.
    If the HAR file already exists and force is set to True, it will overwrite the existing file.
    It also checks if the provided URL matches the expected domain for the campaign.

    Args:
        id (str): The ID of the campaign.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
        endpoints (Optional(list[tuple[str, dict]])): A list of tuples with endpoint URLs and their corresponding request initialization parameters. Default is an empty list.
    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    success, message, har_content = await _scout_campaign(playwright, id, url, force, endpoints)
    return {"success": success, "message": message, "har_content": har_content}

async def triage(playwright: PM, id: str, url: str) -> tuple[list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []

    checklist.append("Scouting the campaign")
    try:
        success, message, _ = await _scout_campaign(playwright, id, url, True, [(url, {})])
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.error(f"Error scouting campaign: {str(e)}")
    return checklist, checks