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
import logging
import sys

from device import start
from device.core.args import parse_arguments

logger = logging.getLogger(__name__)


def main() -> None:
  parse_arguments()

  try:
    asyncio.run(start())
  except KeyboardInterrupt:
    pass
  except Exception as exception:
    if logger.isEnabledFor(logging.DEBUG):
      logger.exception(exception)

    logger.error(f"Oremi Device failed to start: {exception}")
    sys.exit(1)


if __name__ == "__main__":
  main()
