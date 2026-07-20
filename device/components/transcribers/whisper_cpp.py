# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import asyncio
import io
import json
import logging
import math
import wave
from array import array
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

import httpx
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from device.components.transcribers.base import BaseTranscriber
from device.core.audio import Audio
from device.core.cues import ConversationEvent
from device.core.settings import Settings

logger = logging.getLogger(__name__)

FINAL_TRANSCRIPTION_TOPIC = "transcription/result"


class WhisperCppListener(BaseTranscriber):
  """Capture one utterance and submit it to a whisper.cpp HTTP server."""

  def __init__(
    self,
    settings: Settings,
    publisher: Any,
    audio_stream: Audio,
    transcription_complete_event: asyncio.Event,
    conversation_event_handler: Callable[[ConversationEvent], Awaitable[None]] | None = None,
    final_transcription_handler: Callable[[str], Awaitable[None]] | None = None,
  ) -> None:
    super().__init__(settings)
    self.publisher = publisher
    self.audio_stream = audio_stream
    self.transcription_complete_event = transcription_complete_event
    self.conversation_event_handler = conversation_event_handler
    self.final_transcription_handler = final_transcription_handler

  @property
  def name(self) -> str:
    return "whisper.cpp"

  @staticmethod
  def _rms(data: bytes) -> float:
    samples = array("h")
    samples.frombytes(data)

    if not samples:
      return 0

    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))

  @staticmethod
  def _wav(audio: bytes, samplerate: int) -> bytes:
    output = io.BytesIO()

    with wave.open(output, "wb") as wav_file:
      wav_file.setnchannels(1)
      wav_file.setsampwidth(2)
      wav_file.setframerate(samplerate)
      wav_file.writeframes(audio)

    return output.getvalue()

  def _publish(
    self,
    topic: str,
    message: str,
    *,
    qos: int = 1,
    retain: bool = False,
    props: Properties | None = None,
  ) -> None:
    if self.publisher is None:
      return

    publish_event = getattr(self.publisher, "publish_event", None)
    if callable(publish_event):
      publish_event(topic, message, qos=qos, retain=retain, props=props)
    elif callable(self.publisher):
      self.publisher(topic, message, qos=qos, retain=retain, props=props)

  async def _capture(self) -> bytes:
    audio = bytearray()
    speech_started = False
    silence_duration = 0.0
    audio_queue = self.audio_stream.subscribe()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + self.settings.conversation_timeout

    try:
      async with self.audio_stream:
        while self.audio_stream.is_active():
          remaining = deadline - loop.time()

          if remaining <= 0:
            break

          try:
            data = await asyncio.wait_for(self.audio_stream.data(audio_queue), timeout=min(remaining, 1.0))
          except TimeoutError:
            continue

          audio.extend(data)
          chunk_duration = len(data) / (2 * self.audio_stream.samplerate)

          if self._rms(data) >= self.settings.whisper_silence_threshold:
            speech_started = True
            silence_duration = 0
          elif speech_started:
            silence_duration += chunk_duration

            if silence_duration >= self.settings.whisper_silence_duration:
              break
    finally:
      self.audio_stream.unsubscribe(audio_queue)

    return bytes(audio) if speech_started else b""

  async def transcribing(self) -> None:
    await self.listening()

  async def listening(self) -> None:
    logger.info(f"Listening from {self.audio_stream.device_name} device for whisper.cpp...")

    try:
      audio = await self._capture()

      if not audio:
        if self.conversation_event_handler:
          await self.conversation_event_handler("cancelled")
        return

      if self.conversation_event_handler:
        await self.conversation_event_handler("processing")

      endpoint = f"{str(self.settings.whisper_url).rstrip('/')}/inference"
      verify = self.settings.cert_file if self.settings.cert_file else True

      async with httpx.AsyncClient(verify=verify, timeout=self.settings.conversation_timeout) as client:
        response = await client.post(
          endpoint,
          files={"file": ("utterance.wav", self._wav(audio, self.audio_stream.samplerate), "audio/wav")},
          data={"language": self.settings.language, "response_format": "json"},
        )
        response.raise_for_status()
        payload = response.json()

      transcription = payload.get("text", "").strip()

      if transcription:
        payload["text"] = transcription
        props = Properties(PacketTypes.PUBLISH)
        props.MessageExpiryInterval = self.settings.delay

        logger.debug(payload)
        self._publish(FINAL_TRANSCRIPTION_TOPIC, json.dumps(payload), qos=1, retain=False, props=props)

        if self.final_transcription_handler:
          await self.final_transcription_handler(transcription)
      elif self.conversation_event_handler:
        await self.conversation_event_handler("cancelled")
    except Exception as error:
      logger.error(f"whisper.cpp transcription error: {error}")

      if self.conversation_event_handler:
        await self.conversation_event_handler("cancelled")
    finally:
      self.transcription_complete_event.set()
