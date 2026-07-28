from . import flyingdutchman, playwright, campaigns
from dotenv import load_dotenv
from flyingdutchman.captain import captain
from flyingdutchman.navigator import navigator
from flyingdutchman.carpenter import configure_logger, env

import logging

def _mount_subservers():
    logger = logging.getLogger(__name__)
    logger.debug("Mounting subservers...")
    flyingdutchman.mount(captain, "captain")
    flyingdutchman.mount(navigator, "navigator")
    logger.debug("Subservers mounted successfully.")

async def main():
    debug = True
    if debug: load_dotenv()
    configure_logger(debug=debug)
    logger = logging.getLogger(__name__)
    _mount_subservers()
    try:
        await playwright.start()
        transport = env("FLYING_DUTCHMAN_TRANSPORT")[0]
        logger.info("Who dares disturb the Flying Dutchman over %s?!", transport)
        if transport == "stdio":
            await flyingdutchman.run_async(transport="stdio")
        elif transport == "http":
            host, port, path = env("FLYING_DUTCHMAN_HOST,FLYING_DUTCHMAN_PORT,FLYING_DUTCHMAN_PATH")
            await flyingdutchman.run_async(transport="http", host=host, port=int(port), path=path)
        else: raise ValueError(f"Unsupported transport: {transport}")
    except Exception as e:
        logger.exception(f"The Flying Dutchman shipwrecked: {e}")
        raise Exception(f"The Flying Dutchman shipwrecked: {e}") from e
    except KeyboardInterrupt:
        logger.info("The Flying Dutchman is docking...")
    finally:
        await campaigns.clear()
        await playwright.stop()
        logger.info("The Flying Dutchman has docked.")