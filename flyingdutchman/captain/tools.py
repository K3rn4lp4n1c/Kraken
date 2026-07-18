from . import captain
from flyingdutchman import DB_DIRPATH
from flyingdutchman.powderboy import env, sqlite3_connect

EXPEDITIONS_DB_PATH = DB_DIRPATH / "chronicles.sqlite3"

def _get_expeditions() -> tuple[bool, str, list[dict]]:
    """
    Expeditions are CTF events that The Flying Dutchman has, can, or will participate in.
    This function fetches the list of all expeditions from the database.

    Returns:
        tuple[bool, str, list[dict]]:
        A tuple containing a successful status, a message, and a list of dictionaries
        Each dictionary represents an expedition with its details. 
    """
    try:
        expeditions_table = env("EXPEDITIONS_TABLE")[0]
        with sqlite3_connect(EXPEDITIONS_DB_PATH) as conn:
            cursor = conn.cursor()
            fields = ["id", "name", "datetime", "url", "status"]
            cursor.execute("SELECT {} FROM {}".format(', '.join(fields),expeditions_table))
            rows = cursor.fetchall()
            expeditions = [dict(zip(fields, row)) for row in rows]
            return True, "Expeditions fetched successfully.", expeditions
    except Exception as e:
        return False, f"Error fetching expeditions: {str(e)}", []

@captain.tool()
def get_expeditions() -> dict:
    """
    Expeditions are CTF events that The Flying Dutchman has, can, or will participate in.
    This tool fetches the list of all expeditions from the database.

    Returns:
        dict: This will contain the success status, a message and the expeditions list.
        Expenditions contain the following fields: id, name, datetime, url, status
    """
    success, message, expeditions = _get_expeditions()
    return {"success": success, "message": message, "expeditions": expeditions }