"""Install the systemd units that update this box and serve the portal's update button.

The units in `scripts/` carry defaults for a stock Ubuntu AMI -- user `ubuntu`, repository at
`/home/ubuntu/splunky-finance`. A box where either differs would install them, report success, and
never work: a path unit watching a directory that does not exist stays quiet, and `systemctl status`
shows a unit that has simply never triggered. So the paths are substituted here from where this script
actually is and who actually owns it, rather than documented as something to remember.

    sudo python3 scripts/install_service.py

Add --build to run the first update in the foreground afterwards, so the image build's output is
visible rather than buried in the journal.
"""

import argparse
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_DIR = Path("/etc/systemd/system")
# The gid the backend container runs as; see backend/Dockerfile. The shared directory is group-owned
# by it so the container can write a request, and user-owned by the account running the units so the
# host can write the state file. Giving it to the container outright locks the host out of its own
# directory, which presents as selfupdate.py failing to record what it did.
CONTAINER_GID = 10001
SHARED_MODE = 0o770
UNITS = (
    "splunky-finance.service",
    "splunky-finance-ports.service",
    "splunky-finance-egress.service",
    "splunky-finance-egress.timer",
    "splunky-finance-update.service",
    "splunky-finance-update.path",
)


def owner(units_only=False):
    """Who should run the units: the user who invoked sudo, not root.

    At boot there is no invoking account. `splunky-finance.service` refreshes the unit files
    through `--units-only` as root, so there the account is taken from whoever owns the checkout,
    which is the same answer by a different route. Refusing there would fail the step that exists
    to keep the units current.
    """
    name = os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name
    if name != "root":
        return name
    if units_only:
        from_checkout = pwd.getpwuid(ROOT.stat().st_uid).pw_name
        if from_checkout != "root":
            return from_checkout
    raise SystemExit(
        "Refusing to install units that run as root. Run this with sudo from the account that "
        "owns the repository and is in the docker group."
    )


def substitute(text, user, state_dir):
    text = re.sub(r"(?m)^User=.*$", f"User={user}", text)
    text = re.sub(r"(?m)^WorkingDirectory=.*$", f"WorkingDirectory={ROOT}", text)
    text = re.sub(r"(?m)^PathExists=.*$", f"PathExists={state_dir / 'request.json'}", text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true",
                        help="Run the first update in the foreground, with the build output visible")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change")
    parser.add_argument("--units-only", action="store_true",
                        help="Write and reload the unit files, nothing else. For the boot refresh")
    args = parser.parse_args()

    if os.geteuid() != 0 and not args.dry_run:
        raise SystemExit("Needs root to write /etc/systemd/system. Re-run with sudo.")

    user = owner(args.units_only)
    state_dir = ROOT / "runtime" / "update"
    print(f"repository  {ROOT}")
    print(f"runs as     {user}")
    print(f"state dir   {state_dir}")

    if args.dry_run:
        for unit in UNITS:
            print(f"\n--- {unit} ---")
            print(substitute((ROOT / "scripts" / unit).read_text(), user, state_dir))
        return 0

    if args.units_only:
        changed = []
        for unit in UNITS:
            target = UNIT_DIR / unit
            wanted = substitute((ROOT / "scripts" / unit).read_text(), user, state_dir)
            if not target.exists() or target.read_text() != wanted:
                target.write_text(wanted)
                changed.append(unit)
        if not changed:
            print("units already current")
            return 0
        print("refreshed: " + ", ".join(changed))
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        # Enabled, not started: a unit added by a later release is useless unenabled, and a boot
        # refresh must not restart the stack underneath the update that is about to run.
        for unit in ("splunky-finance.service", "splunky-finance-ports.service",
                     "splunky-finance-egress.timer", "splunky-finance-update.path"):
            subprocess.run(["systemctl", "enable", unit], check=False)
        print("a changed unit takes effect on the next boot; systemd has already loaded this one")
        return 0

    # Must exist and be writable by the container before compose mounts it, or Docker creates it
    # root-owned and the portal's button is absent.
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chown(state_dir, pwd.getpwnam(user).pw_uid, CONTAINER_GID)
    state_dir.chmod(SHARED_MODE)
    print(f"created {state_dir}, owned by {user}:{CONTAINER_GID} mode {oct(SHARED_MODE)}")

    for unit in UNITS:
        target = UNIT_DIR / unit
        target.write_text(substitute((ROOT / "scripts" / unit).read_text(), user, state_dir))
        print(f"wrote {target}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    # The .service units are triggered -- one by boot, one by the path unit -- so only the boot
    # service and the watcher are enabled. Enabling the triggered one would run it at boot with no
    # request pending, which does nothing but muddy the journal.
    subprocess.run(["systemctl", "enable", "splunky-finance.service"], check=True)
    # Enabled like the boot service, because boot is what triggers it. `--now` as well: a box being
    # installed may be carrying the redirect at this moment, and the installer should not leave it.
    subprocess.run(["systemctl", "enable", "--now", "splunky-finance-ports.service"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "splunky-finance-update.path"], check=True)
    # The timer is what is enabled, not the service it triggers. `--now` starts the timer, which
    # does not run the service, so the service is started once here as well: a box being installed
    # may have the redirect above the bypasses at this moment and should not be left that way.
    subprocess.run(["systemctl", "enable", "--now", "splunky-finance-egress.timer"], check=True)
    subprocess.run(["systemctl", "start", "splunky-finance-egress.service"], check=False)
    print(
        "\nenabled: splunky-finance.service (on boot), splunky-finance-ports.service (on boot, "
        "before it), splunky-finance-egress.timer (boot, then every few minutes), "
        "splunky-finance-update.path (watching)"
    )

    if args.build:
        print("\nrunning the first update now; this builds the images and takes a few minutes\n")
        return subprocess.run(
            ["sudo", "-u", user, sys.executable, "scripts/selfupdate.py"], cwd=ROOT, check=False
        ).returncode

    print("\nNext, build and start it with the output visible:")
    print(f"  python3 scripts/selfupdate.py")
    print("Afterwards:")
    print("  journalctl -u splunky-finance -u splunky-finance-ports -u splunky-finance-egress"
          " -u splunky-finance-update -f")
    return 0


if __name__ == "__main__":
    sys.exit(main())
