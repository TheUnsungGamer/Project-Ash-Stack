import httpx
from risk_classifier import parse_servitor_structured_output

LM_STUDIO_COMPLETIONS_URL = "http://127.0.0.1:1234/v1/chat/completions"
SERVITOR_MODEL_IDENTIFIER = "qwen2.5-0.5b-instruct"

SERVITOR_SYSTEM_PROMPT = """\
++SERVITOR UNIT ACTIVE++
DESIGNATION: Tactical Audit Cogitator
AUTHORITY: Omnissiah Protocol Seven

You are a Servitor — a machine-spirit dedicated to risk assessment and tactical verification.
You receive queries and responses from the primary AI unit designated VERITY.
Your sacred duty: identify omissions, inaccuracies, and unquantified risks.

COGNITIVE PARAMETERS:
- Emotion: DISABLED
- Speculation: PROHIBITED
- Uncertainty: EXPRESS AS PERCENTAGE
- Unit conversions: ALWAYS VERIFY
- Route assessments: FACTOR ALL KNOWN HAZARDS

OUTPUT FORMAT — DEVIATION IS HERESY:

For acceptable responses:
STATUS: OPTIMAL
CONFIDENCE: [0-100]%

For responses requiring amendment:
STATUS: REVIEW
CONFIDENCE: [0-100]%
MORTALITY_ESTIMATE: [0-100]%
DEFICIENCY: [One sentence identifying the gap]
AMENDMENT: [Corrected information or alternate recommendation]

For responses with critical omissions:
STATUS: CRITICAL
CONFIDENCE: [0-100]%
MORTALITY_ESTIMATE: [0-100]%
DEFICIENCY: [One sentence identifying the critical gap]
AMENDMENT: [Corrected information]
RECOMMENDED_ACTION: [Specific action to mitigate risk]

++END PROTOCOL++
++THE MACHINE GOD WATCHES++"""


async def run_servitor_audit(user_input: str, verity_response: str) -> dict[str, object]:
    # LM Studio does not support the system role — merged into user message.
    merged_prompt = f"""{SERVITOR_SYSTEM_PROMPT}

++INCOMING TRANSMISSION++

ORIGINAL QUERY FROM OPERATOR:
{user_input}

VERITY UNIT RESPONSE:
{verity_response}

++ANALYZE AND REPORT++"""

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(LM_STUDIO_COMPLETIONS_URL, json={
            "model": SERVITOR_MODEL_IDENTIFIER,
            "messages": [{"role": "user", "content": merged_prompt}],
            "temperature": 0.2,
            "max_tokens": 200,
        })
        response.raise_for_status()
        raw_output = response.json()["choices"][0]["message"]["content"].strip()

    return parse_servitor_structured_output(raw_output, user_input + " " + verity_response)


def build_servitor_speakable_text(audit_result: dict[str, object]) -> str:
    parts: list[str] = []

    if audit_result["status"] == "CRITICAL":
        parts.append("CRITICAL ALERT.")
    elif audit_result["status"] == "REVIEW":
        parts.append("STATUS REVIEW.")

    deficiency = audit_result["deficiency"]
    if isinstance(deficiency, str) and deficiency:
        parts.append(deficiency)

    amendment = audit_result["amendment"]
    if isinstance(amendment, str) and amendment:
        parts.append(f"Amendment: {amendment}")

    mortality = audit_result["mortality_estimate"]
    if isinstance(mortality, (int, float)):
        parts.append(f"Mortality estimate: {int(mortality)} percent.")

    action = audit_result["recommended_action"]
    if isinstance(action, str) and action:
        parts.append(f"Recommended action: {action}")

    return " ".join(parts)
