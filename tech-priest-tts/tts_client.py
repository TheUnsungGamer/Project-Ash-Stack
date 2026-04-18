import base64
import httpx

ASH_TTS_SERVER_URL = "http://127.0.0.1:8000/tts"


async def fetch_voice_audio_as_base64(text: str, voice: str = "verity") -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(ASH_TTS_SERVER_URL, json={"text": text, "voice": voice})
        response.raise_for_status()
        return base64.b64encode(response.content).decode("utf-8")