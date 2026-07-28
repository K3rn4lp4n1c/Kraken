from . import navigator
from pathlib import Path
from datetime import datetime
from playwright.async_api import Page, BrowserContext
from urllib.parse import urlparse
from flyingdutchman.carpenter import Campaign, send_request, does_url_match_campaign
from flyingdutchman import playwright, campaigns, HAR_DIRPATH

import asyncio
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
    Ensure the provided URL matches the expected root domain for the campaign.
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
    har_file_path: Path | None = None
    recovered_via_close = False
    paused = False
    try:
        parsed_url = urlparse(url)
        if not does_url_match_campaign(url, campaign.url):
            return False, f"'{url}' does not match expected root domain for campaign {campaign.id}", "", 0
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
        paused = True
        page: Page | None = None
        await context.tracing.start_har(har_file_path, mode="full", content="embed")
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
            if not does_url_match_campaign(endpoint[0], campaign.url):
                logger.warning(f"'{endpoint[0]}' does not match expected root domain for campaign '{campaign.id}'. Skipping...")
                continue
            await send_request(page, url, endpoint)
            await page.wait_for_timeout(1_000)
        try:
            await asyncio.wait_for(context.tracing.stop_har(), timeout=30)
            await campaign.resume(context)
        except asyncio.TimeoutError:
            logger.warning("stop_har() ack never arrived; forcing close to flush")
            try:
                await asyncio.wait_for(context.close(), timeout=30)
            except Exception:
                logger.warning("close() also failed/timed out; proceeding to restart anyway")
            await campaign.restart(playwright)
            recovered_via_close = True
        context = None
        if not har_file_path.exists() or har_file_path.stat().st_size == 0:
            return False, f"Failed to record HAR file for campaign '{campaign.id}'.", "", 0
        har_size = har_file_path.stat().st_size
        har_content = _slice_har_content(har_file_path.read_text(encoding='utf-8'), offset, limit)
        return True, (
            f"Campaign {campaign.id} scouted successfully "
            f"{'with' if recovered_via_close else 'without'} timeout"
        ), har_content, har_size
    except (asyncio.CancelledError, asyncio.TimeoutError):
        await campaign.restart(playwright)
        if har_file_path is None or not har_file_path.exists() or har_file_path.stat().st_size == 0:
            return False, f"After Timeout, failed to record HAR for campaign {campaign.id}", "", 0
        har_size = har_file_path.stat().st_size
        har_content = _slice_har_content(har_file_path.read_text(encoding='utf-8'), offset, limit)
        logger.error("Timeout while scouting campaign. Campaign was restarted.")
        return True, "Timeout while scouting. Campaign was restarted.", har_content, har_size
    except ValueError as ve:
        logger.error("Error while scouting campaign: %s", str(ve))
        if paused and campaign._browser_context is None:
            try:
                new_context = await playwright.create_context_with_callee_as_owner()
                await campaign.resume(new_context)
            except Exception:
                logger.exception("Failed to recover campaign context after ValueError")
        return False, f"Error: {str(ve)}", "", 0
    except Exception as e:
        logger.exception("Error while scouting campaign")
        if paused and campaign._browser_context is None:
            try:
                new_context = await playwright.create_context_with_callee_as_owner()
                await campaign.resume(new_context)
            except Exception:
                logger.exception("Failed to recover campaign context after unexpected error")
        return False, f"Internal Server Error in fetching campaigns: {str(e)}", "", 0

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