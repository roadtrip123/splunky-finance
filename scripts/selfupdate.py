"""Update to the newest release and start the stack. Runs unattended on boot.

An instance spun up for a workshop should not be carrying whatever code was baked into the AMI weeks
earlier, and rebuilding the AMI for every fix is the thing this avoids.

Two properties matter more than being up to date, because this runs with nobody watching on the
morning of a workshop:

  Never leave the box worse than it started. The build happens before anything is torn down, so a
  build that fails leaves the running stack untouched. A stack that comes up unhealthy is rolled back
  to the commit that was checked out on entry.

  Never block on the network. A failed fetch is logged and skipped; the stack starts on the code
  already present.

The default channel is tags rather than branch HEAD. A tag is a decision someone made; a branch tip
is whatever was pushed last, and fifty boxes pulling it at nine in the morning is fifty boxes
inheriting an unfinished commit. `--channel branch` is there when you want it.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "runtime" / "update"


def log(message):
    print(f"[selfupdate] {time.strftime('%H:%M:%S')} {message}", flush=True)


def run(*command, check=True, capture=True):
    result = subprocess.run(
        command, cwd=ROOT, check=False, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if check and result.returncode:
        output = (result.stdout or "").strip()
        raise RuntimeError(f"{' '.join(command)} failed ({result.returncode})\n{output}")
    return (result.stdout or "").strip(), result.returncode


def git(*arguments, **kwargs):
    return run("git", *arguments, **kwargs)


def write_state(directory, result, message="", channel=""):
    """Leave a record the presenter portal can read.

    Its presence is also how the portal knows a host side exists at all, so this is written on every
    outcome including the ones that changed nothing.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "ref": describe(),
            "commit": git("rev-parse", "--short", "HEAD")[0],
            "updated_at": time.time(),
            "result": result,
            "message": message,
            "channel": channel,
        }
        temporary = directory / "state.json.tmp"
        temporary.write_text(json.dumps(payload, indent=2))
        temporary.replace(directory / "state.json")
    except OSError as error:
        log(f"could not write state to {directory}: {error}")


def take_request(directory):
    """Remove the request file before acting on it, so a retrigger cannot loop."""
    path = directory / "request.json"
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        payload = None
    path.unlink(missing_ok=True)
    return payload


def env_defaults():
    """Read UPDATE_* keys from .env. Settings there already tolerate unknown keys."""
    path = ROOT / ".env"
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.fullmatch(r"(UPDATE_[A-Z_]+)=(.*)", line.strip())
            if match:
                values[match.group(1)] = match.group(2).strip()
    return values


def describe(ref="HEAD"):
    """Prefer a tag name, because that is what the changelog and the docs talk about."""
    tag, code = git("describe", "--tags", "--exact-match", ref, check=False)
    if not code:
        return tag
    short, _ = git("rev-parse", "--short", ref)
    return short


def newest_tag():
    tags, _ = git("tag", "--list", "v[0-9]*", "--sort=-v:refname")
    lines = [line for line in tags.splitlines() if line.strip()]
    return lines[0] if lines else None


def resolve_target(channel, branch):
    if channel == "branch":
        return f"origin/{branch}", branch
    tag = newest_tag()
    if not tag:
        raise RuntimeError("No v* tags found; use --channel branch")
    return tag, tag


def compose(*arguments, check=True):
    return run("docker", "compose", *arguments, check=check, capture=False)


def start(timeout):
    """Bring the stack up and wait for the healthchecks rather than for the API call to return."""
    return compose("up", "-d", "--wait", "--wait-timeout", str(timeout), check=False)[1]


def main():
    defaults = env_defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel",
        choices=("tags", "branch", "off"),
        default=defaults.get("UPDATE_CHANNEL", "tags"),
        help="tags: newest v* tag (default). branch: tip of --branch. off: start without updating",
    )
    parser.add_argument(
        "--branch",
        default=defaults.get("UPDATE_BRANCH", "build-splunky-finance"),
        help="Branch to follow when --channel branch",
    )
    parser.add_argument("--timeout", type=int, default=int(defaults.get("UPDATE_TIMEOUT", "300")),
                        help="Seconds to wait for containers to report healthy")
    parser.add_argument("--no-rollback", action="store_true",
                        help="Leave the new code in place even if the stack comes up unhealthy")
    parser.add_argument("--dry-run", action="store_true",
                        help="Say what would happen; touch nothing")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR,
                        help="Directory shared with the container for status and requests")
    parser.add_argument("--consume-request", action="store_true",
                        help="Act only if the portal has asked for an update, and clear the request")
    args = parser.parse_args()

    if args.consume_request:
        request = take_request(args.state_dir)
        if not request:
            log("no pending request; nothing to do")
            return 0
        log("update requested from the presenter portal")

    started_at = describe()
    log(f"currently on {started_at}")

    def finish(code, result, message=""):
        if not args.dry_run:
            write_state(args.state_dir, result, message, args.channel)
        return code

    if args.channel == "off":
        log("channel is off; starting without updating")
        return finish(0 if args.dry_run else start(args.timeout), "not_checked", "channel is off")

    # A dirty tree means someone edited this box by hand. Updating would discard that, so do not.
    dirty, _ = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        log("tracked files are modified; refusing to update and starting as-is")
        log(dirty)
        return finish(
            0 if args.dry_run else start(args.timeout), "skipped", "tracked files modified on this box"
        )

    _, code = git("fetch", "--tags", "--prune", "origin", check=False)
    if code:
        log("fetch failed; starting on the code already present")
        return finish(0 if args.dry_run else start(args.timeout), "offline", "could not reach origin")

    try:
        ref, label = resolve_target(args.channel, args.branch)
    except RuntimeError as error:
        log(f"{error}; starting as-is")
        return finish(0 if args.dry_run else start(args.timeout), "skipped", str(error))

    # `^{commit}` matters: rev-parse on an annotated tag yields the tag object, never equal to HEAD,
    # so without it every boot sees an update and rebuilds for nothing.
    target_sha, _ = git("rev-parse", f"{ref}^{{commit}}")
    head_sha, _ = git("rev-parse", "HEAD^{commit}")

    if target_sha == head_sha:
        log(f"{label} is already checked out; nothing to update")
        return finish(0 if args.dry_run else start(args.timeout), "current", f"{label} is current")

    log(f"update available: {started_at} -> {label}")
    if args.dry_run:
        log("dry run; stopping here")
        return 0

    git("-c", "advice.detachedHead=false", "checkout", "--quiet", ref)
    log(f"checked out {describe()}")

    # Build before anything is recreated. A failed build must leave the running stack alone, which is
    # the whole reason this is two steps rather than `up --build`.
    if compose("build", check=False)[1]:
        log("build failed; restoring previous code and starting it")
        git("-c", "advice.detachedHead=false", "checkout", "--quiet", head_sha)
        start(args.timeout)
        return finish(1, "build_failed", f"{label} did not build; kept {started_at}")

    if start(args.timeout) == 0:
        log(f"running {describe()}")
        return finish(0, "updated", f"{started_at} -> {label}")

    log("stack did not come up healthy")
    if args.no_rollback:
        log("--no-rollback given; leaving the new code in place")
        return finish(1, "unhealthy", f"{label} is unhealthy and was left in place")

    log(f"rolling back to {describe(head_sha)}")
    git("-c", "advice.detachedHead=false", "checkout", "--quiet", head_sha)
    if compose("build", check=False)[1] or start(args.timeout):
        log("rollback did not come up healthy either; this box needs a human")
        return finish(2, "broken", "neither the new release nor the rollback came up healthy")
    log(f"rolled back to {describe()}")
    return finish(1, "rolled_back", f"{label} was unhealthy; back on {started_at}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        log(str(error))
        sys.exit(2)
