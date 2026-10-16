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
BLANK_URLS=0
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Participant-specific values in .env. The volume is destroyed below, but .env is deliberately kept
# for the address and the demo passwords, so anything here has to be cleared by name.
#
# GALILEO_PROJECT is not a credential and is cleared anyway. The lab has each participant create
# their own project, and a field arriving pre-filled with somebody else's name is a trap: Save and
# Connect answers "project not found", or worse it succeeds and their traces land in a project that
# is not theirs.
SECRETS="OPENAI_API_KEY ANTHROPIC_API_KEY GALILEO_API_KEY SPLUNK_AO_API_KEY
         SPLUNK_AO_O11Y_TOKEN SPLUNK_AO_O11Y_API_TOKEN"
NAMES="GALILEO_PROJECT GALILEO_LOG_STREAM AGENT_CONTROL_AGENT_NAME"
# Not credentials, but they describe one tenant. Kept unless --blank-urls.
URLS="GALILEO_CONSOLE_URL GALILEO_API_URL AGENT_CONTROL_URL
      SPLUNK_AO_CONSOLE_URL SPLUNK_AO_API_URL SPLUNK_AO_REALM SPLUNK_AO_AGENT_CONTROL_URL"
# Blanked rather than deleted, and the difference is not cosmetic. GALILEO_LOG_STREAM present and
# empty in .env overrides the application default; the line deleted altogether restores
# "my-bank-agent", which would put a value back into a field the lab asks the participant to type.

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '    \033[1;33m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --blank-urls) BLANK_URLS=1; shift ;;
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
  - the same credentials from .env, plus GALILEO_PROJECT, which is not a secret but
    would pre-fill every participant's form with somebody else's project name

It keeps the shared demo passwords, the public address, the TLS certificate and the
self-update units, because a clone needs those. Tenant URLs are kept and reported;
pass --blank-urls to clear those too.

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
# Through the unit where one exists, so the state file the portal reads is written too. restart,
# not start: the unit is left `active (exited)` and `start` on an active unit is a no-op.
#
# Falling back to compose matters: a box without the units -- a workstation, or anything where only
# the manual path was ever set up -- would otherwise have its volume destroyed and then fail here,
# leaving the stack down. Wiping and not restarting is the one outcome this script must not produce.
if systemctl list-unit-files splunky-finance.service >/dev/null 2>&1 \
  && systemctl cat splunky-finance.service >/dev/null 2>&1; then
  systemctl restart splunky-finance \
    || die "could not start splunky-finance; see journalctl -u splunky-finance"
else
  note "no splunky-finance unit installed; starting with compose instead"
  sudo -u "$OWNER" docker compose --project-directory "$ROOT" up -d --wait --wait-timeout 240 \
    || die "could not start the stack; see docker compose logs"
fi

say "Verifying nothing was left behind"
LEFT="$(sudo -u "$OWNER" docker compose --project-directory "$ROOT" exec -T backend \
  sh -c 'ls /app/runtime/' 2>/dev/null || true)"
note "runtime volume now holds: $(printf '%s' "$LEFT" | tr '\n' ' ')"
if printf '%s' "$LEFT" | grep -q 'galileo-settings.json'; then
  die "galileo-settings.json still exists. Credentials may remain; do not snapshot this box."
fi
note "galileo-settings.json is gone: no saved credentials, endpoints or backend selection"

# .env is not in the volume, so destroying the volume does not touch it. Clearing it by name is the
# only way these values do not reach a clone.
say "Clearing participant-specific values from .env"
# As the owner, not as root: `sed -i` replaces the file rather than editing in place, so running it
# as root would leave a 0600 root-owned .env that the account running compose cannot read, and the
# stack would come up with no configuration at all.
blank() {
  if grep -q "^$1=." "$ROOT/.env" 2>/dev/null; then
    sudo -u "$OWNER" sed -i "s|^$1=.*|$1=|" "$ROOT/.env" || die "could not edit .env"
    note "cleared    $1"
  fi
}
for FIELD in $SECRETS; do blank "$FIELD"; done
for FIELD in $NAMES; do blank "$FIELD"; done
if [ "$BLANK_URLS" -eq 1 ]; then
  for FIELD in $URLS; do blank "$FIELD"; done
else
  for FIELD in $URLS; do
    VALUE="$(grep -m1 "^$FIELD=" "$ROOT/.env" | cut -d= -f2- || true)"
    [ -z "$VALUE" ] || note "kept       $FIELD=$VALUE"
  done
fi
# The stack is already running by this point, so it is holding the values just cleared.
say "Restarting so the cleared values are what the application is running"
if systemctl list-unit-files splunky-finance.service >/dev/null 2>&1 \
  && systemctl cat splunky-finance.service >/dev/null 2>&1; then
  systemctl restart splunky-finance || die "could not restart; see journalctl -u splunky-finance"
else
  sudo -u "$OWNER" docker compose --project-directory "$ROOT" up -d --wait --wait-timeout 240 \
    || die "could not restart the stack; see docker compose logs"
fi
note "running on the cleared configuration"

say "What this image will carry"
note "APP_ORIGIN       $(grep -m1 '^APP_ORIGIN=' "$ROOT/.env" | cut -d= -f2-)"
note "DEMO_MODE        $(grep -m1 '^DEMO_MODE=' "$ROOT/.env" | cut -d= -f2- || echo presenter)"
note "UPDATE_CHANNEL   $(grep -m1 '^UPDATE_CHANNEL=' "$ROOT/.env" | cut -d= -f2- || echo tags)"
note "release          $(sudo -u "$OWNER" git -C "$ROOT" describe --tags 2>/dev/null || echo unknown)"
if [ -f /etc/caddy/tls.crt ]; then
  note "certificate      $(openssl x509 -in /etc/caddy/tls.crt -noout -enddate | cut -d= -f2-) (expires)"
fi
# Checked rather than assumed: these were just cleared, so anything still here means an edit
# failed silently and the image would carry a credential.
LEFTOVER=0
for FIELD in $SECRETS $NAMES; do
  VALUE="$(grep -m1 "^$FIELD=" "$ROOT/.env" | cut -d= -f2- || true)"
  if [ -n "$VALUE" ]; then
    warn "WARNING: $FIELD is still set in .env and WOULD be baked into the image."
    warn "         Inspect with: grep -n '^$FIELD=' .env"
    LEFTOVER=1
  fi
done
[ "$LEFTOVER" -eq 0 ] || die "participant-specific values remain in .env; do not snapshot this box."
note "no credentials or project name remain in .env"

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
