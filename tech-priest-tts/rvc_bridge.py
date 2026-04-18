import time
import uuid
from pathlib import Path

RVC_BRIDGE_INPUT_DIR  = Path(r"C:\rvc_bridge\input")
RVC_BRIDGE_OUTPUT_DIR = Path(r"C:\rvc_bridge\output")
RVC_BRIDGE_TIMEOUT_SECONDS = 30

RVC_BRIDGE_INPUT_DIR.mkdir(parents=True, exist_ok=True)
RVC_BRIDGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def convert_wav_bytes_through_rvc(input_wav_bytes: bytes, voice_name: str = "verity") -> bytes:
    """
    Drops a WAV file into the RVC bridge input directory and polls for the
    converted output. The watcher script (verity_watcher.py) running alongside
    RVC picks up the file and writes the result to the output directory.

    voice_name "servitor" prefixes the filename so the watcher routes it to
    the correct RVC model.
    """
    if not input_wav_bytes:
        raise RuntimeError("Cannot send empty WAV bytes to RVC bridge.")

    job_id = uuid.uuid4().hex
    filename = f"servitor_{job_id}.wav" if voice_name == "servitor" else f"{job_id}.wav"

    input_path  = RVC_BRIDGE_INPUT_DIR  / filename
    output_path = RVC_BRIDGE_OUTPUT_DIR / filename

    try:
        input_path.write_bytes(input_wav_bytes)

        deadline = time.time() + RVC_BRIDGE_TIMEOUT_SECONDS
        while time.time() < deadline:
            if output_path.exists() and output_path.stat().st_size > 0:
                return output_path.read_bytes()
            time.sleep(0.25)

        raise RuntimeError(
            f"RVC bridge timed out after {RVC_BRIDGE_TIMEOUT_SECONDS}s — "
            "is verity_watcher.py running?"
        )
    finally:
        for path in (input_path, output_path):
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass