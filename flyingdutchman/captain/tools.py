from . import captain
from flyingdutchman import DB_DIRPATH
from flyingdutchman.powderboy import *

CAMPAIGNS_DB_PATH = DB_DIRPATH / "chronicles.sqlite3"

def _get_campaigns() -> tuple[bool, str, list[dict]]:
    """
    Campaigns are CTF events that The Flying Dutchman has, can, or will participate in.
    This function fetches the list of all campaigns (except that with id '0') from the database.

    Returns:
        tuple[bool, str, list[dict]]:
        A tuple containing a successful status, a message, and a list of dictionaries
        Each dictionary represents an campaign with its details. 
    """
    try:
        campaigns_table = env("CAMPAIGNS_TABLE")[0]
        with sqlite3_connect(CAMPAIGNS_DB_PATH) as conn:
            cursor = conn.cursor()
            fields = ["id", "name", "datetime", "url", "status"]
            cursor.execute("SELECT {} FROM {}".format(', '.join(fields), campaigns_table))
            rows = cursor.fetchall()
            campaigns = [dict(zip(fields, row)) for row in rows]
            return True, "Campaigns fetched successfully.", campaigns
    except Exception as e:
        return False, f"Error fetching campaigns: {str(e)}", []

@captain.tool()
def get_campaigns() -> dict:
    """
    Campaigns are CTF events that The Flying Dutchman has, can, or will participate in.
    This tool fetches the list of all campaigns (except that with id '0') from the database.

    Returns:
        dict: This will contain the success status, a message and the campaigns list.
        Expenditions contain the following fields: id, name, datetime, url, status
    """
    success, message, campaigns = _get_campaigns()
    return {"success": success, "message": message, "campaigns": campaigns }

def triage() -> tuple[list[str], list[bool]]:
    configure_logger(__name__)
    logger = logging.getLogger(__name__)
    checklist: list[str] = []
    checks: list[bool] = []

    checklist.append("CAMPAIGNS_DB_PATH exists")
    checks.append(CAMPAIGNS_DB_PATH.exists())

    checklist.append("Campaigns Retrieval was successful")
    try:
        success, message, _ = _get_campaigns()
        if not success: raise Exception(message)
        checks.append(True)
    except Exception as e:
        checks.append(False)
        logger.exception("Error fetching campaigns: %s", str(e))
    return checklist, checks