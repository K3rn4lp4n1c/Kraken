from . import MCP_SERVER
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

import json

transport = StdioTransport(command="python3", args=["-m", MCP_SERVER])

client = Client(transport=transport)

async def main():
    if client is None:
        print("Client is not initialized.")
        return
    async with client:
        await client.ping()

        result = await client.call_tool("captain_load_campaigns_from_db", {"campaign_ids": ["3"]})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to load campaigns: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("captain_control_campaign_lifecycle", {"cid": "3", "action": "start"})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to start campaign: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("navigator_scout_campaign", {"cid": "3", "force": True,
                                        "page_url": "https://ctf.hackthebox.com/event/details/ctf-try-out-1434",
                                        "headers": {
                                        },
                                        "endpoints": [(
                                            "https://ctf.hackthebox.com/api/users/profile",
                                            {"method": "GET",
                                            "headers": {
                                                "Content-Type": "application/json",
                                                }
                                            }
                                        )]
                                    })
        with open("scout_campaign.har", "w") as f:
            structured_content = result.structured_content
            if structured_content is None:
                print("No structured content returned from the tool call.")
                return
            har_content = structured_content.get("har_content")
            if har_content is None:
                print("No HAR content returned from the tool call.")
                return
            json.dump(har_content, f, indent=4)