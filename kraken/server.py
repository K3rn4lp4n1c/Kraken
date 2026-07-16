#!/.venv/bin/python3
from fastmcp import FastMCP
import requests

# Initialize your server
kraken = FastMCP("My First Server")

# Define a tool using a decorator
@kraken.tool()
def fetch_web_page(url: str) -> str:
    """
    Fetches the raw text content of a given URL. 
    Use this whenever the user asks you to read or review a website.
    """
    try:
        response = requests.get(url, timeout=10)
        return response.text[:2000] # Return the first 2000 characters
    except Exception as e:
        return f"Error fetching page: {str(e)}"