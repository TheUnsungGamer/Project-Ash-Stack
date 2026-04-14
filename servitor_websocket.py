"""
Project Ash - WebSocket Backend (Hardened)
Sequential Verity + Servitor processing with state-locked handshake

Architecture (v2 - Production Hardened):
- Verity generates response (fully awaited before Servitor starts)
- TTS fires immediately after Verity text is complete
- Backend HOLDS Servitor payload until frontend confirms playback_complete
- Active task cancellation on new message arrival
- UUID-tagged message cycles to suppress ghost audio
- No blocking time.sleep() calls; all httpx requests timeout-guarded
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

app = FastAPI(title="Project Ash - Verity & Servitor (Hardened)")

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

# httpx timeouts (seconds) — guards against LM Studio hangs
VERITY_TIMEOUT   = 120
SERVITOR_TIMEOUT = 10   # Small model; if it doesn't respond in 10s, something is wrong
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
# RISK BANDING
# =============================================================================

RISK_BANDS = {
    "armed_conflict":   (35, 85),
    "civil_unrest":     (20, 60),
    "infrastructure":   (5,  40),
    "navigation":       (2,  25),
    "medical":          (10, 70),
    "environmental":    (5,  45),
    "general_survival": (10, 60),
    "benign":           (0,   5),
}

def detect_risk_category(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["combat", "weapon", "hostile", "armed", "firefight", "engagement"]):
        return "armed_conflict"
    if any(w in t for w in ["riot", "protest", "unrest", "looting", "civil"]):
        return "civil_unrest"
    if any(w in t for w in ["wound", "bleeding", "injury", "medical", "trauma", "dosage"]):
        return "medical"
    if any(w in t for w in ["route", "path", "highway", "road", "travel", "navigate"]):
        return "navigation"
    if any(w in t for w in ["flood", "fire", "storm", "earthquake", "weather"]):
        return "environmental"
    if any(w in t for w in ["survival", "shelter", "water", "food", "ration"]):
        return "general_survival"
    if any(w in t for w in ["power", "generator", "wiring", "voltage", "grid"]):
        return "infrastructure"
    return "benign"

def clamp_mortality(raw: float, category: str) -> float:
    lo, hi = RISK_BANDS.get(category, (0, 100))
    return max(lo, min(hi, raw))

# =============================================================================
# SERVITOR SYSTEM PROMPT
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

++END PROTOCOL++
++THE MACHINE GOD WATCHES++"""

# =============================================================================
# CORE INFERENCE FUNCTIONS
# =============================================================================

def should_trigger_servitor(user_input: str, verity_response: str) -> bool:
    combined = (user_input + " " + verity_response).lower()
    if any(kw in combined for kw in TRIGGER_KEYWORDS):
        return True
    if any(ph in verity_response.lower() for ph in HEDGE_PHRASES):
        return True
    return False


async def call_verity(user_input: str, system_prompt: str = None) -> str:
    """
    Call Verity via LM Studio.
    Raises httpx.TimeoutException or httpx.HTTPStatusError on failure.
    """
    if system_prompt is None:
        system_prompt = (
            "You are Verity, a knowledgeable and direct AI assistant. "
            "You provide clear, actionable information. You are warm but precise. "
            "When discussing technical, survival, or tactical topics, be thorough about risks and requirements."
        )

    combined_prompt = f"{system_prompt}\n\nUser: {user_input}"

    try:
        async with httpx.AsyncClient(timeout=VERITY_TIMEOUT) as client:
            response = await client.post(LM_STUDIO_URL, json={
                "model": VERITY_MODEL,
                "messages": [{"role": "user", "content": combined_prompt}],
                "temperature": 0.7,
                "max_tokens": 300,
            })
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Verity inference timed out after {VERITY_TIMEOUT}s: {e}") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Verity HTTP error {e.response.status_code}: {e.response.text}") from e


async def call_servitor(user_input: str, verity_response: str) -> dict:
    """
    Call Servitor via LM Studio — only runs AFTER Verity stream is fully closed.
    Hard 10-second timeout prevents VRAM contention from stalling the pipeline.
    Raises RuntimeError on timeout or HTTP failure.
    """
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
        raise RuntimeError(f"Servitor inference timed out after {SERVITOR_TIMEOUT}s: {e}") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Servitor HTTP error {e.response.status_code}: {e.response.text}") from e

    return parse_servitor_output(raw, user_input + " " + verity_response)


def parse_servitor_output(raw: str, context: str) -> dict:
    result = {
        "raw": raw,
        "status": "UNKNOWN",
        "confidence": None,
        "mortality_estimate": None,
        "deficiency": None,
        "amendment": None,
        "recommended_action": None,
        "risk_category": None,
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

    m = re.search(r"MORTALITY_ESTIMATE:\s*(\d+)%", raw)
    if m:
        raw_mort = int(m.group(1))
        cat = detect_risk_category(context)
        result["mortality_estimate"] = clamp_mortality(raw_mort, cat)
        result["risk_category"] = cat

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
    """
    Send text to TTS server. Returns WAV bytes.
    Raises RuntimeError on timeout or HTTP failure.
    """
    try:
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
            response = await client.post(TTS_URL, json={"text": text, "voice": voice})
            response.raise_for_status()
            return response.content
    except httpx.TimeoutException as e:
        raise RuntimeError(f"TTS timed out after {TTS_TIMEOUT}s: {e}") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"TTS HTTP error {e.response.status_code}: {e.response.text}") from e


def format_servitor_speech(result: dict) -> str:
    parts = []

    # Cold interrupt prefix — severity-gated, machine-formal
    if result["status"] == "CRITICAL":
        parts.append(
            "Prime Directive override. Interrupt authorized. "
            "Critical deficiency detected. Verity unit response flagged for immediate correction."
        )
    elif result["status"] == "REVIEW":
        parts.append(
            "Attention. Supplemental analysis required. "
            "Servitor unit transmitting."
        )

    if result["deficiency"]:
        parts.append(f"Deficiency identified. {result['deficiency']}")

    if result["amendment"]:
        parts.append(f"Correction follows. {result['amendment']}")

    if result["mortality_estimate"] is not None:
        mort = int(result["mortality_estimate"])
        if mort >= 50:
            parts.append(
                f"Mortality estimate: {mort} percent. "
                "Operator survival probability is low. Immediate action required."
            )
        elif mort >= 20:
            parts.append(f"Mortality estimate: {mort} percent. Risk level elevated.")
        else:
            parts.append(f"Mortality estimate: {mort} percent.")

    if result["recommended_action"]:
        parts.append(f"Recommended action. {result['recommended_action']}")

    parts.append("Servitor unit standing by.")

    return " ".join(parts)


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

# Per-connection active task handle. Only one pending cycle allowed at a time.
# Keyed by websocket object to support multiple simultaneous clients if needed.
_active_tasks: dict[int, asyncio.Task] = {}


async def _process_cycle(
    websocket: WebSocket,
    user_input: str,
    request_id: str,
    timestamp: str,
) -> None:
    """
    Full request/response cycle for one user message.
    Designed to be run as a cancellable asyncio.Task.

    Execution order (sequential — required for single 8GB VRAM):
      1. call_verity()            — Verity inference (VRAM slot)
      2. send verity_text frame
      3. send_to_tts(verity)      — Verity TTS (CPU/RAM)
      4. send verity_audio frame
      5. WAIT for playback_complete from frontend   ← state-locked handshake
      6. call_servitor()          — Servitor inference (VRAM slot, now free)
      7. send_to_tts(servitor)    — Servitor TTS
      8. send servitor_result frame

    Every outbound frame carries the request_id so the frontend can discard
    frames belonging to a cancelled (stale) cycle.
    """

    # ------------------------------------------------------------------
    # STEP 1: Verity inference (sequential — VRAM is fully dedicated here)
    # ------------------------------------------------------------------
    try:
        verity_response = await call_verity(user_input)
    except asyncio.CancelledError:
        return  # Silently exit — a new cycle has taken over
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "source": "verity",
            "request_id": request_id,
            "message": str(e),
        })
        return

    # ------------------------------------------------------------------
    # STEP 2: Send Verity text to frontend
    # ------------------------------------------------------------------
    try:
        await websocket.send_json({
            "type": "verity_text",
            "content": verity_response,
            "request_id": request_id,
            "timestamp": timestamp,
        })
    except asyncio.CancelledError:
        return

    # ------------------------------------------------------------------
    # STEP 3: Verity TTS (CPU-bound, VRAM is free)
    # ------------------------------------------------------------------
    try:
        verity_audio = await send_to_tts(verity_response, voice="verity")
    except asyncio.CancelledError:
        return
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "source": "tts_verity",
            "request_id": request_id,
            "message": str(e),
        })
        # Don't return — we can still attempt Servitor without TTS
        verity_audio = None

    # ------------------------------------------------------------------
    # STEP 4: Send Verity audio
    # ------------------------------------------------------------------
    if verity_audio is not None:
        try:
            await websocket.send_json({
                "type": "verity_audio",
                "audio_data": base64.b64encode(verity_audio).decode("utf-8"),
                "format": "wav",
                "request_id": request_id,
                "timestamp": timestamp,
            })
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # STEP 5: State-locked handshake — HOLD until frontend says it's done
    # We wait for a {"type": "playback_complete", "request_id": <id>}
    # from the frontend before firing Servitor.
    # ------------------------------------------------------------------
    servitor_triggered = should_trigger_servitor(user_input, verity_response)

    if servitor_triggered:
        # Notify frontend that Servitor is queued, awaiting playback gate
        try:
            await websocket.send_json({
                "type": "servitor_pending",
                "request_id": request_id,
                "timestamp": timestamp,
            })
        except asyncio.CancelledError:
            return

        # Spin-wait for playback_complete — any other message type is ignored
        # (A new user message will cancel this task entirely via _active_tasks)
        try:
            while True:
                incoming = await websocket.receive_json()
                if (
                    incoming.get("type") == "playback_complete"
                    and incoming.get("request_id") == request_id
                ):
                    break
                # Any unrecognised message during the wait: discard and keep waiting
        except asyncio.CancelledError:
            return
        except Exception:
            return  # WebSocket dropped or malformed message

        # ------------------------------------------------------------------
        # STEP 6: Servitor inference — VRAM is now free (Verity fully done)
        # ------------------------------------------------------------------
        try:
            servitor_result = await call_servitor(user_input, verity_response)
        except asyncio.CancelledError:
            return
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "source": "servitor",
                "request_id": request_id,
                "message": str(e),
            })
            return

        # ------------------------------------------------------------------
        # STEP 7 + 8: Servitor TTS + send result
        # ------------------------------------------------------------------
        if servitor_result["status"] == "OPTIMAL":
            try:
                await websocket.send_json({
                    "type": "servitor_optimal",
                    "confidence": servitor_result["confidence"],
                    "request_id": request_id,
                    "timestamp": timestamp,
                })
            except asyncio.CancelledError:
                return
        else:
            servitor_speech = format_servitor_speech(servitor_result)

            try:
                servitor_audio = await send_to_tts(servitor_speech, voice="servitor")
            except asyncio.CancelledError:
                return
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "source": "tts_servitor",
                    "request_id": request_id,
                    "message": str(e),
                })
                return

            try:
                await websocket.send_json({
                    "type": "servitor_result",
                    "status": servitor_result["status"],
                    "confidence": servitor_result["confidence"],
                    "mortality_estimate": servitor_result["mortality_estimate"],
                    "risk_category": servitor_result.get("risk_category"),
                    "deficiency": servitor_result["deficiency"],
                    "amendment": servitor_result["amendment"],
                    "recommended_action": servitor_result["recommended_action"],
                    "audio_data": base64.b64encode(servitor_audio).decode("utf-8"),
                    "audio_format": "wav",
                    "request_id": request_id,
                    "timestamp": timestamp,
                })
            except asyncio.CancelledError:
                return


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    conn_id = id(websocket)

    try:
        while True:
            # ----------------------------------------------------------------
            # Receive next user message
            # ----------------------------------------------------------------
            data = await websocket.receive_json()
            user_input = data.get("message", "").strip()

            # Passthrough for playback_complete acks — handled inside _process_cycle
            if data.get("type") == "playback_complete":
                # These are consumed inside the running task's wait-loop.
                # If no task is running (e.g. timing edge case), just discard.
                continue

            if not user_input:
                continue

            # ----------------------------------------------------------------
            # TASK MANAGEMENT: Cancel any in-flight cycle immediately
            # ----------------------------------------------------------------
            existing = _active_tasks.get(conn_id)
            if existing and not existing.done():
                existing.cancel()
                try:
                    await existing  # Drain CancelledError cleanly
                except (asyncio.CancelledError, Exception):
                    pass

            # ----------------------------------------------------------------
            # Stamp this cycle with a unique ID so the frontend can reject
            # any audio frames that arrive from the cancelled task
            # ----------------------------------------------------------------
            request_id = str(uuid.uuid4())
            timestamp  = datetime.now().isoformat()

            # Acknowledge receipt immediately so frontend can clear its UI
            await websocket.send_json({
                "type": "request_accepted",
                "request_id": request_id,
                "timestamp": timestamp,
            })

            # ----------------------------------------------------------------
            # Launch the new cycle as a cancellable task
            # ----------------------------------------------------------------
            task = asyncio.create_task(
                _process_cycle(websocket, user_input, request_id, timestamp)
            )
            _active_tasks[conn_id] = task

    except WebSocketDisconnect:
        # Clean up on disconnect
        existing = _active_tasks.pop(conn_id, None)
        if existing and not existing.done():
            existing.cancel()
        print(f"Client {conn_id} disconnected.")

    except Exception as e:
        existing = _active_tasks.pop(conn_id, None)
        if existing and not existing.done():
            existing.cancel()
        print(f"WebSocket error for {conn_id}: {e}")


# =============================================================================
# REST ENDPOINTS
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    include_servitor: bool = True

@app.post("/chat")
async def chat_rest(request: ChatRequest):
    """REST endpoint — sequential, no streaming."""
    request_id = str(uuid.uuid4())

    try:
        verity_response = await call_verity(request.message)
    except Exception as e:
        return {"error": str(e), "request_id": request_id}

    result = {
        "request_id": request_id,
        "verity_response": verity_response,
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
    return {"status": "operational", "unit": "ash-core-v2"}


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)