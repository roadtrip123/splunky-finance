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
    "splunky-finance-update.service",
    "splunky-finance-update.path",
)


def owner():
    """Who should run the units: the user who invoked sudo, not root."""
    name = os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name
    if name == "root":
        raise SystemExit(
            "Refusing to install units that run as root. Run this with sudo from the account that "
            "owns the repository and is in the docker group."
        )
    return name


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
    args = parser.parse_args()

    if os.geteuid() != 0 and not args.dry_run:
        raise SystemExit("Needs root to write /etc/systemd/system. Re-run with sudo.")

    user = owner()
    state_dir = ROOT / "runtime" / "update"
    print(f"repository  {ROOT}")
    print(f"runs as     {user}")
    print(f"state dir   {state_dir}")

    if args.dry_run:
        for unit in UNITS:
            print(f"\n--- {unit} ---")
            print(substitute((ROOT / "scripts" / unit).read_text(), user, state_dir))
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
    subprocess.run(["systemctl", "enable", "--now", "splunky-finance-update.path"], check=True)
    print("\nenabled: splunky-finance.service (on boot), splunky-finance-update.path (watching)")

    if args.build:
        print("\nrunning the first update now; this builds the images and takes a few minutes\n")
        return subprocess.run(
            ["sudo", "-u", user, sys.executable, "scripts/selfupdate.py"], cwd=ROOT, check=False
        ).returncode

    print("\nNext, build and start it with the output visible:")
    print(f"  python3 scripts/selfupdate.py")
    print("Afterwards:")
    print("  journalctl -u splunky-finance -u splunky-finance-update -f")
    return 0


if __name__ == "__main__":
    sys.exit(main())
