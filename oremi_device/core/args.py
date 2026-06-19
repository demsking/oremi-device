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
import argparse

from .package import APP_DESCRIPTION
from .package import APP_NAME
from .package import APP_VERSION


def positive_float(value: str) -> float:
  parsed = float(value)

  if parsed <= 0:
    raise argparse.ArgumentTypeError("must be greater than zero")

  return parsed


def parse_arguments() -> argparse.Namespace:
  parser = argparse.ArgumentParser(prog=APP_NAME, description=APP_DESCRIPTION)
  subparsers = parser.add_subparsers(dest="command")

  parser.add_argument(
    "-v", "--version", action="version", version=f"%(prog)s {APP_VERSION}", help="Show the version of the application."
  )

  #
  # Start
  command = subparsers.add_parser(name="start", help="Start listening")

  command.add_argument(
    "-l",
    "--language",
    type=str,
    choices=("fr", "en"),
    default="fr",
    help='The language to use for wake word detection and audio processing. Default is "fr" (French).',
  )

  command.add_argument(
    "-i",
    "--device-index",
    type=int,
    default=None,
    help="Index of the audio device to be used for recording audio.",
  )

  command.add_argument(
    "--no-microphone",
    action="store_false",
    dest="microphone_enabled",
    help="Disable microphone capture, sound detection, and wake word detection.",
  )

  command.add_argument(
    "--no-speaker",
    action="store_false",
    dest="speaker_enabled",
    help="Disable speaker output.",
  )

  command.add_argument(
    "-d",
    "--device",
    type=str,
    default=None,
    help="Name of the device.",
  )

  command.add_argument(
    "--delay",
    type=int,
    default=3,
    help="The cooldown period (in seconds) to wait before sending the same sound event again (default: 3).",
  )

  command.add_argument(
    "--conversation-timeout",
    type=positive_float,
    default=15.0,
    help="Maximum seconds to capture speech after a wake word (default: 15).",
  )

  command.add_argument("--config", type=str, help="Path to the Oremi Device configuration file.")

  command.add_argument(
    "--ohunerin-host",
    type=str,
    required=True,
    help="Host address of the Ohunerin server to connect to.",
  )

  command.add_argument(
    "--ohunerin-port",
    type=int,
    default=5023,
    help="Port number of the Ohunerin server to connect to (default: 5023).",
  )

  command.add_argument(
    "--andika-host",
    type=str,
    required=True,
    help="Host address of the Andika server to connect to.",
  )

  command.add_argument(
    "--andika-port",
    type=int,
    default=5315,
    help="Port number of the Andika server to connect to (default: 5315).",
  )

  command.add_argument(
    "--cert-file",
    type=str,
    help="Path to the certificate file for secure connection.",
  )

  # Node ID
  command.add_argument(
    "-n",
    "--node-id",
    type=str,
    required=True,
    help="Unique identifier for the listener node.",
  )

  # MQTT Broker address
  command.add_argument("--mqtt-broker", type=str, required=True, help="The address of the MQTT broker.")

  # MQTT Broker port
  command.add_argument("--mqtt-port", type=int, default=1883, help="The port of the MQTT broker. Default is 1883.")

  # MQTT Username
  command.add_argument(
    "--mqtt-username", type=str, default=None, help="The username for authenticating with the MQTT broker. Default is None."
  )

  # MQTT Password
  command.add_argument(
    "--mqtt-password", type=str, default=None, help="The password for authenticating with the MQTT broker. Default is None."
  )

  # MQTT Topic
  command.add_argument(
    "--mqtt-topic",
    type=str,
    default="oremi/device",
    help='The MQTT topic to publish audio detection events to. Default is "oremi/device".',
  )

  # MQTT Discovery
  command.add_argument(
    "--no-mqtt-discovery",
    action="store_false",
    dest="mqtt_discovery",
    help="Disable Home Assistant MQTT discovery.",
  )

  # MQTT Discovery Prefix
  command.add_argument(
    "--mqtt-discovery-prefix",
    type=str,
    default="homeassistant",
    help='Home Assistant MQTT discovery prefix. Default is "homeassistant".',
  )

  return parser.parse_args()
