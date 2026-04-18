import re

RISK_BANDS: dict[str, tuple[int, int]] = {  # noqa: UP006
    "armed_conflict":   (35, 85),
    "civil_unrest":     (20, 60),
    "infrastructure":   (5,  40),
    "navigation":       (2,  25),
    "medical":          (10, 70),
    "environmental":    (5,  45),
    "general_survival": (10, 60),
    "benign":           (0,  5),
}

_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("armed_conflict",   ["combat", "weapon", "hostile", "armed", "firefight", "engagement"]),
    ("civil_unrest",     ["riot", "protest", "unrest", "looting", "civil"]),
    ("medical",          ["wound", "bleeding", "injury", "medical", "trauma", "dosage"]),
    ("navigation",       ["route", "path", "highway", "road", "travel", "navigate"]),
    ("environmental",    ["flood", "fire", "storm", "earthquake", "weather"]),
    ("general_survival", ["survival", "shelter", "water", "food", "ration"]),
    ("infrastructure",   ["power", "generator", "wiring", "voltage", "grid"]),
]


def classify_risk_category(combined_text: str) -> str:
    lowered = combined_text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(word in lowered for word in keywords):
            return category
    return "benign"


def clamp_mortality_to_risk_band(raw_estimate: float, category: str) -> float:
    low, high = RISK_BANDS.get(category, (0, 100))
    return max(low, min(high, raw_estimate))


def parse_servitor_structured_output(raw_text: str, query_and_response_context: str) -> dict[str, object]:
    result: dict[str, object] = {
        "raw": raw_text,
        "status": "UNKNOWN",
        "confidence": None,
        "mortality_estimate": None,
        "risk_category": None,
        "deficiency": None,
        "amendment": None,
        "recommended_action": None,
    }

    if "STATUS: OPTIMAL" in raw_text:
        result["status"] = "OPTIMAL"
    elif "STATUS: CRITICAL" in raw_text:
        result["status"] = "CRITICAL"
    elif "STATUS: REVIEW" in raw_text:
        result["status"] = "REVIEW"

    confidence_match = re.search(r"CONFIDENCE:\s*(\d+)%", raw_text)
    if confidence_match:
        result["confidence"] = int(confidence_match.group(1))

    mortality_match = re.search(r"MORTALITY_ESTIMATE:\s*(\d+)%", raw_text)
    if mortality_match:
        raw_mortality = int(mortality_match.group(1))
        category = classify_risk_category(query_and_response_context)
        result["mortality_estimate"] = clamp_mortality_to_risk_band(raw_mortality, category)
        result["risk_category"] = category

    deficiency_match = re.search(r"DEFICIENCY:\s*(.+?)(?=\n|AMENDMENT|$)", raw_text, re.DOTALL)
    if deficiency_match:
        result["deficiency"] = deficiency_match.group(1).strip()

    amendment_match = re.search(r"AMENDMENT:\s*(.+?)(?=\n|RECOMMENDED_ACTION|$)", raw_text, re.DOTALL)
    if amendment_match:
        result["amendment"] = amendment_match.group(1).strip()

    action_match = re.search(r"RECOMMENDED_ACTION:\s*(.+?)(?=\n|```|$)", raw_text, re.DOTALL)
    if action_match:
        result["recommended_action"] = action_match.group(1).strip()

    return result