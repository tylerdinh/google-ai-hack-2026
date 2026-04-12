from __future__ import annotations

import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
TTS_MODEL = "eleven_turbo_v2_5"
TTS_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Distinct voices matched to each personality
AGENT_VOICES: dict[str, str] = {
    "analyst":  "onwK4e9ZLuTAKqWW03F9",  # Daniel  — deep, authoritative British
    "diplomat": "XrExE9yKIg1WjnnlVkGX",  # Matilda — warm, measured
    "sentinel": "N2lVS1w4EtoT3dr4eOWO",  # Callum  — intense, grave
    "explorer": "IKne3meq5aSn9XLyUdCD",  # Charlie — conversational, energetic
}

NARRATOR_VOICE = "nPczCjzI2devNBz1zQrb"  # Brian — solemn narrator for the verdict


async def _tts(text: str, voice_id: str) -> str | None:
    """Call ElevenLabs TTS; return base64-encoded MP3 or None on failure."""
    if not ELEVENLABS_API_KEY:
        logger.debug("ELEVENLABS_API_KEY not set — skipping TTS")
        return None

    url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": TTS_MODEL,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80,
            "style": 0.25,
        },
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            return base64.b64encode(resp.content).decode()
        logger.warning("ElevenLabs HTTP %s: %s", resp.status_code, resp.text[:200])
        return None
    except Exception as exc:
        logger.warning("ElevenLabs error: %s", exc)
        return None


async def agent_speak(text: str, agent_id: str) -> str | None:
    """Generate speech for a named council agent. Returns base64 MP3 or None."""
    voice_id = AGENT_VOICES.get(agent_id)
    if not voice_id:
        return None
    return await _tts(text, voice_id)


async def narrator_speak(text: str) -> str | None:
    """Generate speech with the solemn narrator voice. Returns base64 MP3 or None."""
    return await _tts(text, NARRATOR_VOICE)
