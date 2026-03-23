"""Skill: get_joke — 從 JokeAPI 取得隨機笑話"""

import urllib.request
import json


def get_joke(args: dict) -> dict:
    category = args.get("category", "Any")
    url = f"https://v2.jokeapi.dev/joke/{category}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    if data.get("type") == "twopart":
        return {"joke": f"{data['setup']}\n{data['delivery']}"}
    return {"joke": data.get("joke", "沒有笑話")}
