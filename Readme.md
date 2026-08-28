# Travel Agent with MCP
This project is a continuous from Traval agent that integrate MCP into the graph-based agent system.

The system receives user query and perform flight, hotel and weather search to produce a detailed itineray plan. The objective is to learn and explore the usage of different types of MCP -- Remote MCP, local MCP and custom MCP.

> **Disclaimer:** This project is for learning purpose only. Always refer to the official website for the flight and hotel status.

---

## MCP Integration
This project incorporate MCP in different tools:
- Tavily: Use remote MCP
- AviationStack: local STUDIO MCP
- Weather: Custom MCP

---

## Learning Outcomes
- MCP acts as a universal port that it enables mininal changes when an API upgrade
- List of tools can be accessed via MCP, therefore no custom function is needed -- increase modularity and maintainability of a system
- Easy to maintain and expand when number of agent increase: All coordinate though LangGrah workflow and MCP

---

## Tech Stack
- Python
- FastAPI
- LangGraph
- LangChain
- PostgreSQL
- Tavily
- AviationStack
- MCP
- asyncio
- Docker

---

## Project Structure
```
travel agent
├── app.py              # frontend
├── backend.py          # backend
├── DockerFile          # Docker
├── mcp_client          # list of mcp client (tools)
├── requirements.txt    # requirements 
├── test.py             # for testing purpose
└── weather_mcp.py      # custom MCP server
```
