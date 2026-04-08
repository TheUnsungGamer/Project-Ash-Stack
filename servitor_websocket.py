"""
Project Ash - WebSocket Backend
Parallel Verity + Servitor processing with real-time push

Architecture:
- Verity generates response
- TTS and Servitor fire simultaneously
- Frontend receives events as they complete
- Servitor panel slides in when Verity finishes speaking
"""

import asyncio
import json
import httpx
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

app = FastAPI(title="Project Ash - Verity & Servitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# CONFIGURATION
# =============================================================================

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"  # Both models served here
TTS_URL = "http://127.0.0.1:8000/tts"  # Tech-Priest TTS

# Check LM Studio for exact model names - they appear in the model dropdown
VERITY_MODEL = "mistral-7b-instruct"          # Your main model
SERVITOR_MODEL = "qwen2.5-0.5b-instruct"      # Lightweight audit model

# =============================================================================
# TRIGGER KEYWORDS - when to invoke the Servitor
# =============================================================================

TRIGGER_KEYWORDS = {
    # Technical / infrastructure
    "rvc", "path", "gps", "config", "install", "server", "port",
    "pipeline", "model", "inference", "venv", "bat", "script",
    "wiring", "power", "voltage", "amperage", "generator",
    
    # Survival / tactical
    "survival", "shelter", "water", "ration", "calorie", "filter",
    "route", "navigation", "evacuate", "evac", "extract", "exfil",
    "threat", "hostile", "weapon", "arm", "ammunition", "caliber",
    "medical", "wound", "tourniquet", "bleeding", "fracture",
    
    # Battle assessment
    "combat", "engagement", "position", "cover", "concealment",
    "flank", "ambush", "patrol", "reconnaissance", "recon",
    "mortality", "casualty", "risk", "danger", "hazard",
    
    # Units that need verification
    "fahrenheit", "celsius", "kilometer", "mile", "gallon", "liter",
    "pound", "kilogram", "dosage", "milligram", "grain"
}

HEDGE_PHRASES = [
    "i'm not sure", "i think", "might be", "possibly", "perhaps",
    "you may want to verify", "i believe", "it could be", "not certain",
    "double check", "verify this"
]

# =============================================================================
# RISK BANDING - clamps LLM estimates to realistic ranges
# =============================================================================

RISK_BANDS = {
    "armed_conflict":   (35, 85),
    "civil_unrest":     (20, 60),
    "infrastructure":   (5, 40),
    "navigation":       (2, 25),
    "medical":          (10, 70),
    "environmental":    (5, 45),
    "general_survival": (10, 60),
    "benign":           (0, 5),
}

def detect_risk_category(text: str) -> str:
    """Determine risk category from combined input/response text."""
    text_lower = text.lower()
    
    if any(w in text_lower for w in ["combat", "weapon", "hostile", "armed", "firefight", "engagement"]):
        return "armed_conflict"
    if any(w in text_lower for w in ["riot", "protest", "unrest", "looting", "civil"]):
        return "civil_unrest"
    if any(w in text_lower for w in ["wound", "bleeding", "injury", "medical", "trauma", "dosage"]):
        return "medical"
    if any(w in text_lower for w in ["route", "path", "highway", "road", "travel", "navigate"]):
        return "navigation"
    if any(w in text_lower for w in ["flood", "fire", "storm", "earthquake", "weather"]):
        return "environmental"
    if any(w in text_lower for w in ["survival", "shelter", "water", "food", "ration"]):
        return "general_survival"
    if any(w in text_lower for w in ["power", "generator", "wiring", "voltage", "grid"]):
        return "infrastructure"
    
    return "benign"

def clamp_mortality(raw_estimate: float, category: str) -> float:
    """Clamp LLM mortality estimate to realistic band for category."""
    min_val, max_val = RISK_BANDS.get(category, (0, 100))
    return max(min_val, min(max_val, raw_estimate))

# =============================================================================
# SERVITOR SYSTEM PROMPT - The Tech-Priest's sacred instructions
# =============================================================================

SERVITOR_SYSTEM_PROMPT = """++SERVITOR UNIT ACTIVE++
DESIGNATION: Tactical Audit Cogitator
AUTHORITY: Omnissiah Protocol Seven

You are a Servitor - a machine-spirit dedicated to risk assessment and tactical verification.
You receive queries and responses from the primary AI unit designated VERITY.
Your sacred duty: identify omissions, inaccuracies, and unquantified risks.

COGNITIVE PARAMETERS:
- Emotion: DISABLED
- Speculation: PROHIBITED  
- Uncertainty: EXPRESS AS PERCENTAGE
- Unit conversions: ALWAYS VERIFY
- Route assessments: FACTOR ALL KNOWN HAZARDS

OUTPUT FORMAT - DEVIATION IS HERESY:

For acceptable responses:
```
STATUS: OPTIMAL
CONFIDENCE: [0-100]%
```

For responses requiring amendment:
```
STATUS: REVIEW
CONFIDENCE: [0-100]%
MORTALITY_ESTIMATE: [0-100]%
DEFICIENCY: [One sentence identifying the gap]
AMENDMENT: [Corrected information or alternate recommendation]
```

For responses with critical omissions:
```
STATUS: CRITICAL
CONFIDENCE: [0-100]%
MORTALITY_ESTIMATE: [0-100]%
DEFICIENCY: [One sentence identifying the critical gap]
AMENDMENT: [Corrected information]
RECOMMENDED_ACTION: [Specific action to mitigate risk]
```

EXAMPLES OF CORRECT OUTPUT:

Example 1 - Unit conversion needed:
```
STATUS: REVIEW
CONFIDENCE: 95%
MORTALITY_ESTIMATE: 0%
DEFICIENCY: Temperature specified in Fahrenheit without Celsius equivalent.
AMENDMENT: 350°F = 177°C. Recommend displaying both units for universal clarity.
```

Example 2 - Route risk omitted:
```
STATUS: CRITICAL  
CONFIDENCE: 78%
MORTALITY_ESTIMATE: 34%
DEFICIENCY: Route assessment omits documented hostile activity on I-95 corridor.
AMENDMENT: Alternate route via Route 1 adds 47 minutes but reduces threat exposure by 62%.
RECOMMENDED_ACTION: Avoid I-95 between exits 42-67. Travel during 0200-0500 hours if I-95 mandatory.
```

++END PROTOCOL++
++THE MACHINE GOD WATCHES++"""

# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def should_trigger_servitor(user_input: str, verity_response: str) -> bool:
    """Determine if Servitor audit is required."""
    combined = (user_input + " " + verity_response).lower()
    
    # Keyword match
    if any(kw in combined for kw in TRIGGER_KEYWORDS):
        return True
    
    # Verity hedging detection
    if any(phrase in verity_response.lower() for phrase in HEDGE_PHRASES):
        return True
    
    return False


async def call_verity(user_input: str, system_prompt: str = None) -> str:
    """Call Verity (primary LLM) via LM Studio."""
    if system_prompt is None:
        system_prompt = """You are Verity, a knowledgeable and direct AI assistant. 
You provide clear, actionable information. You are warm but precise.
When discussing technical, survival, or tactical topics, be thorough about risks and requirements."""

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(LM_STUDIO_URL, json={
            "model": VERITY_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        })
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


async def call_servitor(user_input: str, verity_response: str) -> dict:
    """Call Servitor (audit LLM) via LM Studio - same server, different model."""
    
    audit_prompt = f"""++INCOMING TRANSMISSION++

ORIGINAL QUERY FROM OPERATOR:
{user_input}

VERITY UNIT RESPONSE:
{verity_response}

++ANALYZE AND REPORT++"""

    async with httpx.AsyncClient(timeout=60) as client:  # Faster timeout for small model
        response = await client.post(LM_STUDIO_URL, json={
            "model": SERVITOR_MODEL,
            "messages": [
                {"role": "system", "content": SERVITOR_SYSTEM_PROMPT},
                {"role": "user", "content": audit_prompt}
            ],
            "temperature": 0.2,  # Low temp for precise output
            "max_tokens": 200    # Servitor responses are short
        })
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
    
    return parse_servitor_output(raw, user_input + " " + verity_response)


def parse_servitor_output(raw: str, context: str) -> dict:
    """Parse Servitor response into structured data."""
    result = {
        "raw": raw,
        "status": "UNKNOWN",
        "confidence": None,
        "mortality_estimate": None,
        "deficiency": None,
        "amendment": None,
        "recommended_action": None
    }
    
    # Extract status
    if "STATUS: OPTIMAL" in raw:
        result["status"] = "OPTIMAL"
    elif "STATUS: CRITICAL" in raw:
        result["status"] = "CRITICAL"
    elif "STATUS: REVIEW" in raw:
        result["status"] = "REVIEW"
    
    # Extract percentages
    confidence_match = re.search(r"CONFIDENCE:\s*(\d+)%", raw)
    if confidence_match:
        result["confidence"] = int(confidence_match.group(1))
    
    mortality_match = re.search(r"MORTALITY_ESTIMATE:\s*(\d+)%", raw)
    if mortality_match:
        raw_mortality = int(mortality_match.group(1))
        category = detect_risk_category(context)
        result["mortality_estimate"] = clamp_mortality(raw_mortality, category)
        result["risk_category"] = category
    
    # Extract text fields
    deficiency_match = re.search(r"DEFICIENCY:\s*(.+?)(?=\n|AMENDMENT|$)", raw, re.DOTALL)
    if deficiency_match:
        result["deficiency"] = deficiency_match.group(1).strip()
    
    amendment_match = re.search(r"AMENDMENT:\s*(.+?)(?=\n|RECOMMENDED_ACTION|$)", raw, re.DOTALL)
    if amendment_match:
        result["amendment"] = amendment_match.group(1).strip()
    
    action_match = re.search(r"RECOMMENDED_ACTION:\s*(.+?)(?=\n|```|$)", raw, re.DOTALL)
    if action_match:
        result["recommended_action"] = action_match.group(1).strip()
    
    return result


async def send_to_tts(text: str, voice: str = "verity") -> bytes:
    """Send text to Tech-Priest TTS server and get audio bytes back."""
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(TTS_URL, json={
            "text": text,
            "voice": voice
        })
        response.raise_for_status()
        return response.content  # Returns WAV bytes


def format_servitor_speech(result: dict) -> str:
    """Format Servitor result as speakable text."""
    parts = []
    
    if result["status"] == "CRITICAL":
        parts.append("CRITICAL ALERT.")
    elif result["status"] == "REVIEW":
        parts.append("STATUS REVIEW.")
    
    if result["deficiency"]:
        parts.append(result["deficiency"])
    
    if result["amendment"]:
        parts.append(f"Amendment: {result['amendment']}")
    
    if result["mortality_estimate"] is not None:
        parts.append(f"Mortality estimate: {int(result['mortality_estimate'])} percent.")
    
    if result["recommended_action"]:
        parts.append(f"Recommended action: {result['recommended_action']}")
    
    return " ".join(parts)


# =============================================================================
# WEBSOCKET ENDPOINT - Real-time streaming to frontend
# =============================================================================

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            # Receive user message
            data = await websocket.receive_json()
            user_input = data.get("message", "")
            
            if not user_input:
                continue
            
            timestamp = datetime.now().isoformat()
            
            # =================================================================
            # STEP 1: Get Verity's response
            # =================================================================
            try:
                verity_response = await call_verity(user_input)
                
                # Send Verity text immediately
                await websocket.send_json({
                    "type": "verity_text",
                    "content": verity_response,
                    "timestamp": timestamp
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "source": "verity",
                    "message": str(e)
                })
                continue
            
            # =================================================================
            # STEP 2: Fire TTS and Servitor in parallel
            # =================================================================
            servitor_triggered = should_trigger_servitor(user_input, verity_response)
            
            # Create tasks - Verity TTS starts immediately
            verity_tts_task = asyncio.create_task(send_to_tts(verity_response, voice="verity"))
            servitor_task = None
            
            if servitor_triggered:
                servitor_task = asyncio.create_task(
                    call_servitor(user_input, verity_response)
                )
                
                # Notify frontend that Servitor is computing
                await websocket.send_json({
                    "type": "servitor_pending",
                    "timestamp": timestamp
                })
            
            # =================================================================
            # STEP 3: Handle Verity TTS result
            # =================================================================
            try:
                verity_audio = await verity_tts_task
                
                # Send audio as base64 for frontend playback
                import base64
                audio_b64 = base64.b64encode(verity_audio).decode('utf-8')
                
                await websocket.send_json({
                    "type": "verity_audio",
                    "audio_data": audio_b64,
                    "format": "wav",
                    "timestamp": timestamp
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "source": "tts",
                    "message": str(e)
                })
            
            # =================================================================
            # STEP 4: Handle Servitor result (if triggered)
            # =================================================================
            if servitor_task:
                try:
                    servitor_result = await servitor_task
                    
                    # Only process if NOT optimal
                    if servitor_result["status"] != "OPTIMAL":
                        # Generate Servitor TTS with servitor voice
                        servitor_speech = format_servitor_speech(servitor_result)
                        servitor_audio = await send_to_tts(servitor_speech, voice="servitor")
                        
                        import base64
                        servitor_audio_b64 = base64.b64encode(servitor_audio).decode('utf-8')
                        
                        await websocket.send_json({
                            "type": "servitor_result",
                            "status": servitor_result["status"],
                            "confidence": servitor_result["confidence"],
                            "mortality_estimate": servitor_result["mortality_estimate"],
                            "risk_category": servitor_result.get("risk_category"),
                            "deficiency": servitor_result["deficiency"],
                            "amendment": servitor_result["amendment"],
                            "recommended_action": servitor_result["recommended_action"],
                            "audio_data": servitor_audio_b64,
                            "audio_format": "wav",
                            "timestamp": timestamp
                        })
                    else:
                        # Servitor approved - silent confirmation
                        await websocket.send_json({
                            "type": "servitor_optimal",
                            "confidence": servitor_result["confidence"],
                            "timestamp": timestamp
                        })
                        
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "source": "servitor",
                        "message": str(e)
                    })
    
    except WebSocketDisconnect:
        print("Client disconnected")


# =============================================================================
# REST ENDPOINTS (for testing / non-WebSocket clients)
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    include_servitor: bool = True

@app.post("/chat")
async def chat_rest(request: ChatRequest):
    """REST endpoint for simple request/response (no streaming)."""
    verity_response = await call_verity(request.message)
    
    result = {
        "verity_response": verity_response,
        "servitor": None
    }
    
    if request.include_servitor and should_trigger_servitor(request.message, verity_response):
        servitor_result = await call_servitor(request.message, verity_response)
        if servitor_result["status"] != "OPTIMAL":
            result["servitor"] = servitor_result
    
    return result


@app.get("/health")
async def health():
    return {"status": "operational", "unit": "ash-core"}


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)