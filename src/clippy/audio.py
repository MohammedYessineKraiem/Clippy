from __future__ import annotations

import io
import math
import struct
import wave
import winsound


class AudioService:
    """Small generated WAV cues; no audio files or network resources are required."""

    def __init__(self, enabled: bool = False, volume: float = 0.25) -> None:
        self.enabled = enabled
        self.volume = volume
        self._sounds = {
            "capture": self._tone(620, 880, 90),
            "open": self._tone(180, 240, 70),
            "close": self._tone(440, 170, 100),
            "confirm": self._tone(780, 780, 45),
        }

    def configure(self, enabled: bool, volume: float) -> None:
        self.enabled = enabled
        self.volume = max(0.0, min(1.0, volume))
        self._sounds = {
            "capture": self._tone(620, 880, 90),
            "open": self._tone(180, 240, 70),
            "close": self._tone(440, 170, 100),
            "confirm": self._tone(780, 780, 45),
        }

    def play(self, cue: str) -> None:
        if self.enabled and cue in self._sounds:
            winsound.PlaySound(self._sounds[cue], winsound.SND_MEMORY | winsound.SND_ASYNC)

    def _tone(self, start_hz: float, end_hz: float, duration_ms: int) -> bytes:
        rate = 22_050
        count = int(rate * duration_ms / 1000)
        frames = bytearray()
        phase = 0.0
        for index in range(count):
            progress = index / max(1, count - 1)
            frequency = start_hz + (end_hz - start_hz) * progress
            phase += 2 * math.pi * frequency / rate
            envelope = math.sin(math.pi * progress) ** 1.5
            sample = int(32767 * 0.16 * self.volume * envelope * math.sin(phase))
            frames.extend(struct.pack("<h", sample))
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(frames)
        return output.getvalue()
