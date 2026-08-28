from pathlib import Path
import traceback, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from backend import run_travel_agent
import nest_asyncio

# allow nested event loops for async calls in FastAPI
nest_asyncio.apply()


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title = "travel agent",
    description="LangGraph Multi-Agent Travel Planner with FastAPI Frontend",
    version="1.0.0"
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR/"static")),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR/"templates")
)

class TravelRequest(BaseModel):
    message: str
    thread_id: str | None = None


'''
app.get('/') is called automatically by the browser
not seen in script.js -- the initial page request happens before the js file is loaded
'''
@app.get("/", response_class = HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name = "index.html",
        context={}
    )


'''
1. User clicks the send button (the function can be found in script.js)
2. The button triggers sendMessages() in script.js
3. sendMessage() sends a POST request to "/api/travel"
4. the FastAPI matches the POST request here to execute the travel_planner function
5. call run_travel_agent() and runs the LangGraph workflow, returns the json response
6. script.js receives the JSON response and proceed to showResult()
'''
@app.post("/api/travel")
async def travel_planner(request_data: TravelRequest):
    try:
        user_message = request_data.message.strip()

        if not user_message:
            return JSONResponse(
                status_code=400,
                content={
                    "success":False,
                    "error": "Message cannot be empty."
                }
            )

        result = run_travel_agent(
            user_input=user_message,
            thread_id=request_data.thread_id
        )

        return JSONResponse(
            content={
                "success": True,
                "thread_id": result["thread_id"],
                "answer": result["answer"],
                "flight_results": result["flight_status"],
                "hotel_results": result["hotel_results"],
                'weather': result["weather"],
                "itinerary": result["itinerary"],
                "llm_calls": result["llm_calls"]
            }
        )

    except Exception as e:
        print("ERROR:",e)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/health")
async def health_check():
    return{
        "status": "ok",
        "message": "AI Travel Planner API is running"
    }

@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(content={})


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host= "127.0.0.1",
        port=8000,
        reload=True
    )