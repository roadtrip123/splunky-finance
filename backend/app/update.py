"""Check for a newer release, and ask the host to install it.

The backend runs in a container with no git and no Docker socket, and deliberately so. Mounting the
Docker socket would let anyone holding the presenter password reach root on the host -- and that
password is published in this repository, read aloud at workshops, and identical on every box. So the
container's whole capability here is to write one file. A host-side systemd unit watches for it and
performs the update itself, which keeps the worst case at "someone triggered a pull of a tag from the
project's own repository" rather than "someone owns the instance".

`scripts/selfupdate.py` writes the state file after every run, so its presence is also how this knows
whether the host side is installed at all.
"""

import json
import os
import re
import time
from pathlib import Path

import httpx

SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CHECK_CACHE_SECONDS = 60


def version_key(tag):
    match = SEMVER.match(tag)
    return tuple(int(part) for part in match.groups()) if match else None


class Updates:
    def __init__(self, state_dir, repo, timeout=10.0, transport=None):
        self.dir = Path(state_dir)
        self.repo = repo
        self.timeout = timeout
        # Injected by the tests so the GitHub call can be exercised without a network.
        self.transport = transport
        self._latest = None
        self._checked_at = 0.0
        self._error = None

    @property
    def state_path(self):
        return self.dir / "state.json"

    @property
    def request_path(self):
        return self.dir / "request.json"

    def state(self):
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def current(self):
        """The release this box is running.

        The state file is authoritative because the host script writes it after checking out. The
        build argument is the fallback for a stack started by hand with plain compose.
        """
        return self.state().get("ref") or os.environ.get("APP_VERSION") or "unknown"

    def control(self):
        """Whether the host side can act, and if not, precisely why."""
        if not self.dir.is_dir():
            return "unavailable", f"{self.dir} is not mounted into the container"
        if not os.access(self.dir, os.W_OK):
            return "unavailable", f"{self.dir} is not writable by the backend user (uid 10001)"
        if not self.state_path.exists():
            return "unavailable", "scripts/splunky-finance.service is not installed on the host"
        return "available", None

    async def check(self, force=False):
        """Newest v* tag on GitHub. Cached, because the status panel polls."""
        if not force and self._latest and time.time() - self._checked_at < CHECK_CACHE_SECONDS:
            return self._latest
        url = f"https://api.github.com/repos/{self.repo}/tags?per_page=100"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get(url, headers={"Accept": "application/vnd.github+json"})
                response.raise_for_status()
                tags = response.json()
        except Exception as error:  # noqa: BLE001 - any failure here is "could not check"
            self._error = f"{type(error).__name__}: {error}"[:200]
            self._checked_at = time.time()
            return self._latest
        # Sorted here rather than trusting the API's order, which is not by version.
        versions = sorted(
            (key, tag["name"]) for tag in tags if (key := version_key(tag.get("name", "")))
        )
        self._latest = versions[-1][1] if versions else None
        self._error = None if versions else "No v* tags found"
        self._checked_at = time.time()
        return self._latest

    def request(self):
        """Ask the host to update. Idempotent: a pending request is not duplicated."""
        state, reason = self.control()
        if state != "available":
            raise RuntimeError(reason)
        payload = {"requested_at": time.time(), "by": "presenter"}
        temporary = self.request_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload))
        temporary.replace(self.request_path)
        return payload

    def pending(self):
        try:
            return json.loads(self.request_path.read_text())
        except (OSError, ValueError):
            return None

    async def view(self, force=False):
        latest = await self.check(force=force)
        current = self.current()
        control, reason = self.control()
        current_key, latest_key = version_key(current), version_key(latest or "")
        return {
            "current": current,
            "latest": latest,
            # Only claim an update when both sides parse as versions and the newer one is newer. An
            # unknown current version must not read as "up to date".
            "update_available": bool(
                current_key and latest_key and latest_key > current_key
            ),
            "comparable": bool(current_key and latest_key),
            "control": control,
            "control_reason": reason,
            "checked_at": self._checked_at or None,
            "check_error": self._error,
            "pending": self.pending(),
            "last_run": self.state(),
            "repo": self.repo,
        }
