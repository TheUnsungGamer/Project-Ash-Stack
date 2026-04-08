from io import BytesIO
from pathlib import Path
import os
import time
import uuid
import tempfile
import traceback
import wave

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from piper import PiperVoice
from pydantic import BaseModel, Field
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range


# =========================
# APP INIT
# =========================
app = FastAPI(title="Tech Priest TTS (Piper -> RVC Bridge -> Dual Voice)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# PIPER CONFIG
# =========================
VOICE_MODEL_PATH = Path(__file__).parent / "models" / "en_GB-jenny_dioco-medium.onnx"

if not VOICE_MODEL_PATH.exists():
    raise RuntimeError(f"Piper model not found: {VOICE_MODEL_PATH}")

voice = PiperVoice.load(str(VOICE_MODEL_PATH))


# =========================
# RVC BRIDGE CONFIG
# =========================
BRIDGE_INPUT   = Path(r"C:\rvc_bridge\input")
BRIDGE_OUTPUT  = Path(r"C:\rvc_bridge\output")
BRIDGE_TIMEOUT = 30

BRIDGE_INPUT.mkdir(parents=True, exist_ok=True)
BRIDGE_OUTPUT.mkdir(parents=True, exist_ok=True)


# =========================
# REQUEST MODEL
# =========================
class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str = Field(default="verity")  # "verity" or "servitor"


# =========================
# PIPER SYNTHESIS
# =========================
def get_piper_sample_rate() -> int:
    config = getattr(voice, "config", None)
    sample_rate = getattr(config, "sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate
    return 22050


def run_piper_synthesize(text: str, wav_file) -> None:
    result = voice.synthesize(text)
    wrote_audio = False

    for chunk in result:
        audio_bytes = (
            getattr(chunk, "audio_int16_bytes", None)
            or getattr(chunk, "audio_bytes", None)
        )
        if audio_bytes:
            wav_file.writeframes(audio_bytes)
            wrote_audio = True
            continue

        audio = getattr(chunk, "audio", None)
        if audio is not None:
            if isinstance(audio, bytes):
                wav_file.writeframes(audio)
                wrote_audio = True
                continue
            if hasattr(audio, "tobytes"):
                wav_file.writeframes(audio.tobytes())
                wrote_audio = True
                continue

    if not wrote_audio:
        raise RuntimeError("Piper synth returned no writable audio chunks.")


def synthesize_piper_wav_bytes(text: str) -> bytes:
    buffer = BytesIO()
    try:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(get_piper_sample_rate())
            run_piper_synthesize(text, wav_file)
    except Exception as exc:
        raise RuntimeError(f"Piper synthesis failed: {exc}") from exc

    wav_bytes = buffer.getvalue()
    if not wav_bytes:
        raise RuntimeError("Piper returned empty WAV bytes.")
    return wav_bytes


# =========================
# RVC CONVERSION (FILE BRIDGE)
# =========================
def apply_rvc_conversion(input_wav_bytes: bytes, voice_type: str = "verity") -> bytes:
    if not input_wav_bytes:
        raise RuntimeError("Empty WAV passed to RVC.")

    job_id = uuid.uuid4().hex
    
    # Prefix with servitor_ if it's the servitor voice
    if voice_type == "servitor":
        filename = f"servitor_{job_id}.wav"
    else:
        filename = f"{job_id}.wav"
    
    in_path  = BRIDGE_INPUT  / filename
    out_path = BRIDGE_OUTPUT / filename

    try:
        in_path.write_bytes(input_wav_bytes)

        deadline = time.time() + BRIDGE_TIMEOUT
        while time.time() < deadline:
            if out_path.exists() and out_path.stat().st_size > 0:
                return out_path.read_bytes()
            time.sleep(0.25)

        raise RuntimeError(
            f"RVC bridge timed out after {BRIDGE_TIMEOUT}s. "
            "Is verity_watcher.py running?"
        )
    finally:
        for p in (in_path, out_path):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass


# =========================
# VERITY FX (warm, intimate)
# =========================
def apply_verity_effect(wav_bytes: bytes) -> bytes:
    try:
        audio = AudioSegment.from_file(BytesIO(wav_bytes), format="wav")
    except Exception as exc:
        raise RuntimeError(f"Could not load WAV: {exc}") from exc

    audio = audio.set_channels(1)
    audio = audio.high_pass_filter(150)

    audio = compress_dynamic_range(
        audio,
        threshold=-20.0,
        ratio=4.0,
        attack=5.0,
        release=50.0,
    )

    presence = audio.high_pass_filter(2500).low_pass_filter(4500) + 5
    audio = audio.overlay(presence)

    reflection = audio - 22
    audio = audio.overlay(reflection, position=12)

    original_rate = audio.frame_rate
    audio = audio._spawn(
        audio.raw_data,
        overrides={"frame_rate": int(original_rate * 1.012)},
    ).set_frame_rate(original_rate)

    audio = audio.normalize(headroom=1.0)

    out = BytesIO()
    audio.export(out, format="wav")
    return out.getvalue()


# =========================
# SERVITOR FX (cold, mechanical, vox-distorted)
# =========================
def apply_servitor_effect(wav_bytes: bytes) -> bytes:
    try:
        audio = AudioSegment.from_file(BytesIO(wav_bytes), format="wav")
    except Exception as exc:
        raise RuntimeError(f"Could not load WAV: {exc}") from exc

    audio = audio.set_channels(1)
    
    # Harsher high-pass for that thin vox-caster sound
    audio = audio.high_pass_filter(300)
    audio = audio.low_pass_filter(3500)

    # Heavy compression for flat, mechanical delivery
    audio = compress_dynamic_range(
        audio,
        threshold=-15.0,
        ratio=8.0,
        attack=2.0,
        release=30.0,
    )

    # Add some grit/distortion by boosting mids
    mid_boost = audio.high_pass_filter(800).low_pass_filter(2000) + 8
    audio = audio.overlay(mid_boost)

    # Slight robotic pitch warble
    original_rate = audio.frame_rate
    audio = audio._spawn(
        audio.raw_data,
        overrides={"frame_rate": int(original_rate * 0.98)},
    ).set_frame_rate(original_rate)

    # Short metallic echo
    echo = audio - 18
    audio = audio.overlay(echo, position=25)

    audio = audio.normalize(headroom=0.5)

    out = BytesIO()
    audio.export(out, format="wav")
    return out.getvalue()


# =========================
# ROUTES
# =========================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pipeline": "Piper -> RVC Bridge -> Dual Voice FX",
        "voices": ["verity", "servitor"],
        "voice_model": VOICE_MODEL_PATH.name,
        "bridge_input": str(BRIDGE_INPUT),
        "bridge_output": str(BRIDGE_OUTPUT),
        "bridge_timeout": BRIDGE_TIMEOUT,
    }


@app.post("/tts")
async def tts(payload: TtsRequest):
    try:
        voice_type = payload.voice.lower()
        
        # Generate base audio with Piper
        piper_audio = synthesize_piper_wav_bytes(payload.text)
        
        # Send through RVC bridge (filename prefix triggers correct voice)
        rvc_audio = apply_rvc_conversion(piper_audio, voice_type)
        
        # Apply voice-specific effects
        if voice_type == "servitor":
            final_audio = apply_servitor_effect(rvc_audio)
            filename = "servitor.wav"
        else:
            final_audio = apply_verity_effect(rvc_audio)
            filename = "verity.wav"

        return Response(
            content=final_audio,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


# =========================
# DIRECT ENDPOINT FOR SERVITOR (convenience)
# =========================
@app.post("/tts/servitor")
async def tts_servitor(payload: TtsRequest):
    payload.voice = "servitor"
    return await tts(payload)


@app.post("/tts/verity")
async def tts_verity(payload: TtsRequest):
    payload.voice = "verity"
    return await tts(payload)