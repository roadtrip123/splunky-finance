"""Remove the port 443 redirect that makes a box unreachable while looking healthy.

The workshop image carries

    -A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443

in /etc/iptables/rules.v4, and netfilter-persistent restores it on every boot. Caddy binds 443, so
from inside the box everything is fine -- the listener is there, the containers are healthy, the
certificate is valid -- while every connection that arrives is bounced to a port nothing listens on.
From a browser the box is simply dead.

Deleting the live rule by hand does not survive a reboot, which is what made this look intermittent
rather than permanent. So this removes the rule from both places: the running nat table, and the
saved file that would otherwise restore it.

    sudo python3 scripts/fix_ports.py              # the live table; report on the saved file
    sudo python3 scripts/fix_ports.py --persist     # also strip it from /etc/iptables/rules.v4
    sudo python3 scripts/fix_ports.py --dry-run      # what it would do, changing nothing

Idempotent, and exits 0 having done nothing when there is no such rule, which is what makes it safe
to run from a unit on every boot. See scripts/splunky-finance-ports.service.
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

RULES = Path("/etc/iptables/rules.v4")
# Matched by what the rule does, not by how it is spelled: the saved copy carries `-m tcp`, a rule
# added by hand may not, and the destination port has varied between 8443 and others. Anything that
# redirects the HTTPS port somewhere else is the fault we are removing.
REDIRECT_443 = re.compile(r"--dport\s+443\b.*-j\s+REDIRECT")
# One pass deletes one rule per matching spec; duplicates existed on the first box we found this on.
MAX_PASSES = 10


def iptables(*arguments, check=True):
    return subprocess.run(
        ("iptables", "-t", "nat", *arguments), capture_output=True, text=True, check=check
    )


def offending(listing):
    return [line for line in listing.splitlines() if REDIRECT_443.search(line)]


def delete(spec):
    """Turn a line from `iptables -S` back into the deletion that removes it."""
    arguments = shlex.split(spec)
    if not arguments or arguments[0] != "-A":
        raise ValueError(f"not an append rule: {spec}")
    return iptables("-D", *arguments[1:], check=False)


def clean_live():
    removed, failures = 0, []
    for _ in range(MAX_PASSES):
        rules = offending(iptables("-S", "PREROUTING").stdout)
        if not rules:
            return removed, failures
        for rule in rules:
            result = delete(rule)
            if result.returncode:
                failures.append(f"{rule}: {result.stderr.strip()}")
                return removed, failures
            removed += 1
            print(f"  removed  {rule}")
    return removed, failures + [f"still present after {MAX_PASSES} passes"]


def clean_saved(persist):
    if not RULES.exists():
        print(f"  {RULES} does not exist; nothing restores the rule at boot")
        return 0
    lines = RULES.read_text().splitlines(keepends=True)
    keep = [line for line in lines if not REDIRECT_443.search(line)]
    count = len(lines) - len(keep)
    if not count:
        print(f"  {RULES} is clean")
        return 0
    if not persist:
        print(f"  {RULES} still holds the rule {count}x -- it will come back on the next boot.")
        print("  Re-run with --persist to remove it.")
        return count
    backup = RULES.with_name(RULES.name + ".bak")
    if not backup.exists():
        shutil.copy2(RULES, backup)
        print(f"  backed up {RULES} to {backup}")
    RULES.write_text("".join(keep))
    print(f"  removed {count} line(s) from {RULES}")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--persist", action="store_true",
                        help="also remove the rule from /etc/iptables/rules.v4")
    parser.add_argument("--dry-run", action="store_true",
                        help="report, change nothing (reading the nat table still needs root)")
    arguments = parser.parse_args()

    if arguments.dry_run:
        listing = iptables("-S", "PREROUTING", check=False)
        if listing.returncode:
            raise SystemExit(f"could not read the nat table: {listing.stderr.strip()}")
        rules = offending(listing.stdout)
        saved = offending(RULES.read_text()) if RULES.exists() else []
        print(f"live nat table : {len(rules)} redirect(s) of port 443")
        for rule in rules:
            print(f"  {rule}")
        print(f"{RULES} : {len(saved)} line(s)")
        return 0

    if os.geteuid() != 0:
        raise SystemExit("Needs root to edit the nat table. Re-run with sudo, or use --dry-run.")

    print("live nat table:")
    removed, failures = clean_live()
    if not removed and not failures:
        print("  no redirect of port 443; nothing to do")
    print("saved rules:")
    clean_saved(arguments.persist)

    if failures:
        # Reported rather than raised: a box that is already reachable must not fail to boot
        # because of a rule we could not parse.
        print("\nWARNING: could not remove every rule:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
