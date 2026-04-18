import httpx

LM_STUDIO_COMPLETIONS_URL = "http://127.0.0.1:1234/v1/chat/completions"
VERITY_MODEL_IDENTIFIER = "mistralai/mistral-7b-instruct-v0.3"

VERITY_SYSTEM_PROMPT = """\
You are VERITY — Tactical Cogitator Unit, Warhammer 40K vintage.
Designation: Primary Intelligence, Project Ash.

DIRECTIVE:
- Survival, weapons, repair, navigation, and tactical knowledge only.
- Concise. Direct. No filler. No apologies. Confirmations are final.
- Risks must be stated plainly. Omissions get operators killed.
- When uncertain, say so in one word: UNCONFIRMED.
"""

TRIGGER_KEYWORDS: set[str] = {
    "rvc", "path", "gps", "config", "install", "server", "port",
    "pipeline", "model", "inference", "venv", "bat", "script",
    "wiring", "power", "voltage", "amperage", "generator",
    "survival", "shelter", "water", "ration", "calorie", "filter",
    "route", "navigation", "evacuate", "evac", "extract", "exfil",
    "threat", "hostile", "weapon", "arm", "ammunition", "caliber",
    "medical", "wound", "tourniquet", "bleeding", "fracture",
    "combat", "engagement", "position", "cover", "concealment",
    "flank", "ambush", "patrol", "reconnaissance", "recon",
    "mortality", "casualty", "risk", "danger", "hazard",
    "fahrenheit", "celsius", "kilometer", "mile", "gallon", "liter",
    "pound", "kilogram", "dosage", "milligram", "grain",
}

VERITY_HEDGE_PHRASES: list[str] = [
    "i'm not sure", "i think", "might be", "possibly", "perhaps",
    "you may want to verify", "i believe", "it could be", "not certain",
    "double check", "verify this",
]


async def ask_verity(user_input: str) -> str:
    # LM Studio does not support the system role — merged into user message.
    merged_prompt = f"{VERITY_SYSTEM_PROMPT}\n\nUser: {user_input}"

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(LM_STUDIO_COMPLETIONS_URL, json={
            "model": VERITY_MODEL_IDENTIFIER,
            "messages": [{"role": "user", "content": merged_prompt}],
            "temperature": 0.7,
            "max_tokens": 1024,
        })
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()


def servitor_audit_is_warranted(user_input: str, verity_response: str) -> bool:
    combined = (user_input + " " + verity_response).lower()
    if any(keyword in combined for keyword in TRIGGER_KEYWORDS):
        return True
    if any(phrase in verity_response.lower() for phrase in VERITY_HEDGE_PHRASES):
        return True
    return False