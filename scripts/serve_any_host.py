"""Serve whatever hostname this instance is reached at, on 443 and the redirect's destination.

A lab platform gives each instance its own name, such as i-0abc123.splunk.show, assigned when it
boots. An image cannot carry that name, and on a platform with no cloud-init and no SSH for
participants there is nothing to set it afterwards. Boot-time units are not the answer either: the
one that already exists for the port redirect did not run on the box this was written for.

So nothing per-instance is configured at all. Two changes make the image identical everywhere:

    the proxy serves by port rather than by name, which a wildcard certificate covers, and
    APP_ORIGIN becomes https://*.<domain>, which the Origin check accepts one label under.

    sudo python3 scripts/serve_any_host.py --dry-run     what it would do, changing nothing
    sudo python3 scripts/serve_any_host.py

The domain is read from the current APP_ORIGIN unless --domain says otherwise. Idempotent: a box
already configured this way is left alone. It does not touch a workshop config serving a port per
participant, or a plain-HTTP site, since neither can use a wildcard origin.

The Origin check this relies on is the third layer, not the only one: session cookies are
host-scoped, HttpOnly, Secure and SameSite=Strict, so a page on a sibling instance sends no cookie
at all, and every mutating request still carries the session's own CSRF token.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = Path("/etc/caddy/Caddyfile")

sys.path.insert(0, str(ROOT / "scripts"))
# Imported after the path above is set, which is why this is not at the top. The destination port
# is read from the live rule by the same code that serves it, so the two cannot drift.
import serve_redirect_port as redirect  # noqa: E402

say, note, warn, die = redirect.say, redirect.note, redirect.warn, redirect.die
SITE_LINE = redirect.SITE_LINE
ADDRESS = redirect.ADDRESS
DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", re.I)


def owner():
    """The account that owns the repository, for anything that writes inside it.

    setup_env.py replaces .env rather than editing it in place, so running it as root leaves a
    root-owned 0600 file that the account running compose cannot read, and the stack comes up
    without configuration.
    """
    name = os.environ.get("SUDO_USER", "")
    if not name or name == "root":
        die("Run with sudo from the account that owns this repository, not as root directly.")
    return name


def domain_from_env():
    """The registrable domain under which this box is reached, from the configured origin."""
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("APP_ORIGIN="):
            host = line.partition("=")[2].strip().split("://")[-1].split("/")[0].split(":")[0]
            if host.startswith("*."):
                return host[2:]
            _, _, rest = host.partition(".")
            return rest or None
    return None


def rewrite(text, public_port, destination):
    """Drop the hostname from every site that serves the public port. Returns (text, changed)."""
    out, changed = [], []
    for line in text.splitlines(keepends=True):
        match = SITE_LINE.match(line.rstrip("\n"))
        if not match:
            out.append(line)
            continue
        addresses = [part.strip() for part in match.group("addresses").split(",") if part.strip()]
        parsed = [ADDRESS.match(address) for address in addresses]
        if not all(parsed):
            out.append(line)
            continue
        # Plain HTTP cannot carry a wildcard origin, and a site on some other port is a deliberate
        # choice such as one port per participant.
        if any(entry.group("scheme") == "http" for entry in parsed):
            out.append(line)
            continue
        ports = {entry.group("port") or str(public_port) for entry in parsed}
        if not {str(public_port)} & ports:
            out.append(line)
            continue
        wanted = [f":{port}" for port in sorted(ports | {str(destination)}, key=int)]
        if addresses == wanted:
            out.append(line)
            continue
        for entry in parsed:
            # One note per host, not per address: both ports carry the same name.
            if entry.group("host") not in changed:
                changed.append(entry.group("host"))
        out.append(", ".join(wanted) + " {\n")
    return "".join(out), changed


def set_origin(domain, account, dry_run):
    origin = f"https://*.{domain}"
    note(f"APP_ORIGIN will become {origin}")
    if dry_run:
        return True
    result = subprocess.run(
        ["sudo", "-u", account, "python3", str(ROOT / "scripts" / "setup_env.py"),
         "--origin", origin],
        capture_output=True, text=True, cwd=ROOT,
    )
    print(result.stdout.strip() or result.stderr.strip())
    return result.returncode == 0


def restart_stack(account):
    """Through the unit where there is one, so the state file the portal reads is written too."""
    unit = subprocess.run(
        ["systemctl", "cat", "splunky-finance.service"], capture_output=True, text=True
    )
    if unit.returncode == 0:
        result = subprocess.run(
            ["systemctl", "restart", "splunky-finance"], capture_output=True, text=True
        )
        if result.returncode == 0:
            return True
        warn("the splunky-finance unit would not restart; falling back to compose")
    result = subprocess.run(
        ["sudo", "-u", account, "docker", "compose", "--project-directory", str(ROOT),
         "up", "-d", "--wait", "--wait-timeout", "240"],
        capture_output=True, text=True,
    )
    if result.returncode:
        print(result.stderr.strip()[-2000:], file=sys.stderr)
    return result.returncode == 0


def verify(domain, public_port, destination):
    """Two names the proxy has never been told about, and the Origin check behind it.

    A 403 from the login endpoint means the origin was rejected; a 401 means it was accepted and
    the credentials were not supplied, which is the answer that proves the wildcard works. The
    check runs before authentication, so no password is needed to read it.
    """
    if not shutil.which("curl"):
        warn("curl is not installed; check from a browser instead")
        return
    for host in (f"i-probe1.{domain}", f"i-probe2.{domain}"):
        for port in (public_port, destination):
            code = subprocess.run(
                ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10",
                 "--connect-to", f"{host}:{public_port}:127.0.0.1:{port}",
                 f"https://{host}:{public_port}/"],
                capture_output=True, text=True,
            ).stdout.strip() or "000"
            note(f"{host} via 127.0.0.1:{port} -> {code}")
            if code != "200":
                warn("expected 200. Check: journalctl -u caddy -n 30")
        code = subprocess.run(
            ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10",
             "-X", "POST", "-H", "Content-Type: application/json",
             "-H", f"Origin: https://{host}",
             "-d", '{"customer_number":"0","password":"0"}',
             "--connect-to", f"{host}:{public_port}:127.0.0.1:{public_port}",
             f"https://{host}:{public_port}/api/auth/login"],
            capture_output=True, text=True,
        ).stdout.strip() or "000"
        verdict = {"401": "origin accepted", "403": "ORIGIN REJECTED"}.get(code, "unexpected")
        note(f"origin check for {host} -> {code} ({verdict})")
        if code == "403":
            warn("the backend is still configured for one exact address. Did the stack restart?")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    parser.add_argument("--domain", help="the domain instances are named under, e.g. splunk.show")
    parser.add_argument("--public-port", type=int, default=443)
    parser.add_argument("--destination", type=int, help="serve this port too, instead of detecting")
    parser.add_argument("--caddyfile", type=Path, default=CADDYFILE)
    arguments = parser.parse_args()

    account = owner() if not arguments.dry_run else os.environ.get("SUDO_USER", "")
    if not arguments.caddyfile.exists():
        die(f"{arguments.caddyfile} does not exist. This box has no Caddy config to edit.")

    say("Working out the domain")
    domain = arguments.domain or domain_from_env()
    if not domain:
        die("Could not read a domain from .env. Pass it: --domain example.com")
    if not DOMAIN.fullmatch(domain) or domain.startswith("*"):
        die(f"Not a domain with at least two labels: {domain}")
    note(f"instances are named under {domain}")

    say("Finding where arriving traffic is sent")
    saved = redirect.RULES.read_text() if redirect.RULES.exists() else ""
    found = redirect.destinations(redirect.live_rules() + "\n" + saved, arguments.public_port)
    for port in found:
        note(f"port {arguments.public_port} is redirected to {port} here")
    destination = arguments.destination or (found[0] if found else redirect.DEFAULT_DESTINATION)
    if not found:
        note(f"no redirect found; serving {destination} as well anyway, since these images")
        note("restore that rule at boot and binding a second port costs nothing")

    say("Rewriting the proxy to serve by port rather than by name")
    original = arguments.caddyfile.read_text()
    updated, changed = rewrite(original, arguments.public_port, destination)
    if changed:
        for host in changed:
            note(f"{host} will no longer be matched on; every arriving name is served")
        print()
        print(updated)
    else:
        note("no named HTTPS site serves the public port here; nothing to change in the proxy")

    if not set_origin(domain, account, arguments.dry_run):
        die("setup_env.py failed; nothing was written to the proxy.")
    if arguments.dry_run:
        note("--dry-run: nothing was written")
        return 0

    if changed:
        backup = arguments.caddyfile.with_name(arguments.caddyfile.name + ".bak")
        if not backup.exists():
            shutil.copy2(arguments.caddyfile, backup)
            note(f"backed up to {backup}")
        arguments.caddyfile.write_text(updated)

        say("Validating")
        if not shutil.which("caddy"):
            warn("caddy is not on PATH, so the result was not validated before being written")
        elif not redirect.caddy_validate(arguments.caddyfile):
            arguments.caddyfile.write_text(original)
            die(f"caddy rejected the result, so {arguments.caddyfile} was put back unchanged.")
        else:
            note("configuration is valid")

        say("Restarting caddy")
        if subprocess.run(["systemctl", "restart", "caddy"], capture_output=True).returncode:
            arguments.caddyfile.write_text(original)
            subprocess.run(["systemctl", "restart", "caddy"], capture_output=True)
            die("caddy would not restart, so the previous configuration was restored and reloaded.")
        note("restarted")

    say("Restarting the stack, which is what applies APP_ORIGIN")
    if not restart_stack(account):
        die("the stack would not start. Check: docker compose logs backend")
    note("running")

    say("Checking names this box has never been told about")
    verify(domain, arguments.public_port, destination)

    print(f"""
This box now answers on any single name under {domain}, on {arguments.public_port} and
{destination}, and accepts an Origin from any of them. There is nothing per-instance left to
configure, so an image made from here comes up working on whatever name it is given.

  1. Open https://<this instance's name>/ from another machine and sign in.
  2. Snapshot. Every clone inherits this and needs no address of its own.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
