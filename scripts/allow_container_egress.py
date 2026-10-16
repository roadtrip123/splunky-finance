"""Keep container outbound HTTPS off the port 443 redirect, and keep it that way across a reboot.

The lab image redirects arriving port 443 to 8443. PREROUTING catches traffic arriving on *any*
interface, the Docker bridges included, so a container's own outbound HTTPS is redirected too: it
leaves the backend bound for Galileo and lands on whatever listens on 8443 locally, which since the
proxy was made to serve both ports is this application. The SDK then reports

    [SSL: CERTIFICATE_VERIFY_FAILED] Hostname mismatch, certificate is not valid for
    'api.multitenant.galileocloud.io'

which carries no status code, so it reads as a generic connection failure and sends a presenter
looking at credentials that were always fine.

The fix is one RETURN rule per bridge, ahead of the redirect. install.sh already inserts them when
its egress probe fails, and warns that they do not survive a reboot. This persists them into
/etc/iptables/rules.v4, ahead of the redirect line, so netfilter-persistent restores them with
everything else. That mechanism is known to work on these images, because it is what restores the
redirect itself every boot.

    sudo python3 scripts/allow_container_egress.py --dry-run     what it would do, changing nothing
    sudo python3 scripts/allow_container_egress.py

Idempotent, and it verifies from inside the running container rather than from the host: traffic the
host originates goes through OUTPUT and never meets PREROUTING, so a check run on the host passes
whether or not containers are affected.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = Path("/etc/iptables/rules.v4")
# docker0 is the default bridge; br+ is an interface-name prefix match, covering the br-xxxxxxx
# bridges compose creates per project.
BRIDGES = ("docker0", "br+")
REDIRECT = re.compile(r"--dport\s+(?P<dport>\d+)\b.*-j\s+REDIRECT")


def say(message):
    print(f"\n\033[1m==> {message}\033[0m")


def note(message):
    print(f"    {message}")


def warn(message):
    print(f"    \033[1;33m{message}\033[0m")


def die(message):
    print(f"\n\033[1;31mFAILED: {message}\033[0m", file=sys.stderr)
    raise SystemExit(1)


def rule(bridge, port):
    return ["PREROUTING", "-i", bridge, "-p", "tcp", "--dport", str(port), "-j", "RETURN"]


def saved_line(bridge, port):
    return f"-A PREROUTING -i {bridge} -p tcp -m tcp --dport {port} -j RETURN\n"


def present(bridge, port):
    return (
        subprocess.run(
            ["iptables", "-t", "nat", "-C", *rule(bridge, port)], capture_output=True
        ).returncode
        == 0
    )


def insert(bridge, port):
    """At position 1, so it is read before the redirect whatever else is in the chain."""
    return subprocess.run(
        ["iptables", "-t", "nat", "-I", "PREROUTING", "1", *rule(bridge, port)[1:]],
        capture_output=True,
        text=True,
    )


def persist(port, dry_run, rules=RULES):
    """Write the bypasses into the saved ruleset, ahead of the redirect.

    Ordering is the whole point: iptables-restore applies the file top to bottom, so a RETURN after
    the REDIRECT would never be reached. Inserted immediately before the first redirect of this
    port, or, where the file has none, after the nat table's chain declarations.
    """
    if not rules.exists():
        warn(f"{rules} does not exist, so nothing restores rules at boot on this box.")
        warn("The live fix above holds until the next reboot. Persist it however this image does.")
        return 0
    lines = rules.read_text().splitlines(keepends=True)
    wanted = [saved_line(bridge, port) for bridge in BRIDGES]
    missing = [line for line in wanted if line not in lines]
    if not missing:
        note(f"{rules} already restores the bypasses")
        return 0
    position, in_nat = None, False
    for index, line in enumerate(lines):
        if line.startswith("*nat"):
            in_nat = True
            position = index + 1
            continue
        if not in_nat:
            continue
        if line.startswith("*") or line.startswith("COMMIT"):
            break
        if line.startswith(":"):
            position = index + 1
        match = REDIRECT.search(line)
        if match and int(match.group("dport")) == port:
            position = index
            break
    if position is None:
        warn(f"{rules} has no nat table; not editing it.")
        return 0
    if dry_run:
        for line in missing:
            note(f"would add at line {position + 1}: {line.strip()}")
        return len(missing)
    backup = rules.with_name(rules.name + ".bak")
    if not backup.exists():
        shutil.copy2(rules, backup)
        note(f"backed up {rules} to {backup}")
    lines[position:position] = missing
    rules.write_text("".join(lines))
    for line in missing:
        note(f"added to {rules}: {line.strip()}")
    return len(missing)


def verify(account):
    """From inside the container, because that is the only path the redirect affects.

    A hostname mismatch here is the fault itself: the request reached a local listener holding a
    certificate for something else. An HTTP status of any kind means it arrived where it was sent.
    """
    probe = (
        "import urllib.error,urllib.request\n"
        "try:\n"
        "    r=urllib.request.urlopen('https://api.openai.com/v1/models',timeout=15)\n"
        "    print('reached, HTTP', r.status)\n"
        "except urllib.error.HTTPError as e:\n"
        "    print('reached, HTTP', e.code)\n"
        "except Exception as e:\n"
        "    print(type(e).__name__, e)\n"
    )
    result = subprocess.run(
        ["sudo", "-u", account, "docker", "compose", "--project-directory", str(ROOT),
         "exec", "-T", "backend", "python3", "-c", probe],
        capture_output=True, text=True,
    )
    answer = (result.stdout or result.stderr).strip().splitlines()
    if not answer:
        warn("could not run the probe in the backend container; check it is running")
        return
    line = answer[-1]
    note(f"container egress: {line}")
    if "reached" in line:
        note("a status of any kind means the request arrived where it was addressed")
    elif "CERTIFICATE_VERIFY_FAILED" in line or "Hostname mismatch" in line:
        warn("still hijacked: the request is reaching a local listener, not the internet.")
        warn("Check the rule order: sudo iptables -t nat -S PREROUTING")
    else:
        warn("not a certificate fault, so this is a different problem from the redirect.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    parser.add_argument("--port", type=int, default=443, help="the redirected port to bypass")
    parser.add_argument("--rules", type=Path, default=RULES, help="the saved ruleset to edit")
    arguments = parser.parse_args()

    if not arguments.dry_run and os.geteuid() != 0:
        die("Needs root to edit the nat table. Re-run with sudo, or use --dry-run.")
    account = os.environ.get("SUDO_USER", "")
    if not arguments.dry_run and (not account or account == "root"):
        die("Run with sudo from the account that owns this repository, not as root directly.")

    say(f"Bypassing the port {arguments.port} redirect for container traffic")
    added = 0
    for bridge in BRIDGES:
        if present(bridge, arguments.port):
            note(f"{bridge:8} already bypassed")
            continue
        if arguments.dry_run:
            note(f"{bridge:8} would be bypassed")
            added += 1
            continue
        result = insert(bridge, arguments.port)
        if result.returncode:
            # Reported rather than fatal: docker0 exists on every box, br+ is a prefix match that
            # some kernels reject if no such interface exists yet, and one bridge fixed is better
            # than none.
            warn(f"{bridge:8} could not be added: {result.stderr.strip()}")
            continue
        note(f"{bridge:8} bypassed")
        added += 1
    if not added and not arguments.dry_run:
        note("nothing to add to the live table")

    say("Making it survive a reboot")
    persist(arguments.port, arguments.dry_run, arguments.rules)

    if arguments.dry_run:
        note("--dry-run: nothing was written")
        return 0

    say("Checking from inside the container")
    verify(account)

    print("""
If the probe reached anything, retry the observability connection in the portal. The log line to
read either way is:

  docker compose logs backend --tail 50 | grep -i "connection failed"
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
