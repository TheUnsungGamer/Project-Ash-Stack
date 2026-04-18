import asyncio
import uuid
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from verity_llm import ask_verity, servitor_audit_is_warranted
from servitor_audit import run_servitor_audit, build_servitor_speakable_text
from tts_client import fetch_voice_audio_as_base64

app = FastAPI(title="Project Ash — Core WebSocket Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/chat")
async def handle_websocket_chat_session(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        while True:
            incoming = await websocket.receive_json()
            user_input: str = incoming.get("message", "").strip()

            if not user_input:
                continue

            # Client can cancel a running cycle by sending { type: "cancel" }
            if incoming.get("type") == "cancel":
                continue

            request_id = uuid.uuid4().hex
            timestamp = datetime.now().isoformat()

            await websocket.send_json({
                "type": "request_accepted",
                "request_id": request_id,
                "timestamp": timestamp,
            })

            # ── Step 1: Verity responds ───────────────────────────────────────
            try:
                verity_response = await ask_verity(user_input)
            except Exception as exc:
                await websocket.send_json({
                    "type": "error",
                    "source": "verity",
                    "message": str(exc),
                })
                continue

            await websocket.send_json({
                "type": "verity_text",
                "content": verity_response,
                "request_id": request_id,
                "timestamp": timestamp,
            })

            # ── Step 2: Verity TTS + Servitor audit fire concurrently ─────────
            audit_is_needed = servitor_audit_is_warranted(user_input, verity_response)

            verity_tts_task = asyncio.create_task(
                fetch_voice_audio_as_base64(verity_response, voice="verity")
            )
            servitor_audit_task = (
                asyncio.create_task(run_servitor_audit(user_input, verity_response))
                if audit_is_needed
                else None
            )

            if audit_is_needed:
                await websocket.send_json({
                    "type": "servitor_pending",
                    "request_id": request_id,
                    "timestamp": timestamp,
                })

            # ── Step 3: Send Verity audio, then wait for playback_complete ────
            try:
                verity_audio_b64 = await verity_tts_task
                await websocket.send_json({
                    "type": "verity_audio",
                    "audio_data": verity_audio_b64,
                    "format": "wav",
                    "request_id": request_id,
                    "timestamp": timestamp,
                })
            except Exception as exc:
                await websocket.send_json({
                    "type": "error",
                    "source": "tts",
                    "message": str(exc),
                    "request_id": request_id,
                })

            # Block until the frontend signals Verity's audio has finished.
            # Servitor's panel appears only after Verity stops speaking.
            await _wait_for_playback_complete_signal(websocket, request_id)

            # ── Step 4: Deliver Servitor audit result ─────────────────────────
            if servitor_audit_task:
                try:
                    audit_result = await servitor_audit_task

                    if audit_result["status"] == "OPTIMAL":
                        await websocket.send_json({
                            "type": "servitor_optimal",
                            "confidence": audit_result["confidence"],
                            "request_id": request_id,
                            "timestamp": timestamp,
                        })
                    else:
                        servitor_speech = build_servitor_speakable_text(audit_result)
                        servitor_audio_b64 = await fetch_voice_audio_as_base64(
                            servitor_speech, voice="servitor"
                        )
                        await websocket.send_json({
                            "type": "servitor_result",
                            "status": audit_result["status"],
                            "confidence": audit_result["confidence"],
                            "mortality_estimate": audit_result["mortality_estimate"],
                            "risk_category": audit_result.get("risk_category"),
                            "deficiency": audit_result["deficiency"],
                            "amendment": audit_result["amendment"],
                            "recommended_action": audit_result["recommended_action"],
                            "audio_data": servitor_audio_b64,
                            "audio_format": "wav",
                            "request_id": request_id,
                            "timestamp": timestamp,
                        })
                except Exception as exc:
                    await websocket.send_json({
                        "type": "error",
                        "source": "servitor",
                        "message": str(exc),
                        "request_id": request_id,
                    })

    except WebSocketDisconnect:
        pass


async def _wait_for_playback_complete_signal(websocket: WebSocket, expected_request_id: str) -> None:
    """
    Drains incoming WebSocket frames until the frontend sends playback_complete
    for this cycle's request_id, or until the connection closes.
    Non-matching frames (e.g. a new chat message arriving) are discarded here —
    the outer loop handles them next iteration.
    """
    try:
        while True:
            frame = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
            if (
                frame.get("type") == "playback_complete"
                and frame.get("request_id") == expected_request_id
            ):
                return
    except (asyncio.TimeoutError, Exception):
        # Timeout or disconnect — release anyway so the server never hangs.
        return


class RestChatRequest(BaseModel):
    message: str
    include_servitor: bool = True


@app.post("/chat")
async def handle_rest_chat_request(request: RestChatRequest) -> dict[str, object]:
    verity_response = await ask_verity(request.message)
    payload: dict[str, object] = {"verity_response": verity_response, "servitor": None}

    if request.include_servitor and servitor_audit_is_warranted(request.message, verity_response):
        audit_result = await run_servitor_audit(request.message, verity_response)
        if audit_result["status"] != "OPTIMAL":
            payload["servitor"] = audit_result

    return payload


@app.get("/health")
async def get_server_health() -> dict[str, str]:
    return {"status": "operational", "unit": "ash-core"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)