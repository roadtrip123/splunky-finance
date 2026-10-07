"""Create local demo configuration once; never overwrite existing credentials.

`--origin` also updates an existing `.env` in place, because an instance cloned from an AMI carries
the address of the instance it was baked from. Only the origin and the cookie flag move; the session
secret and everything else stay as they are unless `--rotate-secret` says otherwise.
"""

import argparse
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[1]
path = root / ".env"


def resolve_origin(value):
    """Return (origin, secure_cookies), accepting a bare host or a full origin.

    HTTPS and secure cookies are validated together by the backend: set one without the other and it
    refuses to start. Deriving the flag from the scheme means that cannot be got wrong by hand.
    """
    origin = value if "://" in value else f"https://{value}"
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit(f"Not an HTTP(S) origin: {value}")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit("Origin must carry no path, query, fragment or credentials")
    return origin.rstrip("/"), parsed.scheme == "https"


def set_key(text, key, value):
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    replacement = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return text.rstrip("\n") + f"\n{replacement}\n"


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--origin",
    help="Public origin, e.g. https://203.0.113.10 or just 203.0.113.10. Sets APP_ORIGIN and "
    "SESSION_COOKIE_SECURE together, and updates an existing .env rather than refusing",
)
parser.add_argument(
    "--rotate-secret",
    action="store_true",
    help="Issue a new SESSION_SECRET. Logs everyone out; use it on a clone that should not share "
    "cookie signing with the instance it was baked from",
)
args = parser.parse_args()

if path.exists():
    if not (args.origin or args.rotate_secret):
        raise SystemExit(".env already exists; preserving it")
    text = path.read_text()
    changed = []
    if args.origin:
        origin, secure = resolve_origin(args.origin)
        text = set_key(text, "APP_ORIGIN", origin)
        text = set_key(text, "SESSION_COOKIE_SECURE", "true" if secure else "false")
        changed.append(f"APP_ORIGIN={origin}, SESSION_COOKIE_SECURE={'true' if secure else 'false'}")
    if args.rotate_secret:
        text = set_key(text, "SESSION_SECRET", secrets.token_urlsafe(48))
        changed.append("SESSION_SECRET rotated; existing logins are now invalid")
    # Written through a temporary file so an interrupted run cannot leave a half-written .env, which
    # would take the backend down on its next restart.
    temporary = path.with_suffix(".env.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    temporary.replace(path)
    print(f"Updated {path.name}:")
    for line in changed:
        print(f"  {line}")
    print("Restart the stack for this to take effect: docker compose up -d")
    raise SystemExit(0)

text = (root / ".env.example").read_text()
# The two demo passwords are fixed in the template: a workshop hands the same pair to everyone
# and a presenter says them out loud, so generating a different one per box would mean editing
# every box. The session secret is a real security boundary -- it signs cookies -- so that one is
# always random and never shared.
text = text.replace("REPLACE_WITH_RANDOM_SECRET", secrets.token_urlsafe(48))
if args.origin:
    origin, secure = resolve_origin(args.origin)
    text = set_key(text, "APP_ORIGIN", origin)
    text = set_key(text, "SESSION_COOKIE_SECURE", "true" if secure else "false")
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; preserving it")
with os.fdopen(fd, "w") as handle:
    handle.write(text)
print("Created private .env.")
if args.origin:
    print(f"APP_ORIGIN={origin} with SESSION_COOKIE_SECURE={'true' if secure else 'false'}.")
print("Model endpoints and Galileo are configured in the presenter portal, not here.")
print("Demo passwords are the shared workshop pair; change them in .env for anything else.")
