from dotenv import load_dotenv
from flyingdutchman import playwright, DB_PATH
from flyingdutchman.powderboy import configure_logger, env, sqlite3_connect
from flyingdutchman.captain import triage as captain
from flyingdutchman.navigator import triage as navigator

import logging

async def _crew_checkup():
    logger = logging.getLogger(__name__)
    if not __debug__: logger.warning("Beware! Crew checkups while campaigning is not recommended.")
    load_dotenv()
    checklist: list[str] = []
    checks: list[bool] = []
    id = "0" # NOTE: IDs are autoincremented as they come starting from 1, so use 0 for testing ;)
    url = "https://architectural-presumptuously-jeanine.ngrok-free.dev/ctf" # Ngrok rocks! (for now)
    initial_campaign: dict | None = None

    checklist.append("Database connection is successful")
    try:
        campaigns_table = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM {} WHERE id = ?".format(campaigns_table), (id,))
            result = cursor.fetchone()
            if result is not None and str(result[0]) == id:
                initial_campaign = dict(zip([column[0] for column in cursor.description], result))
                initial_campaign.pop("id", None)
                checks.append(True)
            else:
                logger.error(f"No campaign found with id: {id} {result}")
                checks.append(False)
    except Exception:
        checks.append(False)
        logger.exception(f"Database connection failed")
    finally:
        if initial_campaign is None:
            logger.error(f"Initial campaign state could not be fetched for id: {id}.")
            return checklist, checks

    captain_result = await captain(id)
    checklist.extend(captain_result[0])
    checks.extend(captain_result[1])

    await playwright.start()
    navigator_result = await navigator(playwright, id, url)
    checklist.extend(navigator_result[0])
    checks.extend(navigator_result[1])

    checklist.append("Cleanup was successful")
    try:
        campaigns_table = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(DB_PATH) as conn:
            cursor = conn.cursor()
            query = "UPDATE {} SET {} WHERE id = ?".format(
                    campaigns_table,
                    ', '.join(f"{k} = ?" for k in initial_campaign.keys())
                )
            cursor.execute(query, tuple(initial_campaign[k] for k in initial_campaign.keys()) + (id,))
            conn.commit()
        checks.append(True)
    except Exception:
        checks.append(False)
        logger.exception("Error during cleanup")
    finally:
        await playwright.stop()
    return checklist, checks

async def main():
    configure_logger(debug=True)
    await playwright.start()
    logger = logging.getLogger(__name__)
    checklist, checks = await _crew_checkup()
    for item, check in zip(checklist, checks):
        status = "\033[32mPASS\033[0m" if check else "\033[31mFAIL\033[0m"
        logger.info(f"{item}: {status}")
    if all(checks): logger.info("All checks passed. Crew is ready for the campaign!")
    else: logger.warning("Some checks failed. Crew is not ready for the campaign.")