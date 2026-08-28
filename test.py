from MCP_client_test import tavily_mcp_search
import asyncio


if __name__ == "__main__":
    query = "lastest news about AI"
    asyncio.run(tavily_mcp_search(query))