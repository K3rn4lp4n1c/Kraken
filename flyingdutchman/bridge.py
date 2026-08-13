from . import flyingdutchman, playwright, campaigns
from dotenv import load_dotenv
from argparse import ArgumentParser, Namespace
from bitwarden_sdk import BitwardenClient
from flyingdutchman.captain import captain
from flyingdutchman.navigator import navigator
from flyingdutchman.quartermaster import quartermaster
from flyingdutchman.carpenter import carpenter, configure_logger, env

import os
import logging

def _resolve_args() -> Namespace:
    parser = ArgumentParser(description="Flying Dutchman")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--transport", choices=["stdio", "http"], default="http", help="Transport method for Flying Dutchman")
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transport")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP transport")
    parser.add_argument("--path", default="/mcp", help="Path for HTTP transport")
    args = parser.parse_args()
    if args.transport == "http" and (not args.host or not args.port or not args.path):
        parser.error("HTTP transport requires --host, --port, and --path arguments")
    transport_kwargs = {
        "host": args.host, "port": args.port, "path": args.path
    } if args.transport == "http" else {}
    setattr(args, "transport_kwargs", transport_kwargs)
    return args

def _mount_subservers():
    logger = logging.getLogger(__name__)
    logger.debug("Mounting subservers...")
    flyingdutchman.mount(captain, "captain")
    flyingdutchman.mount(navigator, "navigator")
    flyingdutchman.mount(carpenter, "carpenter")
    flyingdutchman.mount(quartermaster, "quartermaster")
    logger.debug("Subservers mounted successfully.")

def _load_secrets():
    logger = logging.getLogger(__name__)
    logger.debug("Loading secrets from .env and Bitwarden...")
    load_dotenv()
    client = BitwardenClient()
    token, org_id, proj_id = env("BITWARDEN_ACCESS_TOKEN,BITWARDEN_ORG_ID,BITWARDEN_PROJECT_ID")
    client.auth().login_access_token(token)
    response = client.secrets().sync(org_id, None)
    if not response.success or response.data is None:
        raise Exception(f"Failed to retrieve secret from Bitwarden: {response.error_message}")
    secrets = response.data.secrets or []
    project_secrets = {s.key: s.value for s in (secrets) if str(s.project_id) == proj_id}
    os.environ.update(project_secrets)

async def main():
    args = _resolve_args()
    configure_logger(debug=args.debug)
    logger = logging.getLogger(__name__)
    _load_secrets()
    _mount_subservers()
    try:
        await playwright.start()
        await playwright.start_headed()
        logger.info("Who dares disturb the Flying Dutchman over %s?!", args.transport)
        await flyingdutchman.run_async(transport=args.transport, **args.transport_kwargs)
    except Exception as e:
        logger.exception(f"The Flying Dutchman shipwrecked: {e}")
        raise Exception(f"The Flying Dutchman shipwrecked: {e}") from e
    except KeyboardInterrupt:
        logger.info("The Flying Dutchman is docking...")
    finally:
        await campaigns.clear()
        await playwright.stop_headed()
        await playwright.stop()
        logger.info("The Flying Dutchman has docked.")