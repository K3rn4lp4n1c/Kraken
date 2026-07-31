from . import navigator
from pathlib import Path
from datetime import datetime
from playwright.async_api import Page, BrowserContext
from urllib.parse import urlparse
from flyingdutchman.carpenter import Campaign, send_request, does_url_match_campaign
from flyingdutchman import playwright, campaigns, HAR_DIRPATH

import re
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
                context = await playwright.create_context_with_callee_as_owner()
                await campaign.resume(context)
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

@navigator.tool()
async def scout_campaign(cid: str, page_url: str, force: bool = False, headers: dict | None = None,
                        endpoints: list[tuple[str, dict]] | None = None,
                        offset: int = 0, limit: int = 150_000) -> dict:
    """
    Capture a HAR snapshot for a loaded campaign at `url`.

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

    Ordinarily, with this tool, browser contexts are paused and resumed to avoid losing state.
    However, issues may arise when the `stop_har()` acknowledgment never arrives,
    which has been observed against at least one campaign regardless of HAR file size,
    where the underlying export appears to complete but the acknowledgment never arrives
    In such cases, the context is forcibly closed to flush the HAR and the campaign is restarted.
    If the campaign is restarted, the previous context is lost but the HAR file persists.
    Consequently, session cookies and other storage states are lost

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
        If the `page_url`'s scheme, root domain, or port does not match the campaign's, the process is aborted.
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

def _safe_har_dir(cid: str) -> Path:
    """
    Build the HAR directory path for a campaign, rejecting any cid that
    could be used to escape HAR_DIRPATH (path separators, '..', etc) or
    that isn't a plain ASCII digit string (matching real campaign ids).
    """
    _CID_RE = re.compile(r"^[0-9]+$")  # campaign ids are always plain ASCII digits
    if not _CID_RE.fullmatch(str(cid)):
        raise ValueError(f"Invalid campaign id: {cid!r}")
    base = HAR_DIRPATH.resolve()
    har_dir = (HAR_DIRPATH / str(cid)).resolve()
    if not har_dir.is_relative_to(base):
        raise ValueError(f"Invalid campaign id: {cid!r}")
    return har_dir


def _safe_har_file_path(cid: str, har_filename: str) -> Path:
    """
    Resolve a HAR filename within a campaign's HAR directory, rejecting
    anything that isn't a bare '.har' filename (no separators, no '..',
    no absolute paths) and verifying the resolved path is actually still
    inside that directory.
    """
    _HAR_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.har$")
    if not _HAR_FILENAME_RE.fullmatch(har_filename):
        raise ValueError(
            f"Invalid HAR filename: {har_filename!r}. "
            "Must be a bare filename ending in '.har' with no path separators."
        )
    har_dir = _safe_har_dir(cid)
    har_file_path = (har_dir / har_filename).resolve()
    if not har_file_path.is_relative_to(har_dir):
        raise ValueError(f"Invalid HAR filename: {har_filename!r}")
    return har_file_path


async def _list_campaign_scouts(cid: str) -> tuple[bool, str, list[str]]:
    """
    List all HAR files for a given campaign.

    Args:
        cid (str): ID of the campaign.

    Returns:
        tuple[bool, str, list[str]]:
        A tuple containing a success status, a message, and the list of
        HAR file names for the campaign.
    """
    logger = logging.getLogger(__name__)
    try:
        har_dir = _safe_har_dir(cid)
        if not har_dir.exists() or not har_dir.is_dir():
            raise FileNotFoundError(f"No HAR directory found for campaign {cid}")
        har_files = [f.name for f in har_dir.iterdir() if f.is_file() and f.suffix == ".har"]
        return True, f"Found {len(har_files)} HAR files for campaign {cid}.", har_files
    except (FileNotFoundError, ValueError) as err:
        return False, str(err), []
    except Exception as e:
        logger.exception("Error while listing HAR files for campaign")
        return False, f"Error while listing HAR files for campaign {cid}: {str(e)}", []


@navigator.tool()
async def list_campaign_scouts(cid: str) -> dict:
    """
    List all HAR files for a given campaign, including any placed there
    manually (outside of `scout_campaign`) with descriptive filenames.

    Args:
        cid (str): ID of the campaign.

    Returns:
        dict: Contains `success`, `message`, and `har_files`.
        `har_files` is a list of HAR file names for the campaign.
    """
    success, message, har_files = await _list_campaign_scouts(cid)
    return {"success": success, "message": message, "har_files": har_files}


async def _read_har_file(cid: str, har_filename: str, offset: int = 0, limit: int = 150_000) -> tuple[bool, str, str, int]:
    """
    Read a HAR file for a given campaign.

    Args:
        cid (str): ID of the campaign.
        har_filename (str): Name of the HAR file to read. Must be a bare
            filename ending in '.har' — no path separators or '..' segments.
        offset (int): Offset for the HAR content to return. Default is 0.
        limit (int): Limit for the HAR content to return. Default is 150000.

    Returns:
        tuple[bool, str, str, int]:
        A tuple containing a success status, a message, the HAR content
        (if successful), and the size of the HAR content on disk.
    """
    logger = logging.getLogger(__name__)
    try:
        har_file_path = _safe_har_file_path(cid, har_filename)
        if not har_file_path.exists() or not har_file_path.is_file():
            raise FileNotFoundError(f"No HAR file named '{har_filename}' found for campaign {cid}")
        har_size = har_file_path.stat().st_size
        har_content = _slice_har_content(har_file_path.read_text(encoding='utf-8'), offset, limit)
        return True, f"Successfully read HAR file '{har_filename}' for campaign {cid}.", har_content, har_size
    except (FileNotFoundError, ValueError) as err:
        return False, str(err), "", 0
    except Exception as e:
        logger.exception("Error while reading HAR file for campaign")
        return False, f"Error while reading HAR file '{har_filename}' for campaign {cid}: {str(e)}", "", 0

@navigator.tool()
async def read_campaign_scout(cid: str, har_filename: str, offset: int = 0, limit: int = 150_000) -> dict:
    """
    Read a HAR file for a given campaign — including HAR files placed
    there manually (outside of `scout_campaign`), such as one recorded
    from a real browser session and given a descriptive filename.

    Offsets and limits behave the same as in `scout_campaign`: values are
    capped at the length/size of the HAR content, applied regardless of
    file size, and slicing means the returned content is likely not valid
    JSON on its own — it may also split multibyte characters at the
    boundary. Reassemble via repeated calls with adjusted `offset` before
    parsing if you need the whole file.

    Args:
        cid (str): ID of the campaign.
        har_filename (str): Name of the HAR file to read. Must be a bare
            filename ending in '.har' — no path separators or '..' segments.
        offset (int): Offset for the HAR content to return. Default is 0.
        limit (int): Limit for the HAR content to return. Default is 150000.

    Returns:
        dict: Contains `success`, `message`, `har_content` and `size_of_har`.
        `size_of_har` is the size of the original HAR content on disk,
        before applying offset and limit.
    """
    success, message, har_content, size_of_har = await _read_har_file(cid, har_filename, offset, limit)
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