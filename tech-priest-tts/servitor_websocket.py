"""
Project Ash - WebSocket Backend (v3 - Hardened + Accurate Mortality)
Sequential Verity + Servitor processing with state-locked handshake.

Changes from v2:
- Mortality scoring is now fully deterministic (no LLM number generation)
- Mortality computed from user input only — Verity advice excluded
- TTS timeout decoupled from playback gate timer
- Servitor prompt no longer asks for MORTALITY_ESTIMATE (we supply it)
- playback gate timeout extended, TTS timeout failures non-blocking
"""

import asyncio
import json
import httpx
import re
import base64
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime

# Mortality engine — deterministic, grounded in real data
from mortality import compute_mortality, MortalityResult

app = FastAPI(title="Project Ash - Verity & Servitor (v3)")

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

LM_STUDIO_URL   = "http://127.0.0.1:1234/v1/chat/completions"
TTS_URL         = "http://127.0.0.1:8000/tts"

VERITY_MODEL    = "mistralai/mistral-7b-instruct-v0.3"
SERVITOR_MODEL  = "qwen2.5-0.5b-instruct"

VERITY_TIMEOUT   = 120
SERVITOR_TIMEOUT = 20   # Raised from 10 — Qwen after Verity may need headroom
TTS_TIMEOUT      = 120

# =============================================================================
# TRIGGER KEYWORDS
# =============================================================================

TRIGGER_KEYWORDS = {
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

HEDGE_PHRASES = [
    "i'm not sure", "i think", "might be", "possibly", "perhaps",
    "you may want to verify", "i believe", "it could be", "not certain",
    "double check", "verify this",
]

# =============================================================================
# SERVITOR SYSTEM PROMPT
# NOTE: MORTALITY_ESTIMATE removed — we compute it deterministically.
# Servitor focuses on deficiency detection and amendment only.
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
DEFICIENCY: [One sentence identifying the gap]
AMENDMENT: [Corrected information or alternate recommendation]
```

For responses with critical omissions:
```
STATUS: CRITICAL
CONFIDENCE: [0-100]%
DEFICIENCY: [One sentence identifying the critical gap]
AMENDMENT: [Corrected information]
RECOMMENDED_ACTION: [Specific action to mitigate risk]
```

++END PROTOCOL++
++THE MACHINE GOD WATCHES++"""

# =============================================================================
# CORE INFERENCE
# =============================================================================

def should_trigger_servitor(user_input: str, verity_response: str) -> bool:
    combined = (user_input + " " + verity_response).lower()
    if any(kw in combined for kw in TRIGGER_KEYWORDS):
        return True
    if any(ph in verity_response.lower() for ph in HEDGE_PHRASES):
        return True
    return False


async def call_verity(user_input: str, system_prompt: str = None) -> str:
    if system_prompt is None:
        system_prompt = (
            "You are Verity, a knowledgeable and direct AI assistant. "
            "You provide clear, actionable information. You are warm but precise. "
            "When discussing technical, survival, or tactical topics, be thorough "
            "about risks and requirements."
        )

    combined_prompt = f"{system_prompt}\n\nUser: {user_input}"

    try:
        async with httpx.AsyncClient(timeout=VERITY_TIMEOUT) as client:
            response = await client.post(LM_STUDIO_URL, json={
                "model": VERITY_MODEL,
                "messages": [{"role": "user", "content": combined_prompt}],
                "temperature": 0.7,
                "max_tokens": 1024,
            })
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Verity timed out after {VERITY_TIMEOUT}s") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Verity HTTP {e.response.status_code}") from e


async def call_servitor(user_input: str, verity_response: str) -> dict:
    combined_prompt = (
        f"{SERVITOR_SYSTEM_PROMPT}\n\n"
        f"++INCOMING TRANSMISSION++\n\n"
        f"ORIGINAL QUERY FROM OPERATOR:\n{user_input}\n\n"
        f"VERITY UNIT RESPONSE:\n{verity_response}\n\n"
        f"++ANALYZE AND REPORT++"
    )

    try:
        async with httpx.AsyncClient(timeout=SERVITOR_TIMEOUT) as client:
            response = await client.post(LM_STUDIO_URL, json={
                "model": SERVITOR_MODEL,
                "messages": [{"role": "user", "content": combined_prompt}],
                "temperature": 0.2,
                "max_tokens": 200,
            })
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Servitor timed out after {SERVITOR_TIMEOUT}s") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Servitor HTTP {e.response.status_code}") from e

    return parse_servitor_output(raw)


def parse_servitor_output(raw: str) -> dict:
    result = {
        "raw": raw,
        "status": "UNKNOWN",
        "confidence": None,
        "deficiency": None,
        "amendment": None,
        "recommended_action": None,
    }

    if "STATUS: OPTIMAL" in raw:
        result["status"] = "OPTIMAL"
    elif "STATUS: CRITICAL" in raw:
        result["status"] = "CRITICAL"
    elif "STATUS: REVIEW" in raw:
        result["status"] = "REVIEW"

    m = re.search(r"CONFIDENCE:\s*(\d+)%", raw)
    if m:
        result["confidence"] = int(m.group(1))

    m = re.search(r"DEFICIENCY:\s*(.+?)(?=\nAMENDMENT|\nRECOMMENDED_ACTION|```|$)", raw, re.DOTALL)
    if m:
        result["deficiency"] = m.group(1).strip()

    m = re.search(r"AMENDMENT:\s*(.+?)(?=\nRECOMMENDED_ACTION|```|$)", raw, re.DOTALL)
    if m:
        result["amendment"] = m.group(1).strip()

    m = re.search(r"RECOMMENDED_ACTION:\s*(.+?)(?=```|$)", raw, re.DOTALL)
    if m:
        result["recommended_action"] = m.group(1).strip()

    return result


async def send_to_tts(text: str, voice: str = "verity") -> bytes:
    try:
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
            response = await client.post(TTS_URL, json={"text": text, "voice": voice})
            response.raise_for_status()
            return response.content
    except httpx.TimeoutException as e:
        raise RuntimeError(f"TTS timed out after {TTS_TIMEOUT}s") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"TTS HTTP {e.response.status_code}") from e


def format_servitor_speech(servitor: dict, mortality: MortalityResult) -> str:
    """
    Build Servitor speech from parsed output + deterministic mortality score.
    Mortality number comes from our engine, not the LLM.
    """
    parts = []

    if servitor["status"] == "CRITICAL":
        parts.append(
            "Prime Directive override. Interrupt authorized. "
            "Critical deficiency detected. Verity unit response flagged for immediate correction."
        )
    elif servitor["status"] == "REVIEW":
        parts.append(
            "Attention. Supplemental analysis required. Servitor unit transmitting."
        )

    if servitor["deficiency"]:
        parts.append(f"Deficiency identified. {servitor['deficiency']}")

    if servitor["amendment"]:
        parts.append(f"Correction follows. {servitor['amendment']}")

    # Mortality from our deterministic engine
    mort = int(mortality.score)
    if mort >= 50:
        parts.append(
            f"Mortality estimate: {mort} percent. {mortality.risk_label}. "
            "Operator survival probability is low. Immediate action required."
        )
    elif mort >= 20:
        parts.append(
            f"Mortality estimate: {mort} percent. Risk level {mortality.risk_label.lower()}."
        )
    elif mort >= 5:
        parts.append(f"Mortality estimate: {mort} percent. Risk level {mortality.risk_label.lower()}.")

    if servitor["recommended_action"]:
        parts.append(f"Recommended action. {servitor['recommended_action']}")

    parts.append("Servitor unit standing by.")
    return " ".join(parts)


# =============================================================================
# WEBSOCKET — per-connection state
# =============================================================================

_active_tasks:    dict[int, asyncio.Task]  = {}
_playback_events: dict[int, asyncio.Event] = {}


async def _process_cycle(
    websocket: WebSocket,
    user_input: str,
    request_id: str,
    timestamp: str,
    playback_event: asyncio.Event,
) -> None:
    """
    Execution order (sequential — required for single 8GB VRAM):
      1. call_verity()
      2. compute_mortality()          ← deterministic, instant
      3. send verity_text + mortality frame
      4. send_to_tts(verity)
      5. send verity_audio frame
      6. WAIT for playback_complete   ← state-locked handshake
      7. call_servitor()
      8. send_to_tts(servitor speech)
      9. send servitor_result frame
    """

    # ------------------------------------------------------------------
    # STEP 1: Verity inference
    # ------------------------------------------------------------------
    try:
        verity_response = await call_verity(user_input)
    except asyncio.CancelledError:
        return
    except Exception as e:
        await websocket.send_json({
            "type": "error", "source": "verity",
            "request_id": request_id, "message": str(e),
        })
        return

    # ------------------------------------------------------------------
    # STEP 2: Deterministic mortality scoring (instant, no VRAM)
    # ------------------------------------------------------------------
    mortality = compute_mortality(user_input, verity_response)

    # ------------------------------------------------------------------
    # STEP 3: Send Verity text + mortality to frontend
    # ------------------------------------------------------------------
    try:
        await websocket.send_json({
            "type": "verity_text",
            "content": verity_response,
            "mortality": {
                "score":         mortality.score,
                "risk_label":    mortality.risk_label,
                "category":      mortality.category,
                "sub_category":  mortality.sub_category,
                "confidence":    mortality.confidence,
                "events": [
                    {"label": e.label, "delta": e.delta}
                    for e in mortality.events
                ],
            },
            "request_id": request_id,
            "timestamp":  timestamp,
        })
    except asyncio.CancelledError:
        return

    # ------------------------------------------------------------------
    # STEP 4: Verity TTS
    # ------------------------------------------------------------------
    verity_audio = None
    try:
        verity_audio = await send_to_tts(verity_response, voice="verity")
    except asyncio.CancelledError:
        return
    except Exception as e:
        # TTS failure is non-blocking — log and continue to Servitor
        await websocket.send_json({
            "type": "error", "source": "tts_verity",
            "request_id": request_id, "message": str(e),
        })

    # ------------------------------------------------------------------
    # STEP 5: Send Verity audio
    # ------------------------------------------------------------------
    if verity_audio is not None:
        try:
            await websocket.send_json({
                "type": "verity_audio",
                "audio_data": base64.b64encode(verity_audio).decode("utf-8"),
                "format": "wav",
                "request_id": request_id,
                "timestamp":  timestamp,
            })
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # STEP 6: Playback gate — only if Servitor is needed
    # TTS timeout fix: gate timer starts AFTER audio is sent, not before.
    # Frontend must send playback_complete when audio finishes playing.
    # Timeout is generous (90s) to cover long Verity responses.
    # ------------------------------------------------------------------
    servitor_triggered = should_trigger_servitor(user_input, verity_response)

    if servitor_triggered:
        try:
            await websocket.send_json({
                "type": "servitor_pending",
                "request_id": request_id,
                "timestamp":  timestamp,
            })
        except asyncio.CancelledError:
            return

        # Wait for frontend playback_complete signal
        # Timer starts NOW — after audio was sent — not during TTS generation
        try:
            await asyncio.wait_for(playback_event.wait(), timeout=90.0)
        except asyncio.TimeoutError:
            pass  # Proceed anyway — audio may have finished without confirmation
        except asyncio.CancelledError:
            return

        # ------------------------------------------------------------------
        # STEP 7: Servitor inference
        # ------------------------------------------------------------------
        try:
            servitor_result = await call_servitor(user_input, verity_response)
        except asyncio.CancelledError:
            return
        except Exception as e:
            await websocket.send_json({
                "type": "error", "source": "servitor",
                "request_id": request_id, "message": str(e),
            })
            return

        # ------------------------------------------------------------------
        # STEP 8 + 9: Servitor TTS + send result
        # ------------------------------------------------------------------
        if servitor_result["status"] == "OPTIMAL":
            try:
                await websocket.send_json({
                    "type": "servitor_optimal",
                    "confidence": servitor_result["confidence"],
                    "mortality": {
                        "score":      mortality.score,
                        "risk_label": mortality.risk_label,
                        "category":   mortality.category,
                        "confidence": mortality.confidence,
                    },
                    "request_id": request_id,
                    "timestamp":  timestamp,
                })
            except asyncio.CancelledError:
                return
        else:
            servitor_speech = format_servitor_speech(servitor_result, mortality)

            servitor_audio = None
            try:
                servitor_audio = await send_to_tts(servitor_speech, voice="servitor")
            except asyncio.CancelledError:
                return
            except Exception as e:
                await websocket.send_json({
                    "type": "error", "source": "tts_servitor",
                    "request_id": request_id, "message": str(e),
                })

            try:
                await websocket.send_json({
                    "type": "servitor_result",
                    "status":             servitor_result["status"],
                    "confidence":         servitor_result["confidence"],
                    "deficiency":         servitor_result["deficiency"],
                    "amendment":          servitor_result["amendment"],
                    "recommended_action": servitor_result["recommended_action"],
                    "mortality": {
                        "score":         mortality.score,
                        "risk_label":    mortality.risk_label,
                        "category":      mortality.category,
                        "sub_category":  mortality.sub_category,
                        "confidence":    mortality.confidence,
                        "events": [
                            {"label": e.label, "delta": e.delta}
                            for e in mortality.events
                        ],
                    },
                    "audio_data":   base64.b64encode(servitor_audio).decode("utf-8")
                                    if servitor_audio else None,
                    "audio_format": "wav",
                    "request_id":   request_id,
                    "timestamp":    timestamp,
                })
            except asyncio.CancelledError:
                return


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    conn_id = id(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            user_input = data.get("message", "").strip()

            if data.get("type") == "playback_complete":
                event = _playback_events.get(conn_id)
                if event:
                    event.set()
                continue

            if not user_input:
                continue

            # Cancel any in-flight cycle
            existing = _active_tasks.get(conn_id)
            if existing and not existing.done():
                existing.cancel()
                try:
                    await existing
                except (asyncio.CancelledError, Exception):
                    pass

            request_id = str(uuid.uuid4())
            timestamp  = datetime.now().isoformat()

            await websocket.send_json({
                "type": "request_accepted",
                "request_id": request_id,
                "timestamp":  timestamp,
            })

            playback_event = asyncio.Event()
            _playback_events[conn_id] = playback_event
            task = asyncio.create_task(
                _process_cycle(websocket, user_input, request_id, timestamp, playback_event)
            )
            _active_tasks[conn_id] = task

    except WebSocketDisconnect:
        t = _active_tasks.pop(conn_id, None)
        if t and not t.done(): t.cancel()
        _playback_events.pop(conn_id, None)
        print(f"Client {conn_id} disconnected.")

    except Exception as e:
        t = _active_tasks.pop(conn_id, None)
        if t and not t.done(): t.cancel()
        _playback_events.pop(conn_id, None)
        print(f"WebSocket error {conn_id}: {e}")


# =============================================================================
# REST ENDPOINTS
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    include_servitor: bool = True

@app.post("/chat")
async def chat_rest(request: ChatRequest):
    request_id = str(uuid.uuid4())

    try:
        verity_response = await call_verity(request.message)
    except Exception as e:
        return {"error": str(e), "request_id": request_id}

    mortality = compute_mortality(request.message, verity_response)

    result = {
        "request_id":      request_id,
        "verity_response": verity_response,
        "mortality": {
            "score":        mortality.score,
            "risk_label":   mortality.risk_label,
            "category":     mortality.category,
            "sub_category": mortality.sub_category,
            "confidence":   mortality.confidence,
        },
        "servitor": None,
    }

    if request.include_servitor and should_trigger_servitor(request.message, verity_response):
        try:
            servitor_result = await call_servitor(request.message, verity_response)
            if servitor_result["status"] != "OPTIMAL":
                result["servitor"] = servitor_result
        except Exception as e:
            result["servitor_error"] = str(e)

    return result


@app.get("/health")
async def health():
    return {"status": "operational", "unit": "ash-core-v3"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)