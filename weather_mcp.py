from mcp.server.fastmcp import FastMCP
import requests, os
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Weather MCP")
WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")


# add decorator to make it as mcp server
@mcp.tool()
def get_weather (city:str):
    response = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={
            "q": city,
            "appid": WEATHER_API_KEY,
            "units": "metric"
        }
    )

    data=response.json()

    if response.status_code!= 200:
        return data

    return {
        "city": data['name'],
        "feels_like_c": data["main"]["feels_like"],
        "temperature_c" : data["main"]["temp"],
        "humidity": data["main"]["humidity"],
        "condition": data["weather"][0]["description"],
        "wind_speed" : data["wind"]["speed"]
    }



@mcp.tool()
def get_forecast(city:str):
    url = ("https://api.openweathermap.org/data/2.5/forecast")

    params = {
        "q":city,
        "appid": WEATHER_API_KEY,
        "units": "metric"
    }

    response = requests.get(url, params=params)

    data = response.json()

    forecast=[]

    for item in data["list"][:5]:
        forecast.append(
            {
                "datetime": item["dt_txt"],
                "temperature": item["main"]["temp"],
                "weather":item["weather"][0]["description"]
            }
        )

    return {
        "city":city,
        "forecast": forecast
    }


# run mcp in local, automatically use STDIO
if __name__ == "__main__":
    mcp.run()