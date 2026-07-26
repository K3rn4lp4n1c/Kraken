from . import captain
from flyingdutchman import (
    playwright, campaigns, DB_PATH, HAR_DIRPATH, PLAYWRIGHT_AUTH_DIRPATH, PlaywrightManager as PM
)
from flyingdutchman.carpenter import Campaign, env, sqlite3_connect

import logging

def _get_campaigns() -> tuple[bool, str, list[dict]]:
    """
    Campaigns are CTF events that The Flying Dutchman has, can, or will participate in.
    This function fetches the list of all campaigns from the database.

    Returns:
        tuple[bool, str, list[dict]]:
        A tuple containing a successful status, a message, and a list of dictionaries
        Each dictionary represents an campaign with its details. 
    """
    try:
        table_name = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(DB_PATH) as conn:
            cursor = conn.cursor()
            fields = ["id", "name", "datetime", "url", "status"]
            cursor.execute("SELECT {} FROM {}".format(', '.join(fields), table_name))
            rows = cursor.fetchall()
            db_campaigns = [dict(zip(fields, row)) for row in rows]
            db_campaigns = [
                {**c, "loaded": campaigns.get_campaign(c['id']) is not None}
                for c in db_campaigns
            ]
            return True, "Campaigns fetched successfully.", db_campaigns
    except Exception as e:
        return False, f"Error fetching campaigns: {str(e)}", []

@captain.tool()
def get_campaigns() -> dict:
    """
    Fetch all campaigns from the database and annotate whether each one is
    currently loaded in the in-memory campaign registry.

    Returns:
        dict: Contains `success`, `message`, and `campaigns`.
        Each campaign item includes `id`, `name`, `datetime`, `url`, `status`,
        and `loaded`.
    """
    success, message, campaigns = _get_campaigns()
    return {"success": success, "message": message, "campaigns": campaigns }

def _load_campaigns_from_db(campaign_ids: list[str]) -> tuple[bool, str]:
    """
    Loads campaigns into the CampaignManager based on their IDs.

    Args:
        id (list[str]): A list of campaign IDs to load.
    """
    logger = logging.getLogger(__name__)
    try:
        with sqlite3_connect(DB_PATH) as conn:
            cursor = conn.cursor()
            table_name = env("CAMPAIGNS_TABLE")[0]
            fields = ["id", "name", "datetime", "url", "status"]
            cursor.execute("SELECT {} FROM {} WHERE id IN {}".format(
                ', '.join(fields), table_name, "(" + ",".join("?" for _ in campaign_ids) + ")"
            ), campaign_ids)
            rows = cursor.fetchall()
            for row in rows:
                campaign_data = dict(zip(fields, row))
                campaign = Campaign(**campaign_data, paths={
                    "db": DB_PATH, "har": HAR_DIRPATH, "playwright_auth": PLAYWRIGHT_AUTH_DIRPATH
                })
                campaigns.add_campaign(campaign)
        return True, f"Campaigns {', '.join(campaign_ids)} loaded successfully."
    except Exception as e:
        logger.exception("Error loading campaigns from database: %s", str(e))
        return False, f"Error loading campaigns from database: {str(e)}"

@captain.tool()
def load_campaigns_from_db(campaign_ids: list[str]) -> dict:
    """
    Load campaigns from the database into the in-memory campaign registry.
    This is required before tools that operate on a loaded campaign instance.

    Args:
        campaign_ids (list[str]): Campaign IDs to load.

    Returns:
        dict: Contains `success` and `message`.
    """
    success, message = _load_campaigns_from_db(campaign_ids)
    return {"success": success, "message": message}

async def _control_campaign_lifecycle(campaign: Campaign, action: str, p: PM | None = None,
                                    ctxts: list | None = None, **options) -> tuple[bool, str]:
    """
    Controls the lifecycle of a campaign. The following actions are supported:
    - 'start': Starts the campaign. Options is passed up to its browser context creation
    - 'pause': Pauses the campaign. No options are needed.
    - 'resume': Resumes the campaign. Options is passed up to its browser context creation
    - 'stop': Stops the campaign. No options are needed.
    - 'restart': Restarts the campaign. Options is passed up to its browser context creation

    Args:
        id (str): The ID of the campaign.
        action (str): The action to perform on the campaign. Can be 'start', 'stop', or 'restart'.
        options (dict): Additional options to pass to `BrowserContext` creation function

    Returns:
        tuple[bool, str]:
        A tuple containing a success status and a message indicating the result of the operation.
    """
    logger = logging.getLogger(__name__)
    try:
        if action == 'start':
            if p is None: raise ValueError("PlaywrightManager instance must be provided for 'start'")
            await campaign.start(p, **options)
        elif action == 'pause':
            ctx = await campaign.pause()
            if ctxts is not None: ctxts.append(ctx)
        elif action == 'resume':
            ctx = ctxts[0] if ctxts and len(ctxts) > 0 else None
            await campaign.resume(ctx)
        elif action == 'stop': await campaign.stop()
        elif action == 'restart':
            if p is None: raise ValueError("PlaywrightManager instance must be provided for 'restart'")
            await campaign.restart(p, **options)
        else: raise ValueError(f"Unsupported action: {action}")
        return True, f"{action} on Campaign '{campaign.id}' was successfully."
    except Exception as e:
        logger.exception("Error controlling campaign lifecycle: %s", str(e))
        return False, f"Internal Server Error in controlling campaign lifecycle"

@captain.tool()
async def control_campaign_lifecycle(cid: str, action: str, options: dict | None = None) -> dict:
    """
    Control the lifecycle of a loaded campaign.

    Supported actions:
    - `start`: create a browser context and mark campaign as running.
    - `pause`: detach the active context from the campaign and mark it paused.
    - `resume`: reattach a paused context and mark it running.
    - `stop`: close the active context and mark it stopped.
    - `restart`: replace the active context with a new one and mark it running.

    `options` are forwarded to browser-context creation for `start` and
    `restart`.

    Args:
        cid (str): ID of a campaign that has already been loaded.
        action (str): One of `start`, `pause`, `resume`, `stop`, or `restart`.
        options (dict | None): Optional browser-context options.

    Returns:
        dict: Contains `success` and `message`.
        If `cid` is not loaded, returns `{"success": False, "status": "unknown", ...}`.
    """
    campaign = campaigns.get_campaign(cid)
    if campaign is None:
        return {"success": False, "message": f"Campaign {cid} not found", "status": "unknown"}
    success, message = await _control_campaign_lifecycle(campaign, action, playwright, **(options or {}))
    return {"success": success, "message": message}

async def _authenticate_campaign(campaign: Campaign, page_url: str, endpoint: tuple[str, dict | None],
                                expected_codes: tuple[int, ...],) -> tuple[bool, str]:
    """
    Authenticates a campaign with a given browser context.

    Args:
        campaign (Campaign): The campaign to authenticate.
        url (str): The URL to send the authentication request to.
        reqInit (dict): Optional dictionary containing request initialization parameters.

    Returns:
        tuple[bool, str]:
        A tuple containing a success status and a message indicating the result of the operation.
    """
    logger = logging.getLogger(__name__)
    try:
        await campaign.authenticate(page_url, endpoint, expected_codes)
        return True, f"Campaign '{campaign.id}' authenticated successfully."
    except ValueError as ve:
        logger.error("Error authenticating campaign: %s", str(ve))
        return False, f"Error: {str(ve)}"
    except Exception as e:
        logger.exception("Error authenticating campaign: %s", str(e))
        return False, f"Internal Server Error in authenticating campaign"

@captain.tool()
async def authenticate_campaign(cid: str, page_url: str, endpoint: tuple[str, dict | None],
                                expected_codes: tuple[int, ...]) -> dict:
    """
    Authenticate a loaded, running campaign by sending a request from a page
    inside the campaign context.

    The tool reuses an existing page matching `page_url` or creates one when
    none exists. The campaign must already be running.

    The request body schema is:
    ```
    {
        "body": {
            "encoding": "form" | "json" | "query" | "text",
            "fields": {
                "name": {"$flyingdutchman": {"kind": "credentials", "name": "name"}},
                "password": {"$flyingdutchman": {"kind": "credentials", "name": "password"}},
                "nonce": "literal_value"
            }
        }
    }
    ```

    Fields marked with `$flyingdutchman` are interpolated from stored campaign
    credentials. Endpoint URL must match the campaign origin used by `page_url`.

    Args:
        - cid (str): ID of a campaign that has already been loaded.
        - page_url (str): Page URL used to perform authentication.
        - endpoint (tuple[str, dict | None]): `(url, request_init)` for the request.
        - expected_codes (tuple[int, ...]): HTTP status codes considered successful.

    Returns:
        dict: Contains `success` and `message`.
        If `cid` is not loaded, returns `{"success": False, "status": "unknown", ...}`.
    """
    campaign = campaigns.get_campaign(cid)
    if campaign is None:
        return {"success": False, "message": f"Campaign {cid} not found", "status": "unknown"}
    success, message = await _authenticate_campaign(campaign, page_url, endpoint, expected_codes)
    return {"success": success, "message": message}

async def triage(cid: str) -> tuple[Campaign | None, list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []
    campaign: Campaign | None = None

    checklist.append("Campaigns Retrieval was successful")
    try:
        success, message, _ = _get_campaigns()
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error fetching campaigns: %s", str(e))

    checklist.append("Campaigns Loading from DB was successful")
    try:
        success, message = _load_campaigns_from_db([cid])
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error loading campaigns from DB: %s", str(e))
    
    checklist.append("Campaign Retrieval by ID was successful")
    try:
        campaign = campaigns.get_campaign(cid)
        if campaign is None:
            raise Exception(f"No campaign found with id: {cid}. {campaigns._campaigns.keys()}")
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error fetching campaign by id: %s", str(e))

    checklist.append("Campaigns Lifecycle Control was successful")
    try:
        ctxts = []
        if campaign is None: raise Exception("Campaign is None, cannot control lifecycle")
        await _control_campaign_lifecycle(campaign, "start", playwright)
        if campaign.status != "running":
            raise Exception(f"Expected status 'running', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "pause", ctxts=ctxts)
        if campaign.status != "paused":
            raise Exception(f"Expected status 'paused', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "resume", ctxts=ctxts)
        if campaign.status != "running":
            raise Exception(f"Expected status 'running', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "stop")
        if campaign.status != "stopped":
            raise Exception(f"Expected status 'stopped', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign,  "restart", playwright, extra_http_headers={
            "ngrok-skip-browser-warning": "1"
        })
        if campaign.status != "running":
            raise Exception(f"Expected status 'running', got '{campaign.status}'")
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error controlling campaign lifecycle: %s", str(e))

    checklist.append("Campaign Authentication was successful")
    try:
        if campaign is None: raise Exception("Campaign is None, cannot authenticate")
        if campaign.status != "running": raise Exception(f"Campaign status is not 'running', got '{campaign.status}'")
        context = await campaign.pause()
        login_page = await context.new_page()
        login_url = campaign.url + "/login"
        await login_page.goto(login_url, wait_until="domcontentloaded", timeout=60_000)
        await login_page.wait_for_url("**/ctf/login*")
        nonce = login_page.locator("#nonce")

        # print("Page URL:", login_page.url)
        # print("Page closed:", login_page.is_closed())
        # print("Matching nonce elements:", await nonce.count())
        # print("All context pages:", [page.url for page in context.pages])
        # await login_page.screenshot(path=f"login_page_{cid}.png", full_page=True)
        nonce_value = await nonce.input_value()
        reqInit = {
            "method": "POST",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "ngrok-skip-browser-warning": "1",
            },
            "body": {
                "encoding": "form",
                "fields": {
                    "name": {"$flyingdutchman": {"kind": "credentials", "name": "name"}},
                    "password": {"$flyingdutchman": {"kind": "credentials", "name": "password"}},
                    "nonce": nonce_value,
                    "_submit": "Submit",
                }
            }
        }
        await campaign.resume(context)
        success, message = await _authenticate_campaign(campaign, login_url, (login_url, reqInit), (200,302,))
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error authenticating campaign: %s", str(e))
    return campaign, checklist, checks