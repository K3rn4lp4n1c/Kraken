from . import navigator
from pathlib import Path
from datetime import datetime
from playwright.async_api import Page, BrowserContext
from urllib.parse import urlparse, urlsplit
from flyingdutchman.carpenter import Campaign, send_request
from flyingdutchman import campaigns, HAR_DIRPATH

import logging
import hashlib

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
        headers (Optional(dict)): Optional dictionary containing request headers that will be set on the page request. Default is None.
        endpoints (Optional(list[tuple[str, dict]])): A list of tuples with endpoint URLs and their corresponding request initialization parameters. Default is an empty list.

    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    logger = logging.getLogger(__name__)
    context: BrowserContext | None = None
    recording_har = False
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
        context = await campaign.pause()
        logger.debug(f"Cookies after authentication: {await context.cookies()}")
        page: Page | None = None
        await context.tracing.start_har(har_file_path, mode="full", content="embed")
        recording_har = True
        for p in context.pages:
            if p.url == url:
                logger.debug(f"Found existing page with URL: {url}. Using this page for scouting.")
                if page is not None:
                    raise ValueError(f"Multiple pages found with the same URL: {url}. Perhaps restart the campaign.")
                page = p
        if page is None:
            logger.debug(f"No existing page found with URL: {url}. Creating a new page.")
            page = await context.new_page()
            
            if headers is None: headers = {}
            await page.set_extra_http_headers(headers)
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.screenshot(path=f"scout_campaign_{campaign.id}.png")
            
        await page.wait_for_timeout(5_000)
        
        if endpoints is None: endpoints = []
        for endpoint in endpoints:
            if urlparse(endpoint[0]).netloc != parsed_url.netloc:
                logger.warning(f"'{endpoint[0]}' does not match expected domain for campaign '{campaign.id}'. Skipping...")
                continue
            logger.debug(f"Cookies after authentication: {await page.context.cookies()}")
            await send_request(page, url, endpoint)
            await page.wait_for_timeout(1_000)
        await context.tracing.stop_har()
        await campaign.resume(context)
        context = None
        recording_har = False
        if not har_file_path.exists():
            return False, f"Failed to record HAR file for campaign '{campaign.id}'.", ""
        har_content = har_file_path.read_text(encoding='utf-8')
        return True, f"Campaign '{campaign.id}' scouted successfully.", har_content
    except ValueError as ve:
        logger.error("Error while scouting campaign: %s", str(ve))
        return False, f"Error: {str(ve)}", ""
    except Exception as e:
        logger.exception("Error while scouting campaign: %s", str(e))
        return False, f"Internal Server Error in fetching campaigns", ""
    finally:
        if context is not None:
            if recording_har:
                try:
                    await context.tracing.stop_har()
                except Exception:
                    logger.exception("Failed to stop HAR recording")

            try:
                await campaign.resume(context)
            except Exception:
                logger.exception("Failed to resume campaign")

@navigator.tool()
async def scout_campaign(cid: str, url: str, force: bool = False, headers: dict | None = None,
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
        cid (str): The ID of the campaign.
        url (str): The URL to visit for recording the HAR file.
        force (bool): If True, overwrite the existing HAR file if it exists. Default is False.
        headers (Optional(dict)): Optional dictionary containing request headers that will be set on the page request. Default is None.
        endpoints (Optional(list[tuple[str, dict]])): A list of tuples with endpoint URLs as strings and their corresponding request initialization parameters as dictionaries. Default is an empty list.
    Returns:
        tuple[bool, str, str]:
        A tuple containing a success status, a message, and the HAR content (if successful).
    """
    campaign = campaigns.get_campaign(cid)
    if campaign is None:
        return {"success": False, "message": f"No campaign found with id: {cid}", "har_content": ""}
    if headers is None: headers = {}
    success, message, har_content = await _scout_campaign(campaign, url, force, headers, endpoints)
    return {"success": success, "message": message, "har_content": har_content}

async def triage(campaign: Campaign, url: str, endpoint: tuple[str, dict]) -> tuple[str, list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []
    har: str = ""

    checklist.append("Scouting the campaign")
    try:
        success, message, har = await _scout_campaign(campaign, url, True, endpoints=[endpoint])
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.error(f"Error scouting campaign: {str(e)}")
    return har, checklist, checks