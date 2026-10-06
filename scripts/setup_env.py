"""Create local demo configuration once; never overwrite existing credentials."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
text = (root / ".env.example").read_text()
# The two demo passwords are fixed in the template: a workshop hands the same pair to everyone
# and a presenter says them out loud, so generating a different one per box would mean editing
# every box. The session secret is a real security boundary -- it signs cookies -- so that one is
# always random and never shared.
text = text.replace("REPLACE_WITH_RANDOM_SECRET", secrets.token_urlsafe(48))
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; preserving it")
with os.fdopen(fd, "w") as handle:
    handle.write(text)
print("Created private .env.")
print("Model endpoints and Galileo are configured in the presenter portal, not here.")
print("Demo passwords are the shared workshop pair; change them in .env for anything else.")
