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

        result = await client.call_tool("captain_load_campaigns_from_db", {"campaign_ids": ["0"]})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to load campaigns: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("captain_control_campaign_lifecycle", {"cid": "0", "action": "start"})
        if result.structured_content is None:
            print("No structured content returned from the tool call.")
            return
        if not result.structured_content.get("success", False):
            print(f"Failed to start campaign: {result.structured_content.get('message', 'Unknown error')}")
            return

        result = await client.call_tool("navigator_scout_campaign", {"id": "0", "force": True,
                                        "url": "https://architectural-presumptuously-jeanine.ngrok-free.dev/ctf",
                                        "headers": {
                                            "ngrok-skip-browser-warning": "true"
                                        },
                                        "endpoints": [(
                                            "https://architectural-presumptuously-jeanine.ngrok-free.dev/ctf/challenges",
                                            {"method": "GET",
                                            "headers": {
                                                "Content-Type": "application/json",
                                                'ngrok-skip-browser-warning': 'true'
                                                }
                                            }
                                        )]
                                    })
        with open("scout_campaign.har", "w") as f:
            structured_content = result.structured_content
            if structured_content is None:
                print("No structured content returned from the tool call.")
                return
            json.dump(result.structured_content, f, indent=4)