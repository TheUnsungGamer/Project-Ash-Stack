from io import BytesIO

from pydub import AudioSegment
from pydub.effects import compress_dynamic_range


def apply_verity_voice_effects(wav_bytes: bytes) -> bytes:
    """
    Warm, intimate voice — slight presence boost, soft room reflection,
    gentle pitch nudge upward, compressed dynamics.
    """
    try:
        audio = AudioSegment.from_file(BytesIO(wav_bytes), format="wav")
    except Exception as exc:
        raise RuntimeError(f"Could not load WAV for Verity FX: {exc}") from exc

    audio = audio.set_channels(1)
    audio = audio.high_pass_filter(150)

    audio = compress_dynamic_range(
        audio,
        threshold=-20.0,
        ratio=4.0,
        attack=5.0,
        release=50.0,
    )

    presence_band = audio.high_pass_filter(2500).low_pass_filter(4500) + 5
    audio = audio.overlay(presence_band)

    soft_reflection = audio - 22
    audio = audio.overlay(soft_reflection, position=12)

    # Subtle pitch nudge: re-stamp frame rate without resampling, then snap back
    original_rate = audio.frame_rate
    audio = audio._spawn(
        audio.raw_data,
        overrides={"frame_rate": int(original_rate * 1.012)},
    ).set_frame_rate(original_rate)

    audio = audio.normalize(headroom=1.0)

    out = BytesIO()
    audio.export(out, format="wav")
    return out.getvalue()


def apply_servitor_voice_effects(wav_bytes: bytes) -> bytes:
    """
    Cold, mechanical vox-caster — narrow frequency band, heavy compression,
    mid-range grit boost, downward pitch warp, short metallic echo.
    """
    try:
        audio = AudioSegment.from_file(BytesIO(wav_bytes), format="wav")
    except Exception as exc:
        raise RuntimeError(f"Could not load WAV for Servitor FX: {exc}") from exc

    audio = audio.set_channels(1)
    audio = audio.high_pass_filter(300)
    audio = audio.low_pass_filter(3500)

    audio = compress_dynamic_range(
        audio,
        threshold=-15.0,
        ratio=8.0,
        attack=2.0,
        release=30.0,
    )

    mid_grit_band = audio.high_pass_filter(800).low_pass_filter(2000) + 8
    audio = audio.overlay(mid_grit_band)

    # Robotic downward pitch warp
    original_rate = audio.frame_rate
    audio = audio._spawn(
        audio.raw_data,
        overrides={"frame_rate": int(original_rate * 0.98)},
    ).set_frame_rate(original_rate)

    metallic_echo = audio - 18
    audio = audio.overlay(metallic_echo, position=25)

    audio = audio.normalize(headroom=0.5)

    out = BytesIO()
    audio.export(out, format="wav")
    return out.getvalue()