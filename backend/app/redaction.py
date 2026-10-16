"""Masking key-shaped text out of anything that gets logged.

Error text from an SDK or a provider can quote the credential that was sent, and a log on a shared
box outlives the request. Shared between the provider path and the telemetry path, because both
log what they decline to show in the portal: the presenter password is published in this
repository, so curated sentences go on screen and the detail goes to the log.
"""

import re

# Anything key-shaped: OpenAI and Sharon AI prefixes, and a bearer header the SDK may quote back.
SECRET_SHAPED = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|tv-pat-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)")


def redact(text):
    return SECRET_SHAPED.sub("<redacted>", text)
