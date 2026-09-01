# Travel Agent with MCP, Supervisor agent, HITL and Guardrails
This project is a continuous from Traval agent with MCP -- supervisor agent, guardrails and HITL are added into the existing architecture.

The system receives user query and perform flight, hotel and weather search to produce a detailed itineray plan. The objective is to learn and explore the usage of different types of MCP -- Remote MCP, local MCP and custom MCP.

> **Disclaimer:** This project is for learning purpose only. Always refer to the official website for the flight and hotel status.

---

## New Features
This project integrated new features:
- Supervisor agent: breakdown the task into subtasks and delegate to specific subagent.
- HITL (Human-in-the-loop): user approves or do changes to the result before passing to the final agent.
- guardrails: add guardrails to the agent to prevent injection of harmful prompt/request.

---

## Learning Outcomes
- Supervisor agent: act as the manager to breakdown and delegate tasks to subagents -- use only the necessary agent, no more manual workflow (centralised orchestration).
- HITL: user decides whether the result is up to expectation and perform amendment during the loop.
- Guardrails: model based guardrails.

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
- multi-agent orchestration
- Guardrails

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