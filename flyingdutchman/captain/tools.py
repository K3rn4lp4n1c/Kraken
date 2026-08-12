from . import captain
from flyingdutchman import (
    playwright, campaigns, DB_PATH, HAR_DIRPATH, PLAYWRIGHT_AUTH_DIRPATH, PlaywrightManager as PM
)
from flyingdutchman.carpenter import Campaign, Plugin, PLUGINS, env, sqlite3_connect

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
                {**c, "loaded": campaigns.get_campaign(c["id"]) is not None}
                for c in db_campaigns
            ]
            return True, "Campaigns fetched successfully.", db_campaigns
    except Exception as e:
        return False, f"Error fetching campaigns: {str(e)}", []

@captain.tool()
def get_campaigns() -> dict:
    """
    Fetch all campaigns from the database and annotate whether each one is currently loaded
    in the in-memory campaign registry.

    Returns:
        dict: Contains `success`, `message`, and `campaigns`.
        Each campaign item includes `id`, `name`, `datetime`, `url`, `status`, and `loaded`.

    Raises:
        If you get an empty list of campaigns, the error message should indicate what happened.
    """
    success, message, campaigns = _get_campaigns()
    return {"success": success, "message": message, "campaigns": campaigns }

def _load_campaigns_from_db(campaign_ids: list[str], plugin_names: list[str] | None = None
                        ) -> tuple[bool, str]:
    """
    Loads campaigns into the CampaignManager based on their IDs with optional plugin association.
    This is required before actions on campaigns can be performed.

    Args:
        campaign_ids (list[str]): List of campaign IDs to load.
    """
    logger = logging.getLogger(__name__)
    plugins: list[Plugin] = []
    try:
        for plugin_name in plugin_names or []:
            plugin = PLUGINS.get(plugin_name)
            if plugin is None: raise ValueError(f"Plugin '{plugin_name}' not found in PLUGINS")
            plugins.append(plugin)

        with sqlite3_connect(DB_PATH) as conn:
            cursor = conn.cursor()
            table_name = env("CAMPAIGNS_TABLE")[0]
            fields = ["id", "name", "datetime", "url", "status", "challenge"]
            cursor.execute("SELECT {} FROM {} WHERE id IN {}".format(
                ', '.join(fields), table_name, "(" + ",".join("?" for _ in campaign_ids) + ")"
            ), campaign_ids)
            rows = cursor.fetchall()
            for row in rows:
                campaign_data = dict(zip(fields, row))
                campaign = Campaign(**campaign_data, paths={
                    "db": DB_PATH, "har": HAR_DIRPATH, "playwright_auth": PLAYWRIGHT_AUTH_DIRPATH,
                }, plugins=tuple(plugins))
                campaigns.add_campaign(campaign)
        return True, f"Campaigns {', '.join(campaign_ids)} loaded successfully."
    except Exception as e:
        logger.exception("Error loading campaigns from database")
        return False, f"Error loading campaigns from database: {str(e)}"

@captain.tool()
def load_campaigns_from_db(campaign_ids: list[str], plugin_names: list[str] | None = None) -> dict:
    """
    Load campaigns from the database into the in-memory campaign registry.
    This is required before actions on campaigns can be performed.
    There are no available tools to remove campaigns from the campaign registry.
    Loading a campaign ID that's already loaded fails without replacement or reloading.
    Therefore, the only way to reload a campaign is to restart the Flying Dutchman server.

    Plugin names are optional. They are used to extend the functionality of the loaded campaigns
    without modifying the core Flying Dutchman codebase.
    If provided, the plugins will be associated with the loaded campaigns.
    To see the available plugins, use the `get_plugins` tool.

    Args:
        campaign_ids (list[str]): Campaign IDs to load. IDs are strings here not integers.
        plugin_name (str): Optional plugin name to associate with the loaded campaigns.

    Returns:
        dict: Contains `success` and `message`.
    
    Raises:
        If a campaign ID is not found in the database, the error message will indicate that.
        If a plugin name is not found in the available plugins, the error message will indicate that.
        If a campaign ID is already loaded, the error message will indicate that.
    """
    success, message = _load_campaigns_from_db(campaign_ids, plugin_names)
    return {"success": success, "message": message}

async def _control_campaign_lifecycle(campaign: Campaign, action: str, p: PM | None = None,
                                    headless: bool = True, **options) -> tuple[bool, str]:
    """
    Controls the lifecycle of a campaign. The following actions are supported:
    - 'start': Starts the campaign. Options is passed up to its browser context creation
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
            await campaign.start(p, headless, **options)
        elif action == 'stop': await campaign.stop()
        elif action == 'restart':
            if p is None: raise ValueError("PlaywrightManager instance must be provided for 'restart'")
            await campaign.restart(p, headless, **options)
        else: raise ValueError(f"Unsupported action: {action}")
        return True, f"{action} on Campaign '{campaign.id}' was successfully."
    except Exception as e:
        logger.exception("Error controlling campaign lifecycle")
        return False, f"Internal Server Error in controlling campaign lifecycle: {str(e)}"

@captain.tool()
async def control_campaign_lifecycle(cid: str, action: str, headless: bool = True,
                                    options: dict | None = None) -> dict:
    """
    Control the lifecycle of a loaded campaign.

    Supported actions:
    - `start`: create a browser context and mark campaign as running.
    - `stop`: close the active context and mark it stopped.
    - `restart`: replace the active context with a new one and mark it running.
    The `headless` parameter controls whether the browser context is headless or not.
    `options` are forwarded to browser-context creation for `start` and `restart`.

    Unsupported actions:
    - `pause`: detach the active context from the campaign and mark it paused.
    - `resume`: reattach a paused context and mark it running.
    
    `pause` and `resume` are unsupported. This is because if they had been implemented:
    - They require an unserializable context to be passed in from the tool call. Impossible.
    - `pause` would need to hold some operational campaign lock what only `resume` can release.
    The lock is unbuilt and probably unnecessary but that's the designer's problem

    Args:
        cid (str): ID of a campaign that has already been loaded.
        action (str): One of `start`, `stop`, or `restart`.
        headless (bool = True): Whether the browser and its context should be headless or not.
        options (dict | None = None): Optional browser-context options.

    Returns:
        dict: Contains `success` and `message`.
    
    Raises:
        If the campaign is not loaded, try to load it first. Refer to `load_campaigns_from_db`.
        If the `PlaywrightManager` instance is not up, check The Flying Dutchman for server errors.
        If the `action` is unsupported, the error message will indicate that.
        If no valid action can change the status, try again or request for a server restart.
        If the is no headed browser is unavailable, try again or request for a server restart.
    """
    campaign = campaigns.get_campaign(cid)
    if campaign is None:
        return {"success": False, "message": f"Campaign {cid} not found", "status": "unknown"}
    success, message = await _control_campaign_lifecycle(campaign, action, playwright, headless,
                                                        **(options or {}))
    return {"success": success, "message": message}

async def _authenticate_campaign(campaign: Campaign, page_url: str, endpoint: tuple[str, dict | None],
                                expected_codes: tuple[int, ...],) -> tuple[bool, str]:
    """
    Authenticates a campaign with a given browser context.

    Args:
        campaign (Campaign): The campaign to authenticate.
        page_url (str): The URL of the page to navigate to for authentication.
        endpoint (tuple[str, dict | None]): A tuple containing the URL
            and request initialization parameters for the request to be sent from the page's context.
        expected_codes (tuple[int, ...]): A tuple of HTTP status codes that are considered successful.

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
    Authenticate a loaded, running campaign by sending a request from a page its context.
    The page will navigate to `page_url` and use `page.evaluate()` to send a request to `endpoint[0]`
    The call to `page.evaluate()`, calls `fetch()` with the request initialization parameters.
    This tool will not work as expected unless you know exactly how the request must look like.
    If it fails, refer to `scout_campaign` to probe a campaign and determine how to authenticate it.

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
    After interpolation, if the encoding was 'form', the request body becomes:
    ```
    {
        "body": name=interpolated_name&password=interpolated_password&nonce=literal_value
    }
    ```

    Fields marked with `$flyingdutchman` are interpolated from stored campaign credentials.
    Ensure that `$flyingdutchman` is only present in `body.fields`.
    Otherwise, the request body is sent as-is.

    If a page with the same URL already exists in the campaign's context, it is reused.
    Or else, a new page is made.
    An already existing page may not have the headers and cookies that might need to be set.
    Conversely, a new page may not have the cookies that an existing page has.
    Restart the campaign if you need a new page or add dummy query parameters to the URL.

    The encoding is not inferred from the request header in `endpoint[1]` and defaults to 'json'.
    It will also not be used to build the final request header. Those must be set explicitly.
    The headers are scoped only to the fetch call made from the page and will not be set on the page.

    If the process was succssful but the status code is not expected, the tool will report a failure.
    Refer to `scout_campaign` for probing a campaign.

    It might also help to load the campaign with a plugin
    especially for campaigns whose authentication flow is not consistent with The Flying Dutchman.

    Args:
        cid (str): ID of a campaign that has already been loaded.
        page_url (str): Page URL used to perform authentication.
        endpoint (tuple[str, dict | None]): (url (str), request_init (dict | None)) for the request.
        expected_codes (tuple[int, ...]): HTTP status codes considered successful.

    Returns:
        dict: Contains `success` and `message`.
    
    Raises:
        If the campaign is not loaded, try to load it first. Refer to `load_campaigns_from_db`.
        If the campaign is not running, try to start it first. Refer to `control_campaign_lifecycle`.
        If the campaign has no browser context, try to restart. Refer to `control_campaign_lifecycle`.
        If any URLs provided do not match the campaign's, the process is aborted.
        If at least two pages have the same URL, the process is aborted. This is unlikely.
        If there are no credentials available for the campaign, check the Flying Dutchman for errors
            or add credentials to the campaign.
        If there is a failure in sending the HTTP request, the error message is likely explanatory.
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
        if campaign is None: raise Exception("Campaign is None, cannot control lifecycle")
        await _control_campaign_lifecycle(campaign, "start", playwright)
        if campaign.status != "running":
            raise Exception(f"Expected status 'running', got '{campaign.status}'")
        ctx = await campaign.pause()
        if campaign.status != "paused":
            raise Exception(f"Expected status 'paused', got '{campaign.status}'")
        await campaign.resume(ctx)
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