"""Provision one isolated Splunky Finance stack per workshop participant.

Each participant gets their own compose project, so their dataset, sessions and Galileo
configuration are separate. That matters because the money-transfer scenario writes to the
ledger: on a shared instance one participant's transfer would move everyone's balance.

    python3 scripts/workshop.py up --count 50 --host 10.0.0.5
    python3 scripts/workshop.py list
    python3 scripts/workshop.py down --count 50

Participant settings that must differ (port, origin, session secret) are generated here.
Everything else is inherited from a base env file, so the LLM endpoint, passwords and dataset
seed stay identical across the room.
"""

import argparse
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "workshop"
PROJECT = "sf-p{n:02d}"
# Inherited from the base env unless listed here; these must differ per participant.
GENERATED = (
    "FRONTEND_PORT",
    "APP_ORIGIN",
    "SESSION_SECRET",
    "DEMO_MODE",
    "FRONTEND_BIND_ADDRESS",
    "SESSION_COOKIE_SECURE",
)
# Blanked rather than inherited: each participant connects their own Galileo project from the
# portal, so a fresh instance must not arrive holding the operator's credentials or defaults.
PARTICIPANT_SUPPLIES = (
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "GALILEO_API_KEY",
    "GALILEO_PROJECT",
    "GALILEO_LOG_STREAM",
    "GALILEO_CONSOLE_URL",
    "GALILEO_API_URL",
    "AGENT_CONTROL_URL",
)


def is_local_or_private(host):
    """Mirror the origin rule in config.py so a doomed provision fails before 50 stacks start."""
    from ipaddress import ip_address, ip_network

    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    networks = (ip_network("10.0.0.0/8"), ip_network("172.16.0.0/12"), ip_network("192.168.0.0/16"))
    return address.version == 4 and any(address in network for network in networks)


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


def participant_origin(template, host, port, index):
    """Exact origin the participant browses to, matched on every mutating request.

    Plain HTTP is rejected for anything but localhost and RFC1918 addresses, so a public
    deployment needs an https template pointing at a TLS proxy.
    """
    if template:
        return template.format(n=index, host=host, port=port)
    return f"http://{host}:{port}"


def participant_env(base, index, host, port, bind, mode, origin, existing=None):
    """Base settings plus the ones that must be unique, written newest-wins.

    A session secret already generated for this participant is kept. Rotating it on an update
    invalidates every signed cookie, so re-provisioning to deploy a new version would log the
    whole room out for no reason.
    """
    values = dict(base)
    for key in GENERATED:
        values.pop(key, None)
    for key in PARTICIPANT_SUPPLIES:
        values[key] = ""
    values.update(
        FRONTEND_PORT=str(port),
        FRONTEND_BIND_ADDRESS=bind,
        # Exact-origin matching rejects mutations whose Origin differs, port included. A wrong
        # value here fails every login with a CSRF error rather than anything more obvious.
        APP_ORIGIN=origin,
        SESSION_COOKIE_SECURE="true" if origin.startswith("https://") else "false",
        SESSION_SECRET=(existing or {}).get("SESSION_SECRET") or secrets.token_urlsafe(48),
        DEMO_MODE=mode,
    )
    header = f"# Splunky Finance workshop participant {index:02d}. Generated; do not edit by hand.\n"
    return header + "".join(f"{k}={v}\n" for k, v in values.items())


def write_env(path, text):
    if path.exists():
        path.unlink()
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "w") as stream:
        stream.write(text)


def compose(project, env_file, *arguments, dry_run=False):
    command = ["docker", "compose", "-p", project, "--env-file", str(env_file), *arguments]
    if dry_run:
        print("   " + " ".join(command))
        return 0
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        sys.stderr.write(f"{project}: {result.stderr.strip().splitlines()[-1:] or ['failed']}\n")
    return result.returncode


def projects_running():
    result = subprocess.run(
        ["docker", "compose", "ls", "--format", "json"], capture_output=True, text=True, check=False
    )
    if result.returncode:
        return []
    import json

    return [p for p in json.loads(result.stdout or "[]") if re.fullmatch(r"sf-p\d+", p.get("Name", ""))]


def command_up(args):
    base_path = ROOT / args.base_env
    if not base_path.exists():
        raise SystemExit(f"Base env {base_path} not found; run scripts/setup_env.py first")
    base = read_env(base_path)
    missing = [k for k in ("DEMO_PASSWORD", "DEMO_ADMIN_PASSWORD") if not base.get(k)]
    if missing:
        raise SystemExit(f"Base env is missing {', '.join(missing)}")
    ENV_DIR.mkdir(exist_ok=True)
    os.chmod(ENV_DIR, 0o700)

    # Build once. Every project shares the tagged image, so participants start rather than
    # rebuild identical source fifty times.
    if not args.skip_build:
        print("Building images once (first run on a fresh box takes a few minutes)...")
        if compose("sf-build", base_path, "build", dry_run=args.dry_run):
            raise SystemExit("Image build failed; fix that before provisioning")
        print("Images ready\n")

    print(f"Provisioning {args.count} participants from {args.base_env}\n")
    started, failed = [], []
    for index in range(1, args.count + 1):
        port = args.base_port + index
        project = PROJECT.format(n=index)
        env_file = ENV_DIR / f".env.p{index:02d}"
        origin = participant_origin(args.origin_template, args.host, port, index)
        existing = read_env(env_file) if env_file.exists() else {}
        write_env(
            env_file,
            participant_env(base, index, args.host, port, args.bind, args.mode, origin, existing),
        )
        code = compose(project, env_file, "up", "-d", "--no-build", dry_run=args.dry_run)
        (started if code == 0 else failed).append((index, port))
        print(f"  p{index:02d}  {origin}  {'ok' if code == 0 else 'FAILED'}")
        # Fifty Next.js and uvicorn processes starting at once is the one real CPU spike.
        if index < args.count and not args.dry_run:
            time.sleep(args.stagger)

    print(f"\n{len(started)} started, {len(failed)} failed")
    if failed:
        print("Failed: " + ", ".join(f"p{i:02d}" for i, _ in failed))
    print(f"\nCustomer login {base.get('DEMO_ACCOUNT_NUMBER', '12345678')} · presenter at /demo-admin")
    print(f"Participant env files in {ENV_DIR} (0600). They hold credentials; do not commit them.")


def command_down(args):
    running = {p["Name"] for p in projects_running()} if not args.dry_run else set()
    targets = [PROJECT.format(n=i) for i in range(1, args.count + 1)] if args.count else sorted(running)
    if not targets:
        print("No workshop projects found")
        return
    for project in targets:
        env_file = ENV_DIR / f".env.p{project.split('p')[-1]}"
        arguments = ["down", "-v"] if args.purge else ["down"]
        compose(project, env_file if env_file.exists() else "/dev/null", *arguments, dry_run=args.dry_run)
        print(f"  {project} stopped{' and volumes removed' if args.purge else ''}")
    if args.purge and not args.dry_run:
        for stale in ENV_DIR.glob(".env.p*"):
            stale.unlink()
        print(f"\nRemoved participant env files from {ENV_DIR}")


def command_list(args):
    running = projects_running()
    if not running:
        print("No workshop projects running")
        return
    print(f"{len(running)} workshop projects running\n")
    for project in sorted(running, key=lambda p: p["Name"]):
        env_file = ENV_DIR / f".env.p{project['Name'].split('p')[-1]}"
        origin = read_env(env_file).get("APP_ORIGIN", "?") if env_file.exists() else "?"
        print(f"  {project['Name']}  {origin}  {project.get('Status', '')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("up", "down", "list"))
    parser.add_argument("--count", type=int, default=0, help="Number of participants")
    parser.add_argument("--host", default="", help="Hostname or IP participants browse to")
    parser.add_argument("--bind", default="0.0.0.0", help="Address the host port binds to")
    parser.add_argument("--base-port", type=int, default=3100, help="Participant N listens on base+N")
    parser.add_argument("--base-env", default=".env", help="Env file supplying shared settings")
    parser.add_argument("--mode", default="workshop", help="DEMO_MODE for generated stacks")
    parser.add_argument("--stagger", type=float, default=2.0, help="Seconds between starts")
    parser.add_argument("--purge", action="store_true", help="With down: also delete volumes and env files")
    parser.add_argument(
        "--origin-template",
        default="",
        help="Origin per participant, e.g. https://p{n:02d}.demo.example.com. Defaults to "
        "http://HOST:PORT, which the app rejects on a public address.",
    )
    parser.add_argument("--skip-build", action="store_true", help="Images already built; start straight away")
    parser.add_argument("--dry-run", action="store_true", help="Print what would run, change nothing")
    args = parser.parse_args()

    if args.action == "up":
        if args.count < 1:
            raise SystemExit("--count is required for up")
        if not args.host:
            raise SystemExit("--host is required: participants browse to it and it must match APP_ORIGIN")
        sample = participant_origin(args.origin_template, args.host, args.base_port + 1, 1)
        if sample.startswith("http://") and not is_local_or_private(args.host):
            raise SystemExit(
                f"{sample} will be rejected: plain HTTP is only allowed for localhost and private "
                "LAN addresses. Put a TLS proxy in front and pass --origin-template "
                "https://p{n:02d}.your.domain (see scripts/Caddyfile.workshop)."
            )
        command_up(args)
    elif args.action == "down":
        command_down(args)
    else:
        command_list(args)


if __name__ == "__main__":
    main()
