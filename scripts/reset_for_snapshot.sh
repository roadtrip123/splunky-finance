#!/usr/bin/env bash
# Wipe everything participant-specific, so an image made from this box carries no credentials.
#
#   sudo ./scripts/reset_for_snapshot.sh --confirm
#
# Clearing fields in the portal is not the same thing. Credentials live in galileo-settings.json
# inside the runtime volume, and a field you forget to clear is a field every clone inherits -- a
# hundred people holding your API key. This destroys the volume instead of editing it, then proves
# the file is gone.
set -euo pipefail

CONFIRM=0
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '    \033[1;33m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [ "$CONFIRM" -eq 0 ]; then
  cat <<EOF

This will permanently delete, from this box:

  - every saved observability credential and model endpoint, including API keys
  - the synthetic dataset, and any transfers made during testing
  - all conversations and login sessions

It keeps the shared demo passwords, the public address, the TLS certificate and the
self-update units, because a clone needs those.

Re-run with --confirm to proceed.
EOF
  exit 1
fi

[ "$(id -u)" -eq 0 ] || die "Needs root. Re-run with sudo."
OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != "root" ] || die "Run with sudo from the account that owns this repository."

say "Stopping the stack and destroying the runtime volume"
systemctl stop splunky-finance 2>/dev/null || true
# As the owner, because that account is the one in the docker group.
sudo -u "$OWNER" docker compose --project-directory "$ROOT" down -v || die "compose down failed"
note "volume removed"

say "Starting clean"
# Through the unit rather than compose, so the state file the portal reads is written too.
systemctl start splunky-finance || die "could not start splunky-finance; see journalctl -u splunky-finance"

say "Verifying nothing was left behind"
LEFT="$(sudo -u "$OWNER" docker compose --project-directory "$ROOT" exec -T backend \
  sh -c 'ls /app/runtime/' 2>/dev/null || true)"
note "runtime volume now holds: $(printf '%s' "$LEFT" | tr '\n' ' ')"
if printf '%s' "$LEFT" | grep -q 'galileo-settings.json'; then
  die "galileo-settings.json still exists. Credentials may remain; do not snapshot this box."
fi
note "galileo-settings.json is gone: no saved credentials, endpoints or backend selection"

# .env is not in the volume and is deliberately kept, but it should hold nothing participant-specific.
say "What this image will carry"
note "APP_ORIGIN       $(grep -m1 '^APP_ORIGIN=' "$ROOT/.env" | cut -d= -f2-)"
note "DEMO_MODE        $(grep -m1 '^DEMO_MODE=' "$ROOT/.env" | cut -d= -f2- || echo presenter)"
note "UPDATE_CHANNEL   $(grep -m1 '^UPDATE_CHANNEL=' "$ROOT/.env" | cut -d= -f2- || echo tags)"
note "release          $(sudo -u "$OWNER" git -C "$ROOT" describe --tags 2>/dev/null || echo unknown)"
if [ -f /etc/caddy/tls.crt ]; then
  note "certificate      $(openssl x509 -in /etc/caddy/tls.crt -noout -enddate | cut -d= -f2-) (expires)"
fi
for FIELD in OPENAI_API_KEY ANTHROPIC_API_KEY GALILEO_API_KEY SPLUNK_AO_API_KEY; do
  VALUE="$(grep -m1 "^$FIELD=" "$ROOT/.env" | cut -d= -f2- || true)"
  if [ -n "$VALUE" ]; then
    warn "WARNING: $FIELD is set in .env and WILL be baked into the image."
    warn "         Blank it before snapshotting if it is yours rather than the demo's."
  fi
done

cat <<EOF

$(printf '\033[1;32mReady to snapshot.\033[0m')

Before you create the image:

  1. Check the portal shows no endpoint and no observability credentials.
  2. Confirm the app still answers on its public address, from another machine.

Every clone needs its own address and its own cookie signing key. On first boot:

  python3 scripts/setup_env.py --origin <this-clone-address> --rotate-secret
  # rewrite the proxy's site address to match, then:
  sudo systemctl restart caddy && sudo systemctl restart splunky-finance

Without --rotate-secret every clone shares one SESSION_SECRET, which means a session
cookie minted on one box is valid on all of them.
EOF
