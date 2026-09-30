import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock

from app.demo.generator import GENERATOR_VERSION, content_hash, generate
from app.schemas import Dataset


class Storage:
    def __init__(self, settings):
        self.settings = settings
        self.directory = Path(settings.data_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "dataset.json"
        self.lock = FileLock(str(self.path) + ".lock")
        self.error: str | None = None
        self.dataset: Dataset | None = None
        try:
            with self.lock:
                if self.path.exists() and not self._built_by_older_generator():
                    self.dataset = self.read()
                else:
                    self.dataset = generate(
                        settings.demo_seed, settings.demo_reference_date, settings.demo_timezone
                    )
                    self.write(self.dataset)
        except (ValueError, OSError):
            self.error = (
                "Dataset is corrupt or unavailable; restore a valid file or use confirmed admin reset"
            )

    def _built_by_older_generator(self):
        """True when the stored file was produced by a different generator version.

        A dataset is rebuilt on an upgrade rather than validated against the current code. Adding
        a field changes the content hash of every stored file, so without this an upgrade would
        look like corruption and every existing instance would refuse to start. The rebuild is
        deterministic from the same seed and reference date, so the figures participants were
        given do not move; only uncommitted demo state such as a transfer is discarded.

        A missing or unreadable version is corruption, not an upgrade, and still fails visibly.
        """
        try:
            version = json.loads(self.path.read_text())["manifest"]["generator_version"]
        except (OSError, ValueError, TypeError, KeyError):
            return False
        return isinstance(version, str) and bool(version) and version != GENERATOR_VERSION

    def read(self):
        dataset = Dataset.model_validate_json(self.path.read_text())
        if content_hash(dataset) != dataset.manifest.content_hash:
            raise ValueError("Dataset hash mismatch")
        return dataset

    def write(self, dataset):
        Dataset.model_validate(dataset.model_dump())
        if content_hash(dataset) != dataset.manifest.content_hash:
            raise ValueError("Dataset hash mismatch")
        payload = json.dumps(dataset.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix="dataset-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.directory, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def reset(self, expected_version, seed=None, reference=None):
        with self.lock:
            current = self.read() if self.dataset is not None else None
            version = current.manifest.dataset_version if current else 0
            if expected_version != version:
                raise ValueError("Dataset version changed")
            settings = self.settings
            ds = generate(
                seed if seed is not None else current.manifest.seed if current else settings.demo_seed,
                reference
                if reference is not None
                else current.manifest.reference_date
                if current
                else settings.demo_reference_date,
                settings.demo_timezone,
                version + 1,
            )
            self.write(ds)
            self.dataset, self.error = ds, None
            return ds
