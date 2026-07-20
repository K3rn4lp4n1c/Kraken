from fastmcp import FastMCP
from pathlib import Path
from flyingdutchman.powderboy import PlaywrightManager

PROJECT_ROOT = Path(__file__).resolve().parent

ASSETS_DIRPATH = PROJECT_ROOT.parent / "assets"
DB_DIRPATH = ASSETS_DIRPATH / "db"
HAR_DIRPATH = ASSETS_DIRPATH / "har"
PLAYWRIGHT_AUTH_DIRPATH = PROJECT_ROOT.parent / ".auth"
DB_PATH = DB_DIRPATH / "chronicles.sqlite3"

flyingdutchman = FastMCP(
    name="The Flying Dutchman",
    instructions="""The Flying Dutchman is an MCP server that hosts a lot of tools that are
    used to access Capture the Flag (CTF) events, solve challenges, and submit flags""",
    version="1.0.0",
    website_url="https://github.com/k3rn4lp4n1c/Kraken",
)

playwright = PlaywrightManager()

for dir_path in [ASSETS_DIRPATH, DB_DIRPATH, HAR_DIRPATH, PLAYWRIGHT_AUTH_DIRPATH]:
    Path.mkdir(dir_path, parents=True, exist_ok=True)