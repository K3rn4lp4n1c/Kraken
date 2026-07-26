from dotenv import load_dotenv
from flyingdutchman import playwright, DB_PATH
from flyingdutchman.carpenter import configure_logger, env, sqlite3_connect
from flyingdutchman.captain import triage as captain
from flyingdutchman.navigator import triage as navigator

import logging

async def _prenup(cid: str) -> dict:
    campaigns_table = env("CAMPAIGNS_TABLE")[0]
    with sqlite3_connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM {} WHERE id = ?".format(campaigns_table), (cid,))
        result = cursor.fetchone()
    if result is not None and str(result[0]) == cid:
        initial_campaign = dict(zip([column[0] for column in cursor.description], result))
        initial_campaign.pop("id", None)
        return initial_campaign
    else: raise ValueError(f"No campaign found with id: {cid}")

async def _crew_checkup(id: str, url: str, scout_path: str, scout_endpoint: tuple[str, dict],
                        har_should_contain: tuple[str, ...]) -> tuple[list[str], list[bool]]:
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []

    captain_result = await captain(id)
    campaign = captain_result[0]
    checklist.extend(captain_result[1])
    checks.extend(captain_result[2])
    
    checklist.append("Campaign object is valid")
    if campaign is None:
        checks.append(False)
        return checklist, checks
    else: checks.append(True)

    scout_url = url.rstrip("/") + scout_path
    navigator_result = await navigator(campaign, scout_url, scout_endpoint)
    har = navigator_result[0].lower()
    checklist.extend(navigator_result[1])
    checks.extend(navigator_result[2])

    checklist.append("HAR file contains expected strings")
    if not all(s in har for s in har_should_contain):
        for s in har_should_contain:
            if s not in har: logger.warning(f"Expected string '{s}' not found in HAR file.")
        checks.append(False)
    else: checks.append(True)

    return checklist, checks

async def _cleanup(initial_campaign: dict, id: str):
    campaigns_table = env("CAMPAIGNS_TABLE")[0]
    with sqlite3_connect(DB_PATH) as conn:
        cursor = conn.cursor()
        query = "UPDATE {} SET {} WHERE id = ?".format(
                campaigns_table,
                ', '.join(f"{k} = ?" for k in initial_campaign.keys())
            )
        cursor.execute(query, tuple(initial_campaign[k] for k in initial_campaign.keys()) + (id,))
        conn.commit()

async def main():
    logger = logging.getLogger(__name__)
    if not __debug__: logger.warning("Beware! Crew checkups while campaigning is not recommended.")
    load_dotenv()
    configure_logger(debug=True)
    await playwright.start()
    checklist: list[str] = []
    checks: list[bool] = []
    id = "0" # NOTE: IDs are autoincremented as they come starting from 1, so use 0 for testing ;)
    url = "https://architectural-presumptuously-jeanine.ngrok-free.dev/ctf" # Ngrok rocks! (for now)
    endpoint = (url + "/api/v1/challenges", 
                {"method": "GET", 
                "headers": {
                    "Content-Type": "application/json",
                    'ngrok-skip-browser-warning': '1'
                }})
    scout_url_path = "/challenges"
    har_should_contain = ("challenges", "warmup", "pilot")
    initial_campaign: dict | None = None

    checklist.append("Database connection is valid")
    try:
        initial_campaign = await _prenup(id)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error fetching initial campaign state: %s", str(e))
    
    try:
        res = await _crew_checkup(id, url, scout_url_path, endpoint, har_should_contain)
        checklist.extend(res[0])
        checks.extend(res[1])
        for item, check in zip(checklist, checks):
            status = "\033[32mPASS\033[0m" if check else "\033[31mFAIL\033[0m"
            logger.info(f"{item}: {status}")
        if all(checks): logger.info("All checks passed. Crew is ready for the campaign!")
        else: logger.warning("Some checks failed. Crew is not ready for the campaign.")
    except Exception as e:
        logger.exception("Error during crew checkup")
    
    try:
        if initial_campaign is not None:
            await _cleanup(initial_campaign, id)
            logger.info("Initial campaign state restored successfully.")
        else: logger.warning("Initial campaign state was not fetched, skipping cleanup.")
    except Exception as e:
        logger.exception("Error restoring initial campaign state: %s", str(e))