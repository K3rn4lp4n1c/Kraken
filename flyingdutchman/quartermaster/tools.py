from . import quartermaster
from flyingdutchman import campaigns
from flyingdutchman.carpenter.extensions import Challenge

def _append_challenges(cid: str, new_challenges: list[dict]) -> tuple[bool, str]:
    """
    Append new challenges to the campaign's existing challenges.

    Args:
        cid (str): The campaign ID to which the challenges will be added.
        new_challenges (list[campaigns.Challenge]): A list of Challenge objects to be added.
    """
    try:
        campaign = campaigns.get_campaign(cid)
        if campaign is None:
            raise ValueError(f"Campaign with ID '{cid}' not found.")
        
        challenge_objects = [Challenge(**challenge) for challenge in new_challenges]
        campaign.append(challenge_objects)
    except ValueError as ve:
        return False, str(ve)
    except Exception as e:
        return False, f"Internal Server Error in appending challenges: {str(e)}"
    return True, "Challenges appended successfully."

@quartermaster.tool()
def append_challenges(cid: str, new_challenges: list[dict]) -> dict:
    """
    Append new challenges to the campaign's existing challenges.

    Challenges must follow this schema:
    ```
    {
        "title": str,
        "description": str,
        "points": int,
        "category": str,
        "solves": int,
        "scout_format": tuple[str, list[tuple[str, dict]]] | None,
        "platform_id": str | None,
        "instance_and_files": {
            "protocol": str | None,
            "host": str | None,
            "port": int | None,
            "files": list[str] | None
        }
        "flag": str | None
    }
    ```
    Titles, descriptions, points, categories, and flag are self-explanatory.

    Solves is the number of solves for the challenge and answers the question
    "How many people have solved this challenge?"

    Scout format is a tuple containing the page URL and a list of tuples,
    each containing an endpoint URL and a request initialization dictionary.
    This is would usually come from scouting and helps to reproduce the challenge environment later.

    Platform ID is an optional identifier for the challenge on a specific platform.
    It helps to avoid duplicates and can be used for secondary tracking purposes.

    Instance is an optional dictionary containing instance details for the challenge,
    such as protocol, host, and port. A challenge only has one instance at a time
    but plugins can allow a challenge to accommodate multiple instances.

    Args:
        cid (str): The campaign ID to which the challenges will be added.
        new_challenges (list[dict]): A list of Challenge objects to be added.
    Returns:
        dict: Contains `success` and `message`.
    """
    success, message = _append_challenges(cid, new_challenges)
    return {"success": success, "message": message}

def _peek_challenges(cid: str, mode="minimal", offset: int = 0, limit: int = 100,
                    filters: tuple[dict] | None = None) -> tuple[bool, str, list[dict]]:
    """
    Fetch all challenges for a given campaign.

    Args:
        cid (str): The campaign ID for which challenges will be fetched.
        mode (str): The mode of challenge details to return. Can be "minimal" or "full".
        offset (int): The starting index for the challenges to fetch.
        limit (int): The maximum number of challenges to return.
        filters (tuple[dict] | None): Optional filters to apply to the challenges.
    Returns:
        tuple: A tuple containing a boolean indicating success, a message, and a list of challenges.
    """
    try:
        campaign = campaigns.get_campaign(cid)
        if campaign is None:
            raise ValueError(f"Campaign with ID '{cid}' not found.")
        challenges: list[dict] = []
        if mode == "full":
            challenges = [dict(challenge) for challenge in campaign.challenges]
        elif mode == "minimal":
            challenges = [{
                "title": c.title,
                "points": c.points,
                "category": c.category,
                "solves": c.solves,
                "platform_id": c.platform_id,
                } for c in campaign.challenges]
        else: raise ValueError(f"Invalid mode '{mode}'. Use 'minimal' or 'full'.")
        offset = max(min(offset, len(challenges)), 0)
        limit = max(min(limit, len(challenges) - offset), 0)
        challenges = challenges[offset:offset + limit]
        if filters:
            for f in filters:
                challenges = [challenge for challenge in challenges if all(challenge.get(k) == v for k, v in f.items())]
    except ValueError as ve:
        return False, str(ve), []
    except Exception as e:
        return False, f"Internal Server Error in fetching challenges: {str(e)}", []
    return True, "Challenges fetched successfully.", challenges[offset:offset + limit]

@quartermaster.tool()
def peek_challenges(cid: str, mode="minimal", offset: int = 0, limit: int = 100,
                   filters: tuple[dict] | None = None) -> dict:
    """
    Fetch all challenges for a given campaign.

    If mode is "minimal", only the title, points, category, solves, and platform_id will be returned.
    If mode is "full", all challenge details will be returned.

    Filters can be applied to the challenges to narrow down the results.
    Each filter should be a dictionary where the key is the challenge attribute
    and the value is the expected value for that attribute.

    If you wish to expand the filtering capabilities, create or lookup a plugin to attach to the campaign

    Args:
        cid (str): The campaign ID for which challenges will be fetched.
        mode (str = 'minimal'): The mode of challenge details to return. Can be "minimal" or "full".
        offset (int = 0): The starting index for the challenges to fetch.
        limit (int = 100): The maximum number of challenges to return.
        filters (tuple[dict] | None = None): Optional filters to apply to the challenges
    Returns:
        dict: Contains `success`, `message`, and `challenges`.
    """
    success, message, challenges = _peek_challenges(cid, mode, offset, limit, filters)
    return {"success": success, "message": message, "challenges": challenges}