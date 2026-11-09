"""Best-effort speech cost estimation.

Chat calls price from the models.dev catalog's per-token rates. Speech
bills differently — per audio-second for STT, per input character for
TTS — and the catalog doesn't carry those rates. This table is a
hand-seeded snapshot of provider rate cards (checked Feb 2026; they
drift), so every figure it produces is cost_source="estimated", never
"reported". Unmatched provider/model pairs return None — cost stays
unknown, not free.
"""

from __future__ import annotations

# Ordered (provider_type, model-substring, rate) rules; first match wins.
# STT rates are USD per audio-second, TTS rates USD per input character.
_STT_PER_SECOND: tuple[tuple[str, str, float], ...] = (
    ("openai", "whisper-1", 0.006 / 60),
    ("openai", "gpt-4o-mini-transcribe", 0.003 / 60),
    ("openai", "gpt-4o-transcribe", 0.006 / 60),
    ("openai", "gpt-transcribe", 0.0045 / 60),
    ("groq", "whisper-large-v3-turbo", 0.04 / 3600),
    ("groq", "whisper-large-v3", 0.111 / 3600),
    # Deepgram STT — pre-recorded pay-as-you-go (dictation uploads).
    ("deepgram", "nova-3", 0.0043 / 60),
    ("deepgram", "nova-2", 0.0043 / 60),
    ("deepgram", "nova", 0.0043 / 60),
    ("deepgram", "whisper", 0.0048 / 60),
    ("elevenlabs", "scribe", 0.22 / 3600),
)

_TTS_PER_CHAR: tuple[tuple[str, str, float], ...] = (
    ("openai", "tts-1-hd", 30.0 / 1_000_000),
    ("openai", "tts-1", 15.0 / 1_000_000),
    ("deepgram", "aura-2", 0.030 / 1000),
    ("deepgram", "flux", 0.045 / 1000),
    ("deepgram", "aura", 0.015 / 1000),
    ("elevenlabs", "eleven_flash", 0.04 / 1000),
    ("elevenlabs", "eleven_turbo", 0.04 / 1000),
    ("elevenlabs", "eleven_v4_turbo", 0.04 / 1000),
    ("elevenlabs", "eleven_", 0.08 / 1000),
)


def estimate_speech_cost(
    provider_type: str,
    model: str,
    operation: str,
    *,
    audio_seconds: float | None = None,
    characters: int | None = None,
) -> tuple[float, str] | None:
    """Return (usd, basis_label) for a known rate, else None.

    STT needs a real audio_seconds (provider-reported duration) — it is
    never guessed from byte size. TTS uses the billed character count
    (provider-reported when available, else the submitted text length).
    """
    m = (model or "").lower()
    if operation == "stt":
        if not audio_seconds or audio_seconds <= 0:
            return None
        for ptype, frag, rate in _STT_PER_SECOND:
            if provider_type == ptype and frag in m:
                return audio_seconds * rate, f"~${rate * 60:.4g}/min payg"
        return None
    if operation == "tts":
        if not characters or characters <= 0:
            return None
        for ptype, frag, rate in _TTS_PER_CHAR:
            if provider_type == ptype and frag in m:
                return characters * rate, f"~${rate * 1000:.4g}/1k chars payg"
    return None
