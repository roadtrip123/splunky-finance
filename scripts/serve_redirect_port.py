"""Serve the port 443 redirect's destination as well as 443, by editing the proxy's config.

A shared lab image carries

    -A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443

in /etc/iptables/rules.v4, restored on every boot by netfilter-persistent, and on some boxes put
back while they are running by something outside them. Caddy binds 443, so every arriving
connection is sent to a port nothing listens on: healthy by every internal measure, dead from a
browser. Removing the rule is a fix that has to win that race every time. Binding the destination
port as well does not: the box answers whether the rule is there or not.

This is the same arrangement scripts/install.sh now sets up at install time. It exists because a box
built from an older image already has its Caddyfile written, and nothing in the update path touches
that file.

    sudo python3 scripts/serve_redirect_port.py --dry-run     what it would write, changing nothing
    sudo python3 scripts/serve_redirect_port.py               edit, validate, restart, verify

Idempotent: a Caddyfile that already serves the destination is left alone. It only ever adds an
address to a site that serves the public port, so a workshop config with a port per participant is
untouched, as is a plain-HTTP site, where the redirect of 443 does not apply.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

CADDYFILE = Path("/etc/caddy/Caddyfile")
RULES = Path("/etc/iptables/rules.v4")
DEFAULT_DESTINATION = 8443

# The line that opens a site block: one or more addresses, then `{`. A bare `{` is the global
# options block and must not match, which is why the first character cannot be a brace.
SITE_LINE = re.compile(r"^(?P<addresses>[^\s#{][^{]*?)\s*\{\s*$")
ADDRESS = re.compile(r"^(?:(?P<scheme>https?)://)?(?P<host>\[[^\]]+\]|[^:/\s]+)(?::(?P<port>\d+))?$")
# Matched by what the rule does rather than how it is spelled: the saved copy carries `-m tcp`, a
# rule added by hand may not, and the destination has varied between boxes.
REDIRECT = re.compile(r"--dport\s+(?P<dport>\d+)\b.*-j\s+REDIRECT.*--to-ports\s+(?P<to>\d+)")


def say(message):
    print(f"\n\033[1m==> {message}\033[0m")


def note(message):
    print(f"    {message}")


def warn(message):
    print(f"    \033[1;33m{message}\033[0m")


def die(message):
    print(f"\n\033[1;31mFAILED: {message}\033[0m", file=sys.stderr)
    raise SystemExit(1)


def destinations(listing, public_port):
    """Every port the public port is redirected to, in whatever the caller hands us."""
    found = set()
    for line in listing.splitlines():
        match = REDIRECT.search(line)
        if match and int(match.group("dport")) == public_port:
            found.add(int(match.group("to")))
    return sorted(found)


def live_rules():
    """The running nat table, or an empty string where it cannot be read.

    Not fatal: the destination defaults to 8443, and binding a port nothing redirects to is
    harmless. Refusing to run because one of two sources is unavailable would not be.
    """
    if not shutil.which("iptables-save"):
        return ""
    result = subprocess.run(["iptables-save", "-t", "nat"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def rewrite(text, public_port, destination):
    """Add `host:destination` to every site that serves the public port. Returns (text, changed)."""
    out, changed = [], []
    for line in text.splitlines(keepends=True):
        match = SITE_LINE.match(line.rstrip("\n"))
        if not match:
            out.append(line)
            continue
        addresses = [part.strip() for part in match.group("addresses").split(",") if part.strip()]
        parsed = [ADDRESS.match(address) for address in addresses]
        if not all(parsed):
            # An address shape this does not understand. Left alone rather than guessed at.
            out.append(line)
            continue
        # Plain HTTP is not what the redirect of 443 affects, and a site on some other port is
        # somebody's deliberate choice, such as a port per participant.
        if any(entry.group("scheme") == "http" for entry in parsed):
            out.append(line)
            continue
        ports = {entry.group("port") for entry in parsed}
        if str(destination) in ports:
            out.append(line)
            continue
        serves_public = {None, str(public_port)} & ports
        if not serves_public:
            out.append(line)
            continue
        rebuilt = []
        for entry in parsed:
            host = entry.group("host")
            port = entry.group("port") or str(public_port)
            rebuilt.append(f"{host}:{port}")
            if port == str(public_port):
                rebuilt.append(f"{host}:{destination}")
                changed.append(host)
        out.append(", ".join(rebuilt) + " {\n")
    return "".join(out), changed


def caddy_validate(path):
    result = subprocess.run(
        ["caddy", "validate", "--config", str(path)], capture_output=True, text=True
    )
    if result.returncode:
        print(result.stderr.strip()[-2000:], file=sys.stderr)
    return result.returncode == 0


def verify(host, public_port, destination):
    """Both paths, with the Host header a browser sends.

    The redirected one is the check that matters: it proves the second address is matched and not
    merely bound. A local request cannot traverse PREROUTING, so this reaches the port directly
    instead of relying on the rule being in place.
    """
    if not shutil.which("curl"):
        warn("curl is not installed; check the two paths by hand")
        return
    for label, port in (("direct", public_port), ("redirected", destination)):
        result = subprocess.run(
            ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10",
             "--connect-to", f"{host}:{public_port}:127.0.0.1:{port}",
             f"https://{host}:{public_port}/"],
            capture_output=True, text=True,
        )
        code = result.stdout.strip() or "000"
        note(f"{label:<11} {host} via 127.0.0.1:{port} -> {code}")
        if code != "200":
            warn(f"expected 200 on the {label} path. Check: journalctl -u caddy -n 30")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="print the result, change nothing")
    parser.add_argument("--public-port", type=int, default=443, help="the port browsers ask for")
    parser.add_argument("--destination", type=int, help="serve this port too, instead of detecting")
    parser.add_argument("--caddyfile", type=Path, default=CADDYFILE)
    arguments = parser.parse_args()

    if not arguments.caddyfile.exists():
        die(f"{arguments.caddyfile} does not exist. This box has no Caddy config to edit.")

    say("Finding where arriving traffic is sent")
    saved = RULES.read_text() if RULES.exists() else ""
    found = destinations(live_rules() + "\n" + saved, arguments.public_port)
    for port in found:
        note(f"port {arguments.public_port} is redirected to {port} here")
    destination = arguments.destination or (found[0] if found else DEFAULT_DESTINATION)
    if not found:
        note(f"no redirect of port {arguments.public_port} found; serving {destination} anyway,")
        note("because the rule is restored at boot on these images and costs nothing to cover")
    if len(found) > 1:
        warn(f"more than one destination; serving {destination}. Pass --destination to choose.")

    say(f"Adding :{destination} to every site that serves :{arguments.public_port}")
    original = arguments.caddyfile.read_text()
    updated, changed = rewrite(original, arguments.public_port, destination)
    if not changed:
        note("nothing to do: no site serves the public port, or they already serve the destination")
        return 0
    for host in changed:
        note(f"{host} will answer on {arguments.public_port} and {destination}")
    print()
    print(updated)
    if arguments.dry_run:
        note("--dry-run: nothing was written")
        return 0

    backup = arguments.caddyfile.with_name(arguments.caddyfile.name + ".bak")
    if not backup.exists():
        shutil.copy2(arguments.caddyfile, backup)
        note(f"backed up to {backup}")
    arguments.caddyfile.write_text(updated)

    say("Validating")
    if not shutil.which("caddy"):
        warn("caddy is not on PATH, so the result was not validated before being written")
    elif not caddy_validate(arguments.caddyfile):
        # Restored rather than left broken: the next restart would otherwise take the portal down,
        # and a box whose proxy will not start is harder to diagnose than one that never changed.
        arguments.caddyfile.write_text(original)
        die(f"caddy rejected the result, so {arguments.caddyfile} was put back unchanged.")
    else:
        note("configuration is valid")

    say("Restarting caddy")
    result = subprocess.run(["systemctl", "restart", "caddy"], capture_output=True, text=True)
    if result.returncode:
        arguments.caddyfile.write_text(original)
        subprocess.run(["systemctl", "restart", "caddy"], capture_output=True, text=True)
        die("caddy would not restart, so the previous configuration was restored and reloaded.")
    note("restarted")

    say("Checking both paths")
    for host in changed:
        verify(host, arguments.public_port, destination)

    print(f"""
Leave the redirect rule where it is. This box now answers whether it is there or not.

  1. Open https://{changed[0]}/ from another machine. Nothing on this box can
     test its own public address, so a local check proves nothing on its own.
  2. Make the same edit in the image before snapshotting, or every clone needs it by hand.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
