"""Offline browser test server only. This module is never used by Compose."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / "backend"), str(root / "backend/tests")]
from conftest import FakeModel, CUSTOMER_PASSWORD, ADMIN_PASSWORD
from app.config import Settings
from app.main import create_app

settings = Settings(
    _env_file=None,
    galileo_enabled=False,
    demo_password=CUSTOMER_PASSWORD,
    demo_admin_password=ADMIN_PASSWORD,
    session_secret="browser-test-only-secret-at-least-32-characters",
    openai_api_key="offline-test-key",
    data_dir=root / "runtime/browser-tests",
    policy_dir=root / "data/policies",
)
app = create_app(settings, model_builder=lambda s: FakeModel())
