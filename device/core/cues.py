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
from pathlib import Path
from typing import Literal


SoundCue = Literal[
  "announcement",
  "cancel",
  "error",
  "listening",
  "mute_off",
  "mute_on",
  "ready",
  "shutdown",
  "sleep",
  "thinking",
  "volume",
  "wakeword",
]

ConversationEvent = Literal["cancelled", "listening", "processing"]
ConversationState = Literal["idle", "listening", "processing", "speaking"]
SOUNDS_DIRECTORY = Path(__file__).resolve().parent.parent / "sounds"


def get_sound_cue_path(cue: SoundCue) -> Path:
  return SOUNDS_DIRECTORY / f"{cue}.ogg"
