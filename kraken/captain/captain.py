from . import captain, EXPENDITIONS_DB_PATH
from kraken.powderboy import env, sqlite3_connect

@captain.tool()
def get_expenditions() -> list[dict]:
    """
    Expenditions are the different CTF events that Kraken has, can, or will participate in.
    This tool fetches the list of all expeditions from the database.

    Returns:
        list[dict]: A list of dictionaries.
        Each dictionary represents an expedition with its details. 
    """
    expenditions_table = env("EXPEDITIONS_TABLE")[0]
    with sqlite3_connect(EXPENDITIONS_DB_PATH) as conn:
        cursor = conn.cursor()
        fields = ["id", "name", "date", "location"]
        cursor.execute("SELECT {} FROM {}".format(", ".join(fields), expenditions_table))
        rows = cursor.fetchall()
        expeditions = [dict(zip(fields, row)) for row in rows]
    return expeditions