from fastmcp import FastMCP
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ASSETS_DIRPATH = PROJECT_ROOT.parent / "assets"
DB_DIRPATH = ASSETS_DIRPATH / "db"
HAR_DIRPATH = ASSETS_DIRPATH / "har"

flyingdutchman = FastMCP(
    name="The Flying Dutchman",
    instructions="""The Flying Dutchman is an MCP server that hosts a lot of tools that are
    used to access Capture the Flag (CTF) events, solve challenges, and submit flags""",
    version="1.0.0",
    website_url="https://github.com/k3rn4lp4n1c/Kraken",
)