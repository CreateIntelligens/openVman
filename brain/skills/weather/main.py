"""Weather skill implementation."""

from typing import Any, Dict

def get_current_weather(args: Dict[str, Any]) -> Dict[str, Any]:
    """Mock implementation of getting current weather."""
    location = args.get("location")
    unit = args.get("unit", "celsius")
    
    # In a real skill, this would call a weather API
    return {
        "location": location,
        "temperature": 22 if unit == "celsius" else 72,
        "unit": unit,
        "condition": "Sunny",
        "humidity": 45
    }
