"""Create local demo configuration once; never overwrite existing credentials."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
text = (root / ".env.example").read_text()
text = text.replace("REPLACE_WITH_CUSTOMER_PASSWORD", secrets.token_urlsafe(18))
text = text.replace("REPLACE_WITH_PRESENTER_PASSWORD", secrets.token_urlsafe(18))
text = text.replace("REPLACE_WITH_RANDOM_SECRET", secrets.token_urlsafe(48))
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; preserving it")
with os.fdopen(fd, "w") as handle:
    handle.write(text)
print(
    "Created private .env. Configure selected-provider and Galileo keys before live preflight."
)
