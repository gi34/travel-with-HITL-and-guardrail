import os, asyncio, certifi
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUEST_CA_BUNDLE"] = certifi.where()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATION_STACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")
WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


# A single MCP that provide different tools (API):
client = MultiServerMCPClient(
    {
        "tavily": {
            "transport":"streamable_http",      #remote MCP server
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        },

        "Aviationstack": {
            "transport": "stdio",               # local MCP server
            "command": "/Users/lamhuishan/Documents/vs code/travel agent/.venv/bin/uvx",
            "args": [
                "--with",
                "mcp<2",
                "aviationstack-mcp"
              ],
              "env": {
                "AVIATION_STACK_API_KEY": AVIATION_STACK_API_KEY
              }
            },

        "weather":{
            "transport": "stdio",
            "command": "/Users/lamhuishan/Documents/vs code/travel agent/.venv/bin/python",
            "args": [
                os.path.join(os.path.dirname(__file__), "weather_mcp.py")
            ],
            "env": {
                "OPEN_WEATHER_API_KEY": WEATHER_API_KEY
            }
        }

    }
)


async def get_tools():
    tools = await client.get_tools()
    print("\nAvailable tools:\n")

    for tool in tools:
        print(tool.name)




# ===============
# Tavily and Aviation Tools from MCP
# ===============

search_tool = None
aviation_tools = {}

async def initialize_mcp():

    global search_tool, aviation_tools


    # break if search_tool and aviation tool exist
    if search_tool is not None and aviation_tools:
        return


    # else get the tools
    tools = await client.get_tools()

    print("\nAvailable MCP Tools:\n")
    for tool in tools:
        print(tool.name)


    search_tool = next(
        tool
        for tool in tools
        if tool.name == "tavily_search" # get the tool
    )

    aviation_tools = {
        tool.name: tool
        for tool in tools
        if tool.name != "tavily_search"
    }


async def tavily_mcp_search(query:str):

    await initialize_mcp()

    result = await search_tool.ainvoke(
        {
            "query": query
        }
    )

    return result


async def aviation_search(tool_name:str, tool_args: dict=None):
    tools = await client.get_tools()

    tool = next(
        t for t in tools if t.name == tool_name
    )

    result = await tool.ainvoke(
        tool_args or {}
    )

    return result


# ======= 
# weather tool from MCP
# =======

weather_tool = None
forecast_tool=None


async def initialize_weather_tool():

    global weather_tool, forecast_tool

    if weather_tool is not None:
        return

    
    tools = await client.get_tools()

    weather_tool = next(
        tool
        for tool in tools
        if tool.name == "get_weather"
    )

    forecast_tool = next(
        tool
        for tool in tools
        if tool.name == "get_forecast"
    )


async def weather_mcp_search (city:str):
    await initialize_weather_tool()

    return await weather_tool.ainvoke(
        {
            "city":city, 
        }
    )

async def forecast_mcp_search (city:str):
    await initialize_weather_tool()

    return await forecast_tool.ainvoke(
        {
            "city":city, 
        }
    )



# extract destination from query
llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model= "openai/gpt-oss-20b"
)

prompt = """
Extract only the destination city or country.

Query: {query}

Return only destination name.
"""

def extract_destination(query:str):
    response = llm.invoke(prompt)    

    return response.content.strip()