"""Print validated reference results without keys; run from backend with its virtual environment."""

import json

from app.config import Settings
from app.storage import Storage

settings = Settings()
storage = Storage(settings)
if storage.dataset is None:
    raise SystemExit("Dataset unavailable")
print(json.dumps(storage.dataset.expected_results, indent=2))
