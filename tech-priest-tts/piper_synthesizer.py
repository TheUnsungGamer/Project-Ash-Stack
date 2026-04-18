from io import BytesIO
from pathlib import Path
import wave

from piper import PiperVoice

PIPER_VOICE_MODEL_PATH = Path(__file__).parent / "models" / "en_GB-jenny_dioco-medium.onnx"

if not PIPER_VOICE_MODEL_PATH.exists():
    raise RuntimeError(f"Piper voice model not found: {PIPER_VOICE_MODEL_PATH}")

_loaded_piper_voice = PiperVoice.load(str(PIPER_VOICE_MODEL_PATH))


def _get_piper_sample_rate() -> int:
    config = getattr(_loaded_piper_voice, "config", None)
    sample_rate = getattr(config, "sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate
    return 22050


import wave as wave_module

def _write_piper_audio_frames_to_wav(text: str, wav_file: wave_module.Wave_write) -> None:
    result = _loaded_piper_voice.synthesize(text)
    wrote_any_frames = False

    for chunk in list(result):  # type: ignore[call-overload]
        audio_bytes = (
            getattr(chunk, "audio_int16_bytes", None)
            or getattr(chunk, "audio_bytes", None)
        )
        if audio_bytes:
            wav_file.writeframes(audio_bytes)
            wrote_any_frames = True
            continue

        audio = getattr(chunk, "audio", None)
        if audio is not None:
            if isinstance(audio, bytes):
                wav_file.writeframes(audio)
                wrote_any_frames = True
                continue
            if hasattr(audio, "tobytes"):
                wav_file.writeframes(audio.tobytes())
                wrote_any_frames = True
                continue

    if not wrote_any_frames:
        raise RuntimeError("Piper returned no writable audio chunks.")


def synthesize_text_to_wav_bytes(text: str) -> bytes:
    buffer = BytesIO()
    try:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(_get_piper_sample_rate())
            _write_piper_audio_frames_to_wav(text, wav_file)
    except Exception as exc:
        raise RuntimeError(f"Piper synthesis failed: {exc}") from exc

    wav_bytes = buffer.getvalue()
    if not wav_bytes:
        raise RuntimeError("Piper returned empty WAV bytes.")
    return wav_bytes