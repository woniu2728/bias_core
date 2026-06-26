from __future__ import annotations

import sys

from bias_core.services import settings as _settings


sys.modules[__name__] = _settings
