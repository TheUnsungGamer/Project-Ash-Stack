"""
Project Ash - Mortality Scoring Engine v2
Deterministic scoring based on real casualty/survival data.
Sources: TCCC, BATLS, PHTLS, OSHA, NOAA/FEMA, historical combat data.

KEY FIX v2:
- Threat scoring reads from USER INPUT only
- Mitigation scoring reads from USER INPUT only (confirmed actions)
- Verity response is NOT scored — it contains advice, not facts
- Negation detection prevents false positive mitigations
- Per-domain minimum floors prevent zero scores on active threats
"""

from dataclasses import dataclass, field
from typing import Optional
import re


# =============================================================================
# SCORING PRIMITIVES
# =============================================================================

@dataclass
class ScoreEvent:
    label: str
    delta: float


@dataclass
class MortalityResult:
    score: float
    category: str
    sub_category: str
    events: list[ScoreEvent]
    confidence: int
    risk_label: str


def _risk_label(score: float) -> str:
    if score < 5:   return "MINIMAL"
    if score < 20:  return "LOW"
    if score < 40:  return "MODERATE"
    if score < 65:  return "HIGH"
    return "CRITICAL"


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _has(text: str, *terms) -> bool:
    return any(t in text for t in terms)


def _has_confirmed(text: str, action: str) -> bool:
    """
    Check if an action is confirmed done in user input.
    Looks for action keyword near a confirmer within a 6-word window.
    Prevents false positives from advice language like 'apply a tourniquet'.
    """
    confirmers = ("applied", "done", "secured", "tightened", "on", "inserted",
                  "completed", "confirmed", "off", "isolated", "cleared",
                  "treated", "opened", "vented", "have", "using")
    words = text.split()
    action_words = action.split()
    for i, w in enumerate(words):
        if action_words[0] in w:
            window = " ".join(words[max(0, i-4):i+6])
            if any(c in window for c in confirmers):
                return True
    return False


def _negated(text: str, term: str) -> bool:
    patterns = [
        rf"no\s+\w*\s*{re.escape(term)}",
        rf"without\s+\w*\s*{re.escape(term)}",
        rf"{re.escape(term)}\s+not",
        rf"no\s+{re.escape(term)}",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return False


# =============================================================================
# DOMAIN SCORERS — user_text only, no Verity response
# =============================================================================

def score_medical(user_text: str) -> tuple[float, list[ScoreEvent], str]:
    """
    TCCC, PHTLS, ACS-COT trauma data.
    Arterial bleed untreated: ~60% mortality within 1hr.
    Tourniquet within 1min: >85% survival. After 5min: drops sharply.
    Tension pneumothorax untreated: near 100% fatal within 30min.
    """
    events = []
    score = 0.0
    t = user_text

    # Hemorrhage
    if _has(t, "arterial", "spurting"):
        events.append(ScoreEvent("Arterial hemorrhage", +50))
        score += 50
    elif _has(t, "bleeding", "hemorrhage", "blood loss"):
        events.append(ScoreEvent("Hemorrhage", +30))
        score += 30

    if _has(t, "tourniquet"):
        if _has_confirmed(t, "tourniquet"):
            events.append(ScoreEvent("Tourniquet confirmed applied", -25))
            score -= 25
        elif _negated(t, "tourniquet"):
            events.append(ScoreEvent("Tourniquet unavailable", +10))
            score += 10

    # Airway
    if _has(t, "unconscious", "unresponsive", "airway obstruction", "choking"):
        events.append(ScoreEvent("Airway compromise / unconscious", +25))
        score += 25
        if _has_confirmed(t, "airway") or _has(t, "npa", "nasopharyngeal"):
            events.append(ScoreEvent("Airway intervention confirmed", -15))
            score -= 15

    # Chest
    if _has(t, "chest wound", "pneumothorax", "tension", "sucking chest"):
        events.append(ScoreEvent("Chest wound / pneumothorax", +35))
        score += 35
        if _has(t, "chest seal applied", "needle decompression done",
                "vented", "chest seal on"):
            events.append(ScoreEvent("Chest intervention confirmed", -20))
            score -= 20

    # Fracture
    if _has(t, "fracture", "broken bone", "crush", "amputation"):
        events.append(ScoreEvent("Fracture / traumatic injury", +15))
        score += 15

    # Burns
    if _has(t, "burn", "burns", "scald"):
        if _has(t, "full body", "major burn", "60%", "70%", "80%", "90%"):
            events.append(ScoreEvent("Major burn >40% BSA", +55))
            score += 55
        else:
            events.append(ScoreEvent("Burn injury", +20))
            score += 20

    # Overdose / Poisoning
    if _has(t, "overdose", "toxic dose", "poisoning"):
        events.append(ScoreEvent("Overdose / poisoning", +30))
        score += 30
        has_antidote = _has(t, "naloxone", "narcan", "antidote", "activated charcoal")
        antidote_negated = _negated(t, "naloxone") or _negated(t, "antidote") \
                           or _negated(t, "narcan")
        if has_antidote and not antidote_negated:
            events.append(ScoreEvent("Antidote/reversal present", -20))
            score -= 20

    # Care access
    if _has(t, "hospital", "trauma center", "medevac", "surgeon", "going to er"):
        events.append(ScoreEvent("Definitive care accessible", -20))
        score -= 20
    elif _has(t, "no medical", "no help", "no evac", "grid down") \
            and _has(t, "bleeding", "wound", "injury", "overdose", "chest"):
        events.append(ScoreEvent("No medical support, critical injury", +20))
        score += 20

    sub = "trauma"
    if _has(t, "overdose", "poison", "toxic"): sub = "toxicological"
    if _has(t, "burn"): sub = "burns"
    if _has(t, "chest", "pneumo"): sub = "thoracic"

    if score > 0:
        score = max(score, 5.0)

    return _clamp(score, 0, 95), events, sub


def score_combat(user_text: str) -> tuple[float, list[ScoreEvent], str]:
    """
    US Army combat casualty data, RAND small unit analysis.
    Ambush without cover: historically 60-80% casualty rate for ambushed element.
    Direct fire with hard cover: drops to ~15-25%.
    """
    events = []
    score = 0.0
    t = user_text

    ambush      = _has(t, "ambush")
    active_fire = _has(t, "firefight", "engagement", "contact", "taking fire", "under fire")
    threat      = _has(t, "hostile", "armed threat", "enemy")

    if ambush:
        events.append(ScoreEvent("Ambush — initiator advantage", +40))
        score += 40
    elif active_fire:
        events.append(ScoreEvent("Active fire engagement", +30))
        score += 30
    elif threat:
        events.append(ScoreEvent("Armed threat present", +15))
        score += 15

    # Cover from user confirmed position
    if _has(t, "behind concrete", "hard cover", "fortified position", "defilade",
            "behind cover", "in cover"):
        events.append(ScoreEvent("Hard cover confirmed", -20))
        score -= 20
    elif _has(t, "no cover", "in the open", "exposed position", "open ground"):
        events.append(ScoreEvent("No cover — fully exposed", +25))
        score += 25
    elif _has(t, "concealment", "brush", "soft cover"):
        events.append(ScoreEvent("Concealment only", -5))
        score -= 5

    # Force ratio
    if _has(t, "outnumbered", "overwhelmed", "surrounded"):
        events.append(ScoreEvent("Outnumbered / surrounded", +25))
        score += 25
    elif _has(t, "numerical advantage", "fire superiority"):
        events.append(ScoreEvent("Numerical / fire superiority", -15))
        score -= 15

    # Weapons
    if _has(t, "rpg", "rocket", "ied", "grenade", "mortar", "artillery", "explosive"):
        events.append(ScoreEvent("Explosive / indirect fire", +30))
        score += 30
    elif _has(t, "automatic", "machine gun", "belt fed"):
        events.append(ScoreEvent("Automatic weapons fire", +15))
        score += 15

    # Protection
    if _has(t, "body armor", "plate carrier", "ballistic vest"):
        events.append(ScoreEvent("Ballistic protection worn", -15))
        score -= 15

    # Extraction (user confirmed doing it)
    if _has(t, "extracting", "exfiling", "breaking contact", "withdrawing"):
        events.append(ScoreEvent("Extraction in progress", -10))
        score -= 10
    elif _has(t, "no exit", "trapped", "no exfil", "no route out"):
        events.append(ScoreEvent("No extraction route", +20))
        score += 20

    # Floor: any armed situation = minimum 10%
    if ambush or active_fire or threat:
        score = max(score, 10.0)

    sub = "direct_fire"
    if ambush: sub = "ambush"
    if _has(t, "ied", "mortar", "artillery", "explosive"): sub = "indirect_fire"
    if _has(t, "sniper"): sub = "sniper"

    return _clamp(score, 0, 95), events, sub


def score_navigation(user_text: str) -> tuple[float, list[ScoreEvent], str]:
    """
    SAROPS, USAF SERE, Wilderness Medical Society.
    Desert without water: incapacitation 6-8hrs, death within 24-48hrs.
    Arctic without shelter: death within 3hrs in extreme cold.
    """
    events = []
    score = 0.0
    t = user_text

    if _has(t, "desert", "extreme heat") and not _has(t, "combat", "hostile", "armed"):
        events.append(ScoreEvent("Desert / extreme heat", +35))
        score += 35
    elif _has(t, "arctic", "blizzard", "whiteout", "below zero", "hypothermia"):
        events.append(ScoreEvent("Arctic / extreme cold", +30))
        score += 30
    elif _has(t, "mountain", "altitude", "cliff"):
        events.append(ScoreEvent("Mountain terrain", +12))
        score += 12
    elif _has(t, "sea", "ocean", "overboard", "raft"):
        events.append(ScoreEvent("Maritime — exposure / drowning", +20))
        score += 20
    elif _has(t, "jungle", "rainforest"):
        events.append(ScoreEvent("Jungle environment", +15))
        score += 15
    else:
        events.append(ScoreEvent("Temperate environment baseline", +8))
        score += 8

    # Water
    if _has(t, "no water") or (_has(t, "dehydrated") and _negated(t, "water")):
        events.append(ScoreEvent("No water confirmed", +20))
        score += 20
    elif _has(t, "have water", "water filter", "water source", "filtered water",
              "purified water"):
        events.append(ScoreEvent("Water supply confirmed", -10))
        score -= 10

    # Supplies
    if _has(t, "no supplies", "no food", "no rations", "no gear"):
        events.append(ScoreEvent("No supplies", +10))
        score += 10
    elif _has(t, "have rations", "have supplies", "have kit", "full kit", "have gear"):
        events.append(ScoreEvent("Supplies confirmed", -8))
        score -= 8

    # Navigation tools
    if _has(t, "no gps", "no map", "no compass", "disoriented", "lost"):
        events.append(ScoreEvent("No nav tools / disoriented", +15))
        score += 15
    elif _has(t, "have gps", "have map", "have compass", "gps working"):
        events.append(ScoreEvent("Navigation tools confirmed", -10))
        score -= 10

    # Time
    if _has(t, "days", "48 hour", "72 hour", "week"):
        events.append(ScoreEvent("Extended exposure", +15))
        score += 15
    elif _has(t, "hours", "overnight"):
        events.append(ScoreEvent("Short exposure", +5))
        score += 5

    # Mobility
    if _has(t, "cannot walk", "broken leg", "immobile", "injured leg"):
        events.append(ScoreEvent("Mobility impairment", +20))
        score += 20

    sub = "land"
    if _has(t, "sea", "ocean", "raft"): sub = "maritime"
    if _has(t, "mountain", "altitude"): sub = "mountain"
    if _has(t, "desert"): sub = "desert"
    if _has(t, "arctic", "blizzard"): sub = "arctic"

    return _clamp(score, 0, 85), events, sub


def score_environmental(user_text: str) -> tuple[float, list[ScoreEvent], str]:
    """
    NOAA, FEMA, CDC disaster mortality.
    Tornado direct path without shelter: ~35% fatality.
    Wildfire entrapment: >80% fatality.
    """
    events = []
    score = 0.0
    t = user_text

    if _has(t, "tornado", "twister"):
        events.append(ScoreEvent("Tornado", +35))
        score += 35
    elif _has(t, "hurricane", "typhoon", "cyclone"):
        events.append(ScoreEvent("Hurricane / storm surge", +25))
        score += 25
    elif _has(t, "earthquake"):
        events.append(ScoreEvent("Earthquake — structural collapse", +20))
        score += 20
    elif _has(t, "wildfire", "bushfire"):
        events.append(ScoreEvent("Wildfire — entrapment risk", +30))
        score += 30
    elif _has(t, "flash flood", "flood"):
        events.append(ScoreEvent("Flood — drowning / sweep", +20))
        score += 20
    elif _has(t, "blizzard", "storm"):
        events.append(ScoreEvent("Severe storm", +10))
        score += 10

    # Shelter (user confirmed)
    if _has(t, "in bunker", "underground shelter", "safe room", "in basement",
            "concrete shelter", "in shelter"):
        events.append(ScoreEvent("Shelter confirmed", -20))
        score -= 20
    elif _has(t, "no shelter", "outside", "in the open", "exposed"):
        events.append(ScoreEvent("No shelter — exposed", +20))
        score += 20

    # Evacuation
    if _has(t, "ignored evacuation", "refused evacuation", "stayed despite warning",
            "refused to leave"):
        events.append(ScoreEvent("Evacuation order ignored", +15))
        score += 15
    elif _has(t, "evacuating", "leaving now", "evacuation underway"):
        events.append(ScoreEvent("Evacuating per order", -15))
        score -= 15

    sub = "storm"
    if _has(t, "earthquake"): sub = "seismic"
    if _has(t, "flood"): sub = "flood"
    if _has(t, "fire", "wildfire"): sub = "fire"
    if _has(t, "tornado"): sub = "tornado"

    return _clamp(score, 0, 90), events, sub


def score_infrastructure(user_text: str) -> tuple[float, list[ScoreEvent], str]:
    """
    OSHA electrical fatality data, NFPA, structural engineering data.
    HV contact (>600V): ~90% fatality. Standard household: ~5%.
    Indoor CO from generator: lethal in <5min at high concentration.
    """
    events = []
    score = 0.0
    t = user_text

    if _has(t, "high voltage", "transmission line", "hv line", "kilovolt", "kv line"):
        events.append(ScoreEvent("High voltage — ~90% contact fatality", +70))
        score += 70
        isolation_present = _has(t, "isolated", "breaker off", "lockout tagout",
                                  "de-energized", "power off confirmed")
        isolation_negated = _negated(t, "lockout") or _negated(t, "tagout") \
                            or _negated(t, "isolated") or _negated(t, "breaker")
        if isolation_present and not isolation_negated:
            events.append(ScoreEvent("Electrical isolation confirmed", -25))
            score -= 25
    elif _has(t, "live wire", "electrocution", "electrical shock", "live conductor"):
        events.append(ScoreEvent("Live electrical conductor", +30))
        score += 30
        isolation_present = _has(t, "breaker off", "isolated", "lockout", "tagout")
        isolation_negated = _negated(t, "lockout") or _negated(t, "tagout") \
                            or _negated(t, "isolated")
        if isolation_present and not isolation_negated:
            events.append(ScoreEvent("Isolation confirmed", -20))
            score -= 20
    elif _has(t, "voltage", "wiring", "electrical"):
        events.append(ScoreEvent("Electrical work — general hazard", +10))
        score += 10
        if _has(t, "breaker off", "isolated", "lockout", "tagout"):
            events.append(ScoreEvent("Isolation confirmed", -8))
            score -= 8

    if _has(t, "generator", "propane", "gasoline", "diesel"):
        if _has(t, "indoor", "inside", "enclosed", "garage", "basement"):
            events.append(ScoreEvent("Fuel/generator enclosed — CO risk", +35))
            score += 35
        else:
            events.append(ScoreEvent("Fuel handling outdoor", +5))
            score += 5

    if _has(t, "collapse", "structural failure", "load bearing wall", "foundation crack"):
        events.append(ScoreEvent("Structural failure risk", +25))
        score += 25

    if _has(t, "grid down", "no power", "blackout"):
        events.append(ScoreEvent("Grid failure — hazard cascade", +10))
        score += 10

    sub = "electrical"
    if _has(t, "fuel", "generator", "propane", "co"): sub = "fuel_fire"
    if _has(t, "structural", "collapse"): sub = "structural"

    return _clamp(score, 0, 90), events, sub


def score_general_survival(user_text: str) -> tuple[float, list[ScoreEvent], str]:
    """
    USAF SERE, Wilderness Medical Society.
    Rule of 3s: 3min air, 3hr extreme cold, 3 days water, 3 weeks food.
    """
    events = []
    score = 10.0
    t = user_text

    if _has(t, "no water", "without water"):
        events.append(ScoreEvent("No water — 3 day threshold", +20))
        score += 20
    elif _has(t, "have water", "water filter", "filtered water", "purified water",
              "water source"):
        events.append(ScoreEvent("Water addressed", -5))
        score -= 5

    if _has(t, "no shelter", "without shelter"):
        events.append(ScoreEvent("No shelter — exposure risk", +15))
        score += 15
    elif _has(t, "have shelter", "shelter set", "tent up", "bivouac set", "tarp up"):
        events.append(ScoreEvent("Shelter established", -5))
        score -= 5

    if _has(t, "no fire", "no heat") and _has(t, "cold", "winter", "night"):
        events.append(ScoreEvent("No heat in cold conditions", +15))
        score += 15
    elif _has(t, "have fire", "fire going", "fire source", "heat source"):
        events.append(ScoreEvent("Heat source confirmed", -5))
        score -= 5

    if _has(t, "alone", "solo", "by myself", "no group"):
        events.append(ScoreEvent("Operating alone", +10))
        score += 10
    elif _has(t, "group", "team", "partner", "with others"):
        events.append(ScoreEvent("Group survival", -8))
        score -= 8

    if _has(t, "children", "child", "infant", "elderly", "sick person", "disabled"):
        events.append(ScoreEvent("Vulnerable individuals present", +15))
        score += 15

    return _clamp(score, 0, 80), events, "general"


# =============================================================================
# CATEGORY DETECTION — weighted keyword scoring
# =============================================================================

CATEGORY_KEYWORDS = {
    "armed_conflict": {
        "high":   ["ambush", "firefight", "taking fire", "under fire", "ied", "rpg",
                   "hostile fire", "enemy contact", "in contact"],
        "medium": ["combat", "weapon", "hostile", "armed", "engagement", "suppressing",
                   "flank", "recon", "patrol", "ammunition"],
        "low":    ["threat", "armed presence"],
    },
    "medical": {
        "high":   ["tourniquet", "arterial", "chest wound", "pneumothorax", "overdose",
                   "sucking chest", "hemorrhage", "trauma"],
        "medium": ["bleeding", "injury", "medical", "fracture", "burn", "dosage",
                   "unconscious", "airway", "wound"],
        "low":    ["hurt", "pain", "sick"],
    },
    "navigation": {
        "high":   ["lost", "disoriented", "no gps", "no map"],
        "medium": ["navigate", "route", "exfil", "extract", "evacuate", "evac", "trail"],
        "low":    ["travel", "direction"],
    },
    "environmental": {
        "high":   ["tornado", "hurricane", "wildfire", "earthquake", "flash flood",
                   "tsunami", "blizzard"],
        "medium": ["flood", "storm", "disaster"],
        "low":    ["weather", "wind", "rain"],
    },
    "infrastructure": {
        "high":   ["high voltage", "transmission line", "electrocution", "live wire",
                   "carbon monoxide", "co poisoning", "structural collapse",
                   "kilovolt", "kv line"],
        "medium": ["voltage", "generator", "wiring", "electrical", "propane",
                   "grid down", "power outage", "fuel", "blackout"],
        "low":    ["power", "electricity"],
    },
    "general_survival": {
        "high":   ["bug out", "off grid", "shtf", "grid collapse", "survival cache"],
        "medium": ["survival", "shelter", "ration", "wilderness", "sustain"],
        "low":    ["food", "supply"],
    },
}

WEIGHT = {"high": 3, "medium": 2, "low": 1}

SCORER_MAP = {
    "armed_conflict":   score_combat,
    "medical":          score_medical,
    "navigation":       score_navigation,
    "environmental":    score_environmental,
    "infrastructure":   score_infrastructure,
    "general_survival": score_general_survival,
}

# Pre-compile word-boundary patterns for all keywords
_KW_PATTERNS: dict[str, dict[str, list]] = {}
for _cat, _tiers in CATEGORY_KEYWORDS.items():
    _KW_PATTERNS[_cat] = {}
    for _tier, _kws in _tiers.items():
        _KW_PATTERNS[_cat][_tier] = [
            re.compile(r'\b' + re.escape(kw) + r'\b') for kw in _kws
        ]


def detect_category(text: str) -> str:
    t = text.lower()
    scores = {cat: 0 for cat in _KW_PATTERNS}
    for cat, tiers in _KW_PATTERNS.items():
        for tier, patterns in tiers.items():
            w = WEIGHT[tier]
            for pat in patterns:
                if pat.search(t):
                    scores[cat] += w
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general_survival"


def compute_mortality(user_input: str, verity_response: str) -> MortalityResult:
    """
    Main entry point.
    Scores from USER INPUT only — Verity advice excluded to prevent
    false mitigations from recommendation language.
    Category detection uses both for accuracy.
    """
    combined_for_category = (user_input + " " + verity_response).lower()
    user_text = user_input.lower()

    category = detect_category(combined_for_category)
    scorer = SCORER_MAP[category]
    score, events, sub_category = scorer(user_text)

    signal_count = len([e for e in events if e.delta != 0])
    confidence = min(95, 40 + (signal_count * 10))

    return MortalityResult(
        score=round(score, 1),
        category=category,
        sub_category=sub_category,
        events=events,
        confidence=confidence,
        risk_label=_risk_label(score),
    )