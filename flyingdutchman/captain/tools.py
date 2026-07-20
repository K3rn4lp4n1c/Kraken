from . import captain
from flyingdutchman import playwright, DB_PATH, PLAYWRIGHT_AUTH_DIRPATH
from flyingdutchman.powderboy import *
from flyingdutchman.carpenter.extensions import Campaign
from flyingdutchman.navigator.tools import get_campaign_by_id

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
            campaigns = [dict(zip(fields, row)) for row in rows]
            return True, "Campaigns fetched successfully.", campaigns
    except Exception as e:
        return False, f"Error fetching campaigns: {str(e)}", []

@captain.tool()
def get_campaigns() -> dict:
    """
    Campaigns are CTF events that The Flying Dutchman has, can, or will participate in.
    This tool fetches the list of all campaigns from the database.

    Returns:
        dict: This will contain the success status, a message and the campaigns list.
        Campaigns contain the following fields: id, name, datetime, url, status
    """
    success, message, campaigns = _get_campaigns()
    return {"success": success, "message": message, "campaigns": campaigns }

async def _control_campaign_lifecycle(campaign: Campaign, action: str, **options) -> tuple[bool, str]:
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
            await campaign.start(sqlite3_connect(DB_PATH), playwright, **options)
        elif action == 'pause':
            await campaign.pause(sqlite3_connect(DB_PATH), PLAYWRIGHT_AUTH_DIRPATH)
        elif action == 'resume':
            await campaign.resume(sqlite3_connect(DB_PATH), playwright, PLAYWRIGHT_AUTH_DIRPATH, **options)
        elif action == 'stop': await campaign.stop(sqlite3_connect(DB_PATH))
        elif action == 'restart': await campaign.restart(sqlite3_connect(DB_PATH), playwright, **options)
        return True, f"Campaign '{id}' {action}ed successfully."
    except Exception as e:
        logger.exception("Error controlling campaign lifecycle: %s", str(e))
        return False, f"Internal Server Error in controlling campaign lifecycle"

@captain.tool()
async def control_campaign_lifecycle(id: str, action: str, options: dict) -> dict:
    """
    Controls the lifecycle of a campaign. The following actions are supported:
    - 'start': Starts the campaign. Options is passed up to its browser context creation
    - 'pause': Pauses the campaign. No options are needed.
    - 'resume': Resumes the campaign. Options is passed up to its browser context creation
    - 'stop': Stops the campaign. No options are needed.
    - 'restart': Restarts the campaign. Options is passed up to its browser context creation

    Args:
        id (str): The ID of the campaign.
        action (str): The action to perform on the campaign. Can be 'start', 'pause', 'resume', 'stop', or 'restart'.
        options (dict): Additional options to pass to `BrowserContext` creation function
    Returns:
        dict: Contains a success status and a message indicating the result of the operation.
    """
    success, message, campaign = get_campaign_by_id(sqlite3_connect(DB_PATH), id)
    if not success or campaign is None:
        return {"success": False, "message": message, "status": "unknown"}
    success, message = await _control_campaign_lifecycle(campaign, action, **options)
    return {"success": success, "message": message}

async def _authenticate_campaign(campaign: Campaign, url: str, expected_codes: tuple[int, ...],
                                reqInit: dict = {}) -> tuple[bool, str]:
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
        await campaign.authenticate(sqlite3_connect(DB_PATH), url, expected_codes, reqInit)
        return True, f"Campaign '{campaign.id}' authenticated successfully."
    except Exception as e:
        logger.exception("Error authenticating campaign: %s", str(e))
        return False, f"Internal Server Error in authenticating campaign"

@captain.tool()
async def authenticate_campaign(id: str, url: str, expected_codes: tuple[int, ...],
                            reqInit: dict = {}) -> dict:
    """
    Authenticates a running campaign and stores the authentication state in the its browser context.
    Ensure the campaign is running before trying to authenticate it.
    Also ensure that the provided URL matches the campaign's URL.
    Credentials, fetched from a secure database, replace expected placeholders in the request body.
    For example, if the body has "name={{name}}", {{name}} will be replaced with the actual value
    There are no tools to insert campaigns or select credentials so this is safe

    Args:
        id (str): The ID of the campaign.
        url (str): The URL to send the authentication request to.
        expected_codes (tuple[int, ...]): A tuple of expected HTTP status codes for a successful request.
        reqInit (dict): Optional dictionary containing request initialization parameters.

    Returns:
        dict: Contains a success status and a message indicating the result of the operation.
    """
    success, message, campaign = get_campaign_by_id(sqlite3_connect(DB_PATH), id)
    if not success or campaign is None:
        return {"success": False, "message": message}
    success, message = await _authenticate_campaign(campaign, url, expected_codes, reqInit)
    return {"success": success, "message": message}

async def triage(id: str) -> tuple[Campaign | None, list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []
    campaign: Campaign | None = None

    checklist.append("Campaigns database exists")
    checks.append(DB_PATH.exists())

    checklist.append("Campaigns Retrieval was successful")
    try:
        success, message, _ = _get_campaigns()
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error fetching campaigns: %s", str(e))
    
    checklist.append("Campaigns Retrieval by ID was successful")
    try:
        success, message, campaign = get_campaign_by_id(sqlite3_connect(DB_PATH), id)
        if not success or campaign is None: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error fetching campaign by id: %s", str(e))

    checklist.append("Campaigns Lifecycle Control was successful")
    try:
        if campaign is None: raise Exception("Campaign is None, cannot control lifecycle")
        await _control_campaign_lifecycle(campaign, "start")
        if campaign.status != "running":
            raise Exception(f"Expected status 'running', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "pause")
        if campaign.status != "paused":
            raise Exception(f"Expected status 'paused', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "resume")
        if campaign.status != "running":
            raise Exception(f"Expected status 'running', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "stop")
        if campaign.status != "stopped":
            raise Exception(f"Expected status 'stopped', got '{campaign.status}'")
        await _control_campaign_lifecycle(campaign, "restart", extra_http_headers={
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
        context = await campaign.pause(sqlite3_connect(DB_PATH), PLAYWRIGHT_AUTH_DIRPATH)
        login_page = await context.new_page()
        login_url = campaign.url + "/login"
        await login_page.goto(login_url, wait_until="domcontentloaded", timeout=60_000)
        await login_page.wait_for_url("**/ctf/login*")
        nonce = login_page.locator("#nonce")

        # print("Page URL:", login_page.url)
        # print("Page closed:", login_page.is_closed())
        # print("Matching nonce elements:", await nonce.count())
        # print("All context pages:", [page.url for page in login_page.context.pages])
        # await login_page.screenshot(path=f"login_page_{id}.png", full_page=True)
        nonce_value = await nonce.input_value()
        reqInit = {
            "method": "POST",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "ngrok-skip-browser-warning": "1",
            },
            "body": "name={{name}}&password={{password}}&_submit=Submit&nonce={nonce_value}".format(
                nonce_value=nonce_value
            )
        }
        await campaign.resume(sqlite3_connect(DB_PATH), playwright, paused_context=context)
        success, message = await _authenticate_campaign(campaign, login_url, (200,302), reqInit)
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error authenticating campaign: %s", str(e))
    return campaign, checklist, checks