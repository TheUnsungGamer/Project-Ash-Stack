from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from piper_synthesizer import synthesize_text_to_wav_bytes, PIPER_VOICE_MODEL_PATH
from rvc_bridge import convert_wav_bytes_through_rvc, RVC_BRIDGE_INPUT_DIR, RVC_BRIDGE_OUTPUT_DIR, RVC_BRIDGE_TIMEOUT_SECONDS
from voice_fx import apply_verity_voice_effects, apply_servitor_voice_effects

import traceback

app = FastAPI(title="Project Ash — TTS Server (Piper → RVC → Voice FX)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str = Field(default="verity")


@app.post("/tts")
async def synthesize_voice_audio(payload: TtsRequest) -> Response:
    try:
        voice_name = payload.voice.lower()

        piper_wav = synthesize_text_to_wav_bytes(payload.text)
        rvc_wav   = convert_wav_bytes_through_rvc(piper_wav, voice_name)

        if voice_name == "servitor":
            final_wav = apply_servitor_voice_effects(rvc_wav)
            output_filename = "servitor.wav"
        else:
            final_wav = apply_verity_voice_effects(rvc_wav)
            output_filename = "verity.wav"

        return Response(
            content=final_wav,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'inline; filename="{output_filename}"',
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/tts/verity")
async def synthesize_verity_audio(payload: TtsRequest) -> Response:
    payload.voice = "verity"
    return await synthesize_voice_audio(payload)


@app.post("/tts/servitor")
async def synthesize_servitor_audio(payload: TtsRequest) -> Response:
    payload.voice = "servitor"
    return await synthesize_voice_audio(payload)


@app.get("/health")
async def get_tts_server_health() -> dict[str, object]:
    return {
        "status": "ok",
        "pipeline": "Piper → RVC Bridge → Voice FX",
        "voices": ["verity", "servitor"],
        "piper_model": PIPER_VOICE_MODEL_PATH.name,
        "rvc_bridge_input": str(RVC_BRIDGE_INPUT_DIR),
        "rvc_bridge_output": str(RVC_BRIDGE_OUTPUT_DIR),
        "rvc_bridge_timeout_seconds": RVC_BRIDGE_TIMEOUT_SECONDS,
    }