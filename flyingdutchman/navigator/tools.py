from . import navigator
from pathlib import Path
from datetime import datetime
from playwright.async_api import Page, BrowserContext
from urllib.parse import urlparse
from flyingdutchman.carpenter import Campaign, send_request
from flyingdutchman import campaigns, HAR_DIRPATH

import logging
import hashlib

def _slice_har_content(har_content: str, offset: int, limit: int) -> str:
    """
    Slices the HAR content based on the provided offset and limit.

    Args:
        har_content (str): The original HAR content.
        offset (int): The starting index from which to slice the content.
        limit (int): The maximum number of characters to include in the sliced content.

    Returns:
        str: The sliced HAR content.
    """
    offset = max(0, min(offset, len(har_content)))
    limit = max(0, min(limit, len(har_content) - offset))
    return har_content.encode('utf-8')[offset:offset + limit].decode('utf-8', errors='ignore')

async def _scout_campaign(campaign: Campaign, url: str, force: bool, headers: dict | None = None,
                        endpoints: list[tuple[str, dict]] | None = None,
                        offset: int = 0, limit: int = 150_000) -> tuple[bool, str, str, int]:
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
        headers (dict | None): Optional HTTP headers to set on the page. Default is None.
        endpoints (list[tuple[str, dict]] | None): Optional list of endpoints to send fetch requests to after visiting the URL. Each endpoint is a tuple of (url, request_init).
        offset (int): Offset for the HAR content to return. Default is 0.
        limit (int): Limit for the HAR content to return. Default is 150000.

    Returns:
        tuple[bool, str, str, int]:
        A tuple containing a success status, a message, the HAR content (if successful), and the size of the HAR content.
    """
    logger = logging.getLogger(__name__)
    context: BrowserContext | None = None
    recording_har = False
    try:
        parsed_url = urlparse(url)
        alike = (
            parsed_url.scheme == urlparse(campaign.url).scheme and
            parsed_url.netloc == urlparse(campaign.url).netloc and
            parsed_url.port == urlparse(campaign.url).port
        )
        if not alike:
            return False, f"'{url}' does not match expected domain for campaign {campaign.id}", "", 0
        har_dir = HAR_DIRPATH / str(campaign.id)
        har_path = hashlib.md5(parsed_url.geturl().encode()).hexdigest() + ".har"
        Path.mkdir(har_dir, parents=True, exist_ok=True)
        har_file_path = har_dir / har_path
        if har_file_path.exists() and not force:
            m_timestamp = har_file_path.stat().st_mtime
            m_time = datetime.fromtimestamp(m_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            har_size = har_file_path.stat().st_size
            har_content = _slice_har_content(har_file_path.read_text(encoding='utf-8'), offset, limit)
            return True, f"Campaign {campaign.id} already scouted at {m_time}.", har_content, har_size
        har_file_path.unlink(missing_ok=True)
        context = await campaign.pause()
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
            await page.wait_for_timeout(5_000)
        
        if endpoints is None: endpoints = []
        for endpoint in endpoints:
            alike = (
                urlparse(endpoint[0]).scheme == parsed_url.scheme and
                urlparse(endpoint[0]).netloc == parsed_url.netloc and
                urlparse(endpoint[0]).port == parsed_url.port
            )
            if not alike:
                logger.warning(f"'{endpoint[0]}' does not match expected domain for campaign '{campaign.id}'. Skipping...")
                continue
            await send_request(page, url, endpoint)
            await page.wait_for_timeout(1_000)
        await context.tracing.stop_har()
        await campaign.resume(context)
        context = None
        recording_har = False
        if not har_file_path.exists():
            return False, f"Failed to record HAR file for campaign '{campaign.id}'.", "", 0
        har_size = har_file_path.stat().st_size
        har_content = _slice_har_content(har_file_path.read_text(encoding='utf-8'), offset, limit)
        return True, f"Campaign '{campaign.id}' scouted successfully.", har_content, har_size
    except ValueError as ve:
        logger.error("Error while scouting campaign: %s", str(ve))
        return False, f"Error: {str(ve)}", "", 0
    except Exception:
        logger.exception("Error while scouting campaign")
        return False, f"Internal Server Error in fetching campaigns", "", 0
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
async def scout_campaign(cid: str, page_url: str, force: bool = False, headers: dict | None = None,
                        endpoints: list[tuple[str, dict]] | None = None,
                        offset: int = 0, limit: int = 150_000) -> dict:
    """
    Capture a HAR snapshot for a loaded campaign at `url` without closing the campaign's context.

    If `force` is `False` and a HAR already exists for the URL hash, the existing HAR content
    is returned instead of recording again. The capture time is also returned in the message.

    HAR recording is done in "full" mode, which captures all headers, bodies, and cookies.
    HAR contents are in "embed" state, which puts all bodies inline in the HAR file.
    The file is saved in the campaign's HAR directory with a name based on the MD5 hash of the URL.

    If a page with the same URL already exists in the campaign's context, it is reused and
    the resulting HAR will not contain navigational requests to the URL. Or else, a new page is made.
    An already existing page may not have the headers and cookies that might need to be set.
    Conversely, a new page may not have the cookies that an existing page has.
    Restart the campaign if you need a new page or add dummy query parameters to the URL.

    Offsets and limits are often for clients with constraints on the max output size from servers.
    While constraints may not apply to LLMs themselves, calls to servers are heavily abstracted.
    In short, use them to avoid sending too much data to the server at once
    Their values are capped at the length and size of the HAR content respectively.
    They are applied regardless of whether the HAR content is newly recorded or already exists.
    This will mean that sliced HAR content is likely not valid JSON.
    Slicing may also split at multibyte characters.

    Args:
        cid (str): ID of a campaign that has already been loaded.
        page_url (str): Page URL to open/record.
        force (bool = False): Re-record even when a HAR file already exists.
        headers (dict | None = None): Extra HTTP headers set on a newly created page.
        endpoints (list[tuple[str, dict]] | None = None): Fetch requests in (url (str), request_init (dict | None)) format.
        offset (int = 0): Offset for the HAR content to return. Default is 0.
        limit (int = 150000): Limit for the HAR content to return. Default is 150000.

    Returns:
        dict: Contains `success`, `message`, `har_content` and `har_size`.
        `har_size` is the size of the original HAR content before applying offset and limit.
    
    Raises:
        If the campaign is not found, try to load it first. Refer to `load_campaign_from_db`.
        If the page's scheme, domain, or port does not match the campaign's, the process is aborted.
        If at least two pages have the same URL, the process is aborted. This is unlikely.
    """
    campaign = campaigns.get_campaign(cid)
    if campaign is None:
        return {"success": False, "message": f"No campaign found with id: {cid}", "har_content": ""}
    if headers is None: headers = {}
    success, message, har_content, size_of_har = await _scout_campaign(
        campaign, page_url, force, headers, endpoints, offset, limit
    )
    return {"success": success, "message": message, "har_content": har_content, "size_of_har": size_of_har}

async def triage(campaign: Campaign, url: str, endt: tuple[str, dict]) -> tuple[str, list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []
    har: str = ""

    checklist.append("Scouting the campaign")
    try:
        success, message, har, _ = await _scout_campaign(campaign, url, True, endpoints=[endt])
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.error(f"Error scouting campaign: {str(e)}")
    return har, checklist, checks