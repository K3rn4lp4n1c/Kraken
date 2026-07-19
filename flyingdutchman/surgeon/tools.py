from dotenv import load_dotenv
from flyingdutchman.powderboy import configure_logger, env, sqlite3_connect
from flyingdutchman import DB_DIRPATH
from flyingdutchman.captain import triage as captain
from flyingdutchman.navigator import triage as navigator
from flyingdutchman.carpenter import playwright

import logging

async def _crew_checkup():
    logger = logging.getLogger(__name__)
    if not __debug__: logger.warning("Beware! Crew checkups while campaigning is not recommended.")
    load_dotenv()
    checklist: list[str] = []
    checks: list[bool] = []
    id = "0" # NOTE: IDs are autoincremented as they come starting from 1, so use 0 for testing ;)
    url = "https://architectural-presumptuously-jeanine.ngrok-free.dev/ctf" # Ngrok rocks! (for now)

    checklist.append("Database connection is successful")
    try:
        test_db_path = DB_DIRPATH / "test.sqlite3"
        with sqlite3_connect(test_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            if result is not None and result[0] == 1: checks.append(True)
            else: checks.append(False)
    except Exception as e:
        checks.append(False)
        print(f"Database connection failed: {e}")
    
    captain_result = captain()
    checklist.extend(captain_result[0])
    checks.extend(captain_result[1])

    await playwright.start()
    navigator_result = await navigator(playwright, id, url)
    checklist.extend(navigator_result[0])
    checks.extend(navigator_result[1])

    return checklist, checks

async def main():
    configure_logger(debug=True)
    logger = logging.getLogger(__name__)
    checklist, checks = await _crew_checkup()
    for item, check in zip(checklist, checks):
        status = "\033[32mPASS\033[0m" if check else "\033[31mFAIL\033[0m"
        logger.info(f"{item}: {status}")
    if all(checks): logger.info("All checks passed. Crew is ready for the campaign!")
    else: logger.warning("Some checks failed. Crew is not ready for the campaign.")