from . import MCP_SERVER
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from dotenv import load_dotenv

import os

load_dotenv()

transport = StdioTransport(command="python3", args=["-m", MCP_SERVER], env=os.environ.copy())

client = Client(transport=transport)

async def main():
    if client is None:
        print("Client is not initialized.")
        return
    async with client:
        await client.ping()

        result = await client.call_tool("captain_load_campaigns_from_db", {
            "campaign_ids": ["3"], "plugin_name": "htb"
        })
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to load campaigns: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("captain_control_campaign_lifecycle",
                                        {"cid": "3", "action": "start", "headless": False})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to start campaign: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("captain_authenticate_campaign", {
            "cid": "3",
            "page_url": "https://ctf.hackthebox.com/",
            "endpoint": ("https://ctf.hackthebox.com/api/users/profile", {
                "method": "GET",
                "headers": { "Accept": "application/json" },
                "mode": "cors",
                "credentials": "include",
                "body": None
            }),
            "expected_codes": [200]
        })

        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("Stopping the campaign...")
        result = await client.call_tool("captain_control_campaign_lifecycle",
                                        {"cid": "3", "action": "stop", "headless": False})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to stop campaign: {result.structured_content.get('message', 'Unknown error')}")
            return
        print("Campaign stopped successfully.")