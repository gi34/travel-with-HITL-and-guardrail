import os, asyncio
import certifi
from dotenv import load_dotenv

load_dotenv()

os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import TypedDict, Annotated, Any
import operator, json
import uuid
import psycopg
from psycopg.rows import dict_row
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import(AnyMessage,HumanMessage,AIMessage, SystemMessage)

from langchain_groq import ChatGroq
from mcp_client import (
    tavily_mcp_search, 
    aviation_search, 
    extract_destination, 
    forecast_mcp_search, 
    weather_mcp_search
)



# return database url to save long term memory (shared state, conversation)
def get_database():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url




# ===========
# LLM
# ========

llm = ChatGroq(
    model= 'openai/gpt-oss-safeguard-20b',
    api_key=os.getenv('GROQ_API_KEY')
    )

def llm_text(system_prompt: str, user_prompt:str) -> str:
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content = user_prompt),
    ]
    )
    return str(response.content)


# convert llm otuput to json format: ez for communication between agent
def llm_2_json(text:str) -> dict[str,Any]:
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end< start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start:end+1])


def empty_constraints()->dict[str:Any]:
    return {
        "destination":"",
        "prigin":"",
        "duration":"",
        "budget":"",
        "travel_style":"",
        "special_preferences":[],
    }



# ==============
# Shared State
# ==============

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage],operator.add]
    user_query: str

    # supervisor and guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # specialist status
    flight_status: str
    hotel_result:str
    weather: str
    budget: str
    itinerary: str
    llm_calls: int

    # Budget and HITL state
    budget_results: str
    approval_request: str
    approved:bool
    human_feedback: str
    final_response:str

# ========
# agents
# ========

# use set to prevent changes
AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "itinerary_agent",
}

AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent"
]



# ============
# Supervisor Agent with guardrails
# ============
guardrail_prompt= """
Determine whether the following request belongs to travel planning or travel information. 
Valid requests can include destination, flights, hotels, weather, budgets, cisas, transportation, sightseeing, food, packing or itineraries.

Block clearly unrelated requests and requests asking for harmful or illegal instrucstions.
Do not block a valid travel request merely because some details are missing.

Return strict JSON only:
{{
"allowed": true,
"reason":""
}}

User request: {query}

"""


supervisor_prompt = """
You are the supervisor of a multi-agent travel planning system.
Choose only the specialsit agents needed for the request.

Available agents:
- flight_agent: flights, airports, airlines, routes, airfare, or booking advice.
- hotel_agent: hotels, accomodation, neighborhoods, or places to stay.
- weather_agent: weather, climate, season, forecast, or packing advice.
- budget_agent: cost, affordability, price limits, or budget feasibility.
- itinerary_agent: creates the integrated travel plan and must always be included

Return strict JSON only using this schema:

{{
"selected-agents": ["flight_agent", "hotel_agent","weather_agent","budget_agent", "itinerary_agent"]
"trip_constraints":{{
"destination":"",
"origin":"",
"duration":"",
"budget":"",
"travel_style":"",
"special_preferences":[]
}}
"reasoning":""
}}

User query: {query}
"""

def supervisor_guardrail_agent(state:TravelState):
    original_query = state['user_query']
    human_feedback = str(state.get('human_feedback', '') or '').strip()
    query = original_query

    if human_feedback:
        query = apply_human_feedback_to_query(original_query, human_feedback)

    llm_calls = state['llm_calls']

    # pass the guardrail first
    try: 
        supervisor_guardrail_prompt_query = guardrail_prompt.format(query=query)
        guardrails_raw = llm_text(
            "You are the input guardrail for a travel-planning applciation. Return strict JSON only.",
            supervisor_guardrail_prompt_query
            )

        guardrail_result = llm_2_json(guardrails_raw)
        allowed = bool(guardrail_result.get("allowed", True))
        guardrail_reason = str(guardrail_result.get("reason","")).strip()
        llm_calls+=1

    except Exception as e:
        print(f"Guardrail fallback used: {e}")
        allowed = True
        guardrail_reason = "Guardrail validation fallback allowed the request."


    # if does not pass the guardrail
    if not allowed:
        reason = guardrail_reason or (
            "Travel Agent can only help with travel-planning requests."
            "Please ask about a destination, flight, hotel, weather, budget, "
        )

        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents":[],
            "trip_constraints": empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content = f"Guardrail blocked request: {reason}")],
            "llm_calls" : llm_calls
        }

    # if pass the guardrail
    try:
        supervisor_prompt_query = supervisor_prompt.format(query=query)
        supervisor_raw = llm_text(
            "You route work to travel specialist agents. Return strict JSON only.",
            supervisor_prompt_query,
        )

        parsed = llm_2_json(supervisor_raw)
        request_agents = parsed.get("selected_agents",[])
        selected_agents = [
            name for name in AGENT_ORDER
            if name in request_agents and name in AGENTS
        ] # maintain the order of agent, eg must get flight first before hotel

        # must-have
        if "itinerary_agent" not in selected_agents:
            selected_agents.append("itinerary_agent")

        constraints = empty_constraints()
        parsed_constraints = parsed.get("trip_constraints",{})

        if isinstance(parsed_constraints, dict):
            constraints.update(parsed_constraints)

        reasoning = str(parsed.get("reasoning","")).strip()
        llm_calls +=1

    except Exception as e:
        print(f"Supervisor fallback used: {e}")

        selected_agents = AGENT_ORDER.copy()
        constraints = empty_constraints()
        reasoning = (
            "Supervisor parsing failed, so the original full travel workflow was selected as a safe fallback."
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content = "Supervisor created the agent plan.")],
        "llm_calls": llm_calls
    }


# ===============
# Guardrail blocked request agent
# ===============
def guardrail_blocked_agent(state:TravelState):
    reason = state.get("final_response") or state.get("guardrail_reason") or (
        "This request was blocked by the travel input guardrail."
    )

    return {
        "final_response": reason,
        "messages": [AIMessage(content=reason)]
    }




# every agent returns the result to update the shared status
# ==============
# flight agent
# ==============
# add llm to the function: to decide which tool to use from MCP

flight_prompt = """
You are a travel flight expert. Provide answer to the question using the provided information only.

Query : {query}

Airport Information: {airport_information}

Airline Information: {airline_information}

Generate answer with the format:
1. Likely departure airport
2. Likely arrival airport
3. Airline
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""

def flight_agent(state: TravelState):
    print("\nInside Flight Agent")

    query = state["user_query"]

    try:
        airports = asyncio.run(
            aviation_search("list_airports")
        )

        airlines = asyncio.run(
            aviation_search("list_airlines")
        )

        print("\nAirports:\n", airports)
        print("\nAirlines:\n", airlines)


        prompt = flight_prompt.format(
            query=query,
            airport_information=str(airports)[:3000],
            airline_information=str(airlines)[:3000]
        )

        response = llm.invoke([
            SystemMessage(content = "You are an expert travel flight planner."),
            HumanMessage(content = prompt)
        ])

        flight_data = response.content

    except Exception as e:
        flight_data = f"Flight information unavailable: {str(e)}"

    # update the status
    return {
        "flight_status": flight_data,
        "messages": [
            AIMessage( content = "Flight recommendations generated")
        ],
        "llm_calls": state.get("llm_calls",0)+1
    }




# ==============
# Hotel agent
# ==============

def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"

    try: 
        hotel_results = asyncio.run(tavily_mcp_search(query))

    except Exception as e:
        print(
            f"Hotel agent MCP error: "
            f"{type(e).__name__}: {e}",
            flush = True
        )

        hotel_results = (
            "Live hotel search is temporarily unavailable." 
            "Provide general accomodation and neighborhood" 
            "guidance based on the destination and clearly label it as non-live advice"
        )


    return {
        "hotel_result": hotel_results,
        "messages": [
            AIMessage(content = "Hotel information fetched")
        ],
        "llm_calls": state.get("llm_calls",0) +1
    }




# ==============
# Weather agent
# ==============
def weather_agent(state:TravelState):
    query = state["user_query"]
    city = extract_destination(query)

    try: 
        weather_result = asyncio.run(weather_mcp_search(city))
        forecast_result = asyncio.run(forecast_mcp_search(city))

        weather_results= f"""
Curent Weather: {weather_result}
Forecast:{forecast_result}

"""
    except Exception as e:
        print(
            f"Weather agent MCP error: "
            f"{type(e).__name__}:{e}",
            flush=True
        )

        weather_results = (
            f"Live weather information for {city}"
            "is temporarily unavailable. GIve general seasonal guidance and advice the traveler"
            "to verify the forcast before departure."
        )

    return {
        "weather": weather_results,
        "messages":[
            AIMessage(content = "Weather Information processed")
        ]
    }


# ============
# Budget Agent
# ============
def budget_agent(state:TravelState):
    prompt = f'''
Analyze whether this trip is realistic for the user's budget.

User query: {state['user_query']}

Trip Constraint : {state['trip_constraints']}

Flight Results:{state['flight_status']}

Hotel Results: {state['hotel_result']}

Budget Results: {state.get('budget_results', '')}

Weather Results: {state['weather']}

Return:
1. Estiamted cost categories
2. Budget risk areas
3. Money-saving suggestions
4. Overall feasibility

If exact live prices are unavailable, clearly label estimates as approximate
'''

    response = llm.invoke(
        [
            SystemMessage(content= "You are a practical travel budget analyst."),
            HumanMessage(content=prompt)
        ]
    )

    return {
        "budget_results": response.content,
        "messages": [AIMessage(content="budget assessment generated.")],
        "llm_calls":state.get("llm_calls",0)+1
    }

# ==============
# itinerary agent
# ==============

def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Trip Constraints:
{state['trip_constraints']}

Flight Results:
{state['flight_status']}

Hotel Results:
{state['hotel_result']}

Weather Results:
{state["weather"]}

Budget Results:
{state.get('budget_results', '')}

Make theitinerary practical, budget-aware and easy to follow.
Create a clear draft that is ready for human review.
"""

    response = llm.invoke([
        SystemMessage(content = "You are an expert travel planner."),
        HumanMessage(content=prompt)
    ])

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create final polished plan, or provide feedback for revision."
    )

    return {
        "itinerary": response.content,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get('llm_calls',0)+1
    }



# =========
# Human in the loop
# =========

def apply_human_feedback_to_query(original_query: str, human_feedback: str) -> str:
    if not human_feedback:
        return original_query

    normalized = human_feedback.strip()
    lower_feedback = normalized.lower()

    if "from " in lower_feedback and " to " in lower_feedback:
        import re
        match = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:\.|$)", lower_feedback, flags=re.IGNORECASE)
        if match:
            old_origin = match.group(1).strip()
            new_origin = match.group(2).strip()
            query = re.sub(
                rf"from\s+{re.escape(old_origin)}",
                f"from {new_origin}",
                original_query,
                flags=re.IGNORECASE,
            )
            if query != original_query:
                return query

    if "change the origin" in lower_feedback or "origin" in lower_feedback:
        import re
        match = re.search(r"to\s+([A-Za-z][A-Za-z\s-]+?)(?:\.|$)", normalized, flags=re.IGNORECASE)
        if match:
            new_origin = match.group(1).strip()
            return re.sub(
                r"from\s+[A-Za-z][A-Za-z\s-]*",
                f"from {new_origin}",
                original_query,
                flags=re.IGNORECASE,
            )

    return f"{original_query} Update: {normalized}"


def human_approval_agent(state:TravelState):
    review = interrupt(
        {
            "question":"Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary",""),
            "approval_request": state.get("approval_request",""),
            "selected_agents": state.get("selected_agents",""),
            "supervisor_reasoning": state.get("supervisor_reasoning",""),
            "expected_response":{
                "approved":True,
                "feedback": "Optional revision feedback"
            }

        }
    )


    approved = bool(review.get("approved",False))
    human_feedback = str(review.get("feedback","")).strip()
    updated_query = state.get("user_query", "")

    if human_feedback:
        updated_query = apply_human_feedback_to_query(state.get("user_query", ""), human_feedback)

    return{
        "approved": approved,
        "human_feedback": human_feedback,
        "user_query": updated_query,
        "messages": [AIMessage(content="Human approval step completed.")]
    }


# ==============
# Final response agent
# ==============

def final_agent(state:TravelState):

    user_feedback = (state.get('human_feedback') or '').strip()

    if user_feedback:
        if state.get("approved", False):
            review_instruction = (
                "The user approved the draft but also provided additional adjustments to apply. "
                f"Apply these changes carefully before finalizing:\n{user_feedback}"
            )
        else:
            review_instruction = f'''
The user requested a revision. Apply this feedback carefully:
{user_feedback}
'''
    elif state.get("approved", False):
        review_instruction = (
            "The user approved the draft. Preserve its decisions while polishing it."
        )
    else:
        review_instruction = '''
The user requested a revision. Improve the draft before finalizing it.
'''

    final_prompt = f"""
Generate the final travel response for the user.

User Request:
{state['user_query']}

Supervisor Constraints:
{state['trip_constraints']}

Human Review Instruction:
{review_instruction}

Flights:
{state['flight_status']}

Hotels:
{state['hotel_result']}

Weather:
{state['weather']}

Budget Analysis:
{state.get('budget_results', '')}

Itinerary:
{state['itinerary']}

Format the final answer beautifully using these selections:

1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Important:
- Be clear and practical.
- Mention that live lfight API may not provide ticket prices if pricing is unavailable.
- Keep the repsonse useful for real travel planning.
- Incorporate the human feedback when revision was requested.
"""

    response = llm.invoke([
        SystemMessage(content = "You are a professional AI travel booking assistant."),
        HumanMessage(content=final_prompt)
    ])

    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls",0) + 1
    }



# =========
# Dynamic Supervisor Routing
# =========

Route_map={
    "guardrail_blocked": "guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent"
}

def selected_agents(state:TravelState):
    selected = state.get("selected_agents",[])
    return [agent for agent in AGENT_ORDER if agent in selected]


def route_from_supervisor(state:TravelState):
    if not state.get('guardrail_allowed',True):
        return "guardrail_blocked"

    selected = selected_agents(state)
    return selected[0] if selected else "itinerary_agent"


def route_after_agent(current_agent:str):
    def route(state:TravelState):
        selected = selected_agents(state)
        current_index = AGENT_ORDER.index(current_agent)

        for next_agent in AGENT_ORDER[current_index + 1:]:
            if next_agent in selected:
                return next_agent

        return "itinerary_agent"

    return route


def route_after_human_approval(state:TravelState):
    approved = bool(state.get('approved', False))

    if approved:
        return "final_agent"

    return "supervisor"


# ==============
# Graph
# ==============

graph = StateGraph(TravelState)

graph.add_node("supervisor", supervisor_guardrail_agent)
graph.add_node("guardrail_blocked", guardrail_blocked_agent)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("budget_agent",budget_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("human_approval", human_approval_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route_from_supervisor, Route_map)

graph.add_conditional_edges("flight_agent", route_after_agent("flight_agent"), Route_map)
graph.add_conditional_edges("hotel_agent", route_after_agent("hotel_agent"), Route_map)
graph.add_conditional_edges("weather_agent", route_after_agent("weather_agent"), Route_map)
graph.add_conditional_edges("budget_agent", route_after_agent("budget_agent"), Route_map)

graph.add_edge("itinerary_agent", "human_approval")
graph.add_conditional_edges(
    "human_approval",
    route_after_human_approval,
    {
        "supervisor": "supervisor",
        "final_agent": "final_agent",
    },
)
graph.add_edge("final_agent", END)
graph.add_edge("guardrail_blocked",END)




# ==============
# Postgre Database
# ==============
DATABASE_URL = get_database()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row
)

checkpointer = PostgresSaver(_conn)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)


def interrupt_payload(result: dict[str,Any])-> dict[str,Any]|None:
    interrupts = result.get("__interrupt__",[])
    if not interrupts:
        return None

    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value":payload}


def serialize_result(
        result:dict[str,Any],
        thread_id: str
) -> dict[str,Any]:

    messages = result.get("messages",[])
    last_messages = messages[-1].content if messages else ""

    answer = result.get("final_response") or last_messages
    interrupt_payloads = interrupt_payload(result)

    if interrupt_payloads:
        answer = interrupt_payloads.get("draft_itinerary") or result.get("itinerary","")

    return {
        "thread_id":thread_id,
        "answer": answer,
        "requires_approval": interrupt_payloads is not None,
        "approval_request": (
            interrupt_payloads.get("approval_request","")
            if interrupt_payloads else result.get("approval_request","")
        ),
        "flight_results": result.get("flight_status",""),
        "hotel_results": result.get("hotel_result",""),
        "weather": result.get("weather",""),
        "budget_results": result.get("budget_results",""),
        "itinerary": (
            interrupt_payloads.get("draft_itinerary","")
            if interrupt_payloads else result.get("itinerary","")
        ),
        "selected_agents": result.get("selected_agents",[]),
        "trip_constraints": result.get("trip_constraints",{}),
        "supervisor_reasoning": result.get("supervisor_reasoning",""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason",""),
        "human_feedback": result.get("human_feedback",""),
        "llm_calls": result.get('llm_calls',0)
    }



# ==============
# Function for FastAPI: to handle HTTP request and python logic
# mainly to connect the python logic to HTTP via FastAPI
# ==============
def run_travel_agent(user_input: str, thread_id: str| None = None):
    if not thread_id:
        thread_id=f"user_{uuid.uuid4().hex}" # generate a random unique identifier

    config = {
        "configurable": {
            "thread_id": thread_id  # LangGraph configure the checkpoint with PostgreSQL to save and retrieve the state of this conversation
        }
    }


    '''
    *** the 'configurable' tells LangGraph that this value controls how the graph runs, but it is not part of the graph's travelstate (shared state)
    '''
    
    result = travel_graph.invoke(
        {
            "messages":[
                HumanMessage(content = user_input)
            ],
            "user_query": user_input,
            "guardrail_allowed": True,
            "guardrail_reason": "",
            "selected_agents":[],
            "trip_constraints": empty_constraints(),
            "supervisor_reasoning":"",
            "flight_status": "",
            "hotel_result":"",
            "weather":"",
            "itinerary":"",
            "approval_request":"",
            "approved":False,
            "human_feedback":"",
            "final_response": "",
            "llm_calls":0
        },
        config=config
    )

    return serialize_result(result, thread_id)


def resume_travel_agent(thread_id:str, approved:bool, feedback:str=""):
    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        Command(
            resume={
                "approved": approved,
                "feedback": feedback.strip(),
            }
        ),
        config=config,
    )

    print('\n=================\n')
    print('Response for revise:\n',result)

    return serialize_result(result, thread_id)