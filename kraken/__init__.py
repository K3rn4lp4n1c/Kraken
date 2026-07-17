from fastmcp import FastMCP
from pathlib import Path

DB_DIRPATH = Path(__file__).resolve().parent / "db"

kraken = FastMCP(
    name="Kraken",
    instructions="""Kraken is an autonomous agent that can solve Capture the Flag (CTF)
    challenges, submit flags, and provide writeups for the challenges it solves.""",
    version="1.0.0",
    website_url="https://github.com/k3rn4lp4n1c/Kraken",
)