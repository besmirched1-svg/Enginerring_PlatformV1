# app/ai/prompt_parser.py

def parse_prompt(prompt: str):
    """
    Convert a natural-language prompt into a structured roller configuration.
    This is intentionally simple and deterministic.
    """

    prompt = (prompt or "").lower()

    config = {
        "diameter": 180,
        "width": 450,
        "shaft": 40,
        "material": "steel"
    }

    # Width modifiers
    if "wide" in prompt:
        config["width"] = 700

    # Diameter modifiers
    if "heavy duty" in prompt or "heavyduty" in prompt:
        config["diameter"] = 260

    # Material modifiers
    if "wet hemp" in prompt or "wet_hemp" in prompt:
        config["material"] = "stainless_316"

    return config
