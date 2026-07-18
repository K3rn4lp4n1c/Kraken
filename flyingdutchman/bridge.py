from . import flyingdutchman
from dotenv import load_dotenv
from flyingdutchman.captain import captain
from flyingdutchman.navigator import navigator
from flyingdutchman.powderboy import env, configure_logger

import logging

def mount_subservers():
    logger = logging.getLogger(__name__)
    logger.debug("Mounting subservers...")
    flyingdutchman.mount(captain, "captain")
    flyingdutchman.mount(navigator, "navigator")
    logger.debug("Subservers mounted successfully.")

def main():
    debug = True
    configure_logger(__name__, debug=debug)
    logger = logging.getLogger(__name__)
    mount_subservers()
    try:
        if debug: load_dotenv()
        transport = env("FLYING_DUTCHMAN_TRANSPORT")[0]
        logger.info("Who dares disturb the Flying Dutchman over %s?!", transport)
        if transport == "stdio":
            flyingdutchman.run(transport="stdio")
        elif transport == "http":
            host, port = env("FLYING_DUTCHMAN_HOST,FLYING_DUTCHMAN_PORT", "127.0.0.1,8000")
            flyingdutchman.run(transport="http", host=host, port=int(port))
        else: raise ValueError(f"Unsupported transport: {transport}")
    except Exception as e:
        logger.exception(f"The Flying Dutchman shipwrecked: {e}")
    except KeyboardInterrupt:
        logger.info("The Flying Dutchman is docking...")
    finally:
        logger.info("The Flying Dutchman has docked.")