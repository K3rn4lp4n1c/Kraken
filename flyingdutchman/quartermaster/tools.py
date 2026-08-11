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

    Args:
        cid (str): The campaign ID to which the challenges will be added.
        new_challenges (list[dict]): A list of Challenge objects to be added.
    Returns:
        dict: Contains `success` and `message`.
    """
    success, message = _append_challenges(cid, new_challenges)
    return {"success": success, "message": message}

def _get_challenges(cid: str, mode="minimal") -> tuple[bool, str, list[dict]]:
    """
    Fetch all challenges for a given campaign.

    Args:
        cid (str): The campaign ID for which challenges will be fetched.
        mode (str): The mode of challenge details to return. Can be "minimal" or "full".
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
        else:
            raise ValueError(f"Invalid mode '{mode}'. Use 'minimal' or 'full'.")
    except ValueError as ve:
        return False, str(ve), []
    except Exception as e:
        return False, f"Internal Server Error in fetching challenges: {str(e)}", []
    return True, "Challenges fetched successfully.", challenges

@quartermaster.tool()
def get_challenges(cid: str, mode="minimal") -> dict:
    """
    Fetch all challenges for a given campaign.

    Args:
        cid (str): The campaign ID for which challenges will be fetched.
        mode (str = 'minimal'): The mode of challenge details to return. Can be "minimal" or "full".
    Returns:
        dict: Contains `success`, `message`, and `challenges`.
    """
    success, message, challenges = _get_challenges(cid, mode)
    return {"success": success, "message": message, "challenges": challenges}