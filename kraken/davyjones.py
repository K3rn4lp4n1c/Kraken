from . import MCP_SERVER
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from dotenv import load_dotenv

import os
import asyncio

load_dotenv()

transport = StdioTransport(command="python3",
                           args=["-m", MCP_SERVER, "--transport", "stdio"],
                           env=os.environ.copy())

client = Client(transport=transport)

headless = False

async def main():
    if client is None:
        print("Client is not initialized.")
        return
    async with client:
        await client.ping()

        result = await client.call_tool("captain_load_campaigns_from_db", {
            "campaign_ids": ["3"], "plugin_names": ["htb-auth"]
        })
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to load campaigns: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("captain_control_campaign_lifecycle",
                                        {"cid": "3", "action": "start", "headless": headless})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to start campaign: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("quartermaster_append_challenges", {
            "cid": "3", "new_challenges": [
                {
                    "title": "Pilot",
                    "description": "What is the lastname of the man in the picture in this link?",
                    "points": 100,
                    "category": "Warmup",
                    "flag": "",
                    "solves": 0,
                    "platform_id": 1,
                }
            ]
        })
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return

        result = await client.call_tool("quartermaster_peek_challenges", {"cid": "3"})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        challenges = result.structured_content.get("challenges", [])
        if not challenges:
            print("No challenges found for the campaign.")
            return

        # result = await client.call_tool("captain_authenticate_campaign", {
        #     "cid": "3",
        #     "page_url": "https://ctf.hackthebox.com/",
        #     "endpoint": ("https://ctf.hackthebox.com/api/users/profile", {
        #         "method": "GET",
        #         "headers": { "Accept": "application/json" },
        #         "mode": "cors",
        #         "credentials": "include",
        #         "body": None
        #     }),
        #     "expected_codes": [200]
        # })

        # await asyncio.sleep(5)  # Wait for a moment to ensure the authentication process completes

        # result = await client.call_tool("navigator_scout_campaign", {
        #     "cid": "3",
        #     "page_url": "https://ctf.hackthebox.com/event/details/ctf-try-out-1434",
        #     "force": True,
        #     "endpoints": [
        #         (f"https://ctf.hackthebox.com/api/public/company-registration-status", {
        #             "method": "GET",
        #             "headers": { "Accept": "application/json" },
        #             "mode": "cors",
        #             "credentials": "include",
        #             "body": None
        #         }),
        #     ]
        # })
        # if result.structured_content is None:
        #     print("No structured content returned from the tool call.")
        #     return
        # if not result.structured_content.get("success", False):
        #     print(f"Failed to scout campaign: {result.structured_content.get('message', 'Unknown error')}")
        #     return

        # if not headless:
        #     try:
        #         while True:
        #             pass
        #     except KeyboardInterrupt:
        #         print("Stopping the campaign...")
        result = await client.call_tool("captain_control_campaign_lifecycle",
                                        {"cid": "3", "action": "stop", "headless": headless})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to stop campaign: {result.structured_content.get('message', 'Unknown error')}")
            return
        print("Campaign stopped successfully.")