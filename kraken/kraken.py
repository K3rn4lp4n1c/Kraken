from . import kraken
from kraken.captain import captain
import requests

def mount_subservers():
    kraken.mount(captain, "captain")

def main():
    mount_subservers()
    try:
        kraken.run(transport="http", host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        print("Server stopped by user.")

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