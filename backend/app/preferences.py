"""Presenter preferences: settings that outlive a restart and are not credentials.

Deliberately not in galileo-settings.json. `_persist` there rebuilds the saved document from
scratch on every write, so a key added from elsewhere would be silently dropped on the next
connection change, and scripts/reset_for_snapshot.sh destroys that file to remove credentials. A
preference belongs to neither job.

It lives on the runtime volume, which means a clone of the image starts with the defaults. That is
what "off by default" has to mean for an image stamped a hundred times: not off in the source, off
on every box that boots from it.
"""

import json
from pathlib import Path

# Every preference and its default. A name absent from here cannot be set, so a typo from the
# portal is a 422 rather than a key nothing ever reads.
DEFAULTS = {"demo_chip": False}


class Preferences:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "presenter-settings.json"

    def all(self):
        """Defaults, overlaid with whatever on disk is of the right type.

        A hand-edited file with a string where a bool belongs falls back to the default rather than
        reaching a template as "false", which renders as enabled.
        """
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError, TypeError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        return {
            name: saved[name] if type(saved.get(name)) is type(default) else default
            for name, default in DEFAULTS.items()
        }

    def set(self, name, value):
        if name not in DEFAULTS:
            raise KeyError(name)
        if type(value) is not type(DEFAULTS[name]):
            raise TypeError(name)
        current = {**self.all(), name: value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current))
        temporary.replace(self.path)
        return current
