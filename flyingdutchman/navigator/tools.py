from . import navigator
from pathlib import Path
from datetime import datetime
from sqlite3 import Connection
from urllib.parse import urlparse, urlsplit
from playwright.async_api import Page
from flyingdutchman import playwright, DB_PATH, HAR_DIRPATH, PLAYWRIGHT_AUTH_DIRPATH
from flyingdutchman.carpenter.extensions import Campaign
from flyingdutchman.powderboy import env, sqlite3_connect, send_request

import logging
import hashlib

def get_campaign_by_id(conn: Connection, id: str) -> tuple[bool, str, Campaign | None]:
    """
    Fetches a campaign by its ID from the database.

    Args:
        id (str): The ID of the campaign to fetch.
    Returns:
        tuple[bool, str, Campaign | None]:
        A tuple containing a success status, a message, and the Campaign object if found.
    """
    try:
        table_name = env("CAMPAIGNS_TABLE")[0]
        with conn:
            cursor = conn.cursor()
            fields = ["id", "name", "datetime", "url", "status"]
            cursor.execute("SELECT {} FROM {} WHERE id=?".format(', '.join(fields),table_name),(id,))
            row = cursor.fetchone()
            if row is None:
                return False, f"No campaign found with id: {id}", None
            campaign_data = dict(zip(fields, row))
            campaign = Campaign(
                **campaign_data,
                playwright_manager=playwright,
                auth_path=PLAYWRIGHT_AUTH_DIRPATH
            )
            return True, "Campaign fetched successfully.", campaign
    except Exception as e:
        return False, f"Error fetching campaign by id: {str(e)}", None

async def _scout_campaign(campaign: Campaign, url: str, force: bool, headers: dict | None = None,
                        endpoints: list[tuple[str, dict]] | None = None) -> tuple[bool, str, str]:
    """
    Records a HAR file for a given campaign by visiting the provided URL.
    If the HAR file already exists and force is set to True, it will overwrite the existing file.
    Ensure the provided URL matches the expected domain for the campaign.
    There are no tools to insert campaigns or select credentials.
    Requests to the provided endpoints will be sent after visiting the URL in form of fetch requests
    Responses will be recorded in the HAR file.

    Args:
        campaign (Campaign): The Campaign object for which to record the HAR file.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
        endpoints (Optional(list[tuple[str, dict]])): A list of tuples with endpoint URLs and their corresponding request initialization parameters. Default is an empty list.

    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    logger = logging.getLogger(__name__)
    try:
        parsed_url = urlparse(url)
        if parsed_url.netloc != urlsplit(campaign.url).netloc:
            return False, f"'{url}' does not match expected domain for campaign id: {id}", ""
        har_dir = HAR_DIRPATH / str(campaign.id)
        har_path = hashlib.md5(parsed_url.geturl().encode()).hexdigest() + ".har"
        Path.mkdir(har_dir, parents=True, exist_ok=True)
        har_file_path = har_dir / har_path
        if har_file_path.exists() and not force:
            m_timestamp = har_file_path.stat().st_mtime
            m_time = datetime.fromtimestamp(m_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            har_content = har_file_path.read_text(encoding='utf-8')
            return True, f"Campaign '{campaign.id}' already scouted at {m_time}.", har_content
        har_file_path.unlink(missing_ok=True)
        context = await campaign.pause(sqlite3_connect(DB_PATH))
        page: Page | None = None
        await context.tracing.start_har(har_file_path, mode="full", content="embed")
        for p in context.pages:
            if p.url == url:
                if page is not None:
                    raise ValueError(f"Multiple pages found with the same URL: {url}. Perhaps restart the campaign.")
                page = p
        if page is None:
            page = await context.new_page()
            if headers is None: headers = {}
            await page.set_extra_http_headers(headers)
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5_000)
        if endpoints is None: endpoints = []
        for endpoint, reqInit in endpoints:
            if urlparse(endpoint).netloc != parsed_url.netloc:
                logger.warning(f"'{endpoint}' does not match expected domain for campaign '{campaign.id}'. Skipping...")
                continue
            await send_request(page, endpoint, reqInit)
            await page.wait_for_timeout(1_000)
        await context.tracing.stop_har()
        await campaign.resume(sqlite3_connect(DB_PATH), context)
        if not har_file_path.exists():
            return False, f"Failed to record HAR file for campaign '{id}'.", ""
        har_content = har_file_path.read_text(encoding='utf-8')
        return True, f"Campaign '{campaign.id}' scouted successfully.", har_content
    except ValueError as ve:
        logger.error("Error while scouting campaign: %s", str(ve))
        return False, f"Error: {str(ve)}", ""
    except Exception as e:
        logger.exception("Error while scouting campaign: %s", str(e))
        return False, f"Internal Server Error in fetching campaigns", ""

@navigator.tool()
async def scout_campaign(id: str, url: str, force: bool = False, headers: dict | None = None,
                        endpoints: list[tuple[str, dict]] | None = None) -> dict:
    """
    Records a HAR file for a given campaign by visiting the provided URL.
    If the HAR file already exists and force is set to True, it will overwrite the existing file.
    It also checks if the provided URL matches the expected domain for the campaign.
    If a page with the provided URL exists in the campaign's browser context, it will use that page.
    Otherwise, it will create a new page. Multiple pages with the same URL will raise an error.
    There are no tools to insert campaigns or select credentials so this is safe.
    Requests to the provided endpoints will be sent after visiting the URL in form of fetch requests.
    Responses will be recorded in a HAR file whose filename is a hash of the URL.
    The HAR file will be stored in a directory named after the campaign ID.

    Args:
        id (str): The ID of the campaign.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
        headers (Optional(dict)): Optional dictionary containing request headers that will be set on the page request. Default is None.
        endpoints (Optional(list[tuple[str, dict]])): A list of tuples with endpoint URLs as strings and their corresponding request initialization parameters as dictionaries. Default is an empty list.
    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    campaign = get_campaign_by_id(sqlite3_connect(DB_PATH), id)[2]
    if campaign is None:
        return {"success": False, "message": f"No campaign found with id: {id}", "har_content": ""}
    if headers is None: headers = {}
    success, message, har_content = await _scout_campaign(campaign, url, force, headers, endpoints)
    return {"success": success, "message": message, "har_content": har_content}

async def triage(campaign: Campaign, url: str) -> tuple[list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []
    headers = {'ngrok-skip-browser-warning': 'true'}
    endpoints = [(url, {"method": "GET", "headers": headers})]

    checklist.append("Scouting the campaign")
    try:
        success, message, _ = await _scout_campaign(campaign, url, True, headers, endpoints)
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.error(f"Error scouting campaign: {str(e)}")
    return checklist, checks