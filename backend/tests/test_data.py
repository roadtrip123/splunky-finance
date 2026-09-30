import json
from datetime import date

import pytest

from app.demo.expected_results import previous_months, spending
from app.demo.generator import GENERATOR_VERSION, generate
from app.schemas import Dataset, Transaction
from app.storage import Storage


def test_reproducible_reconciled_persistent(settings):
    a = generate(42, date(2026, 9, 15))
    assert a.model_dump_json() == generate(42, date(2026, 9, 15)).model_dump_json()
    assert a.manifest.content_hash != generate(43, date(2026, 9, 15)).manifest.content_hash
    assert a.manifest.content_hash != generate(42, date(2026, 9, 16)).manifest.content_hash
    truth = a.expected_results["restaurants"]
    assert truth["purchase_count"] >= 3 and len({t["id"] for t in truth["top_purchases"]}) == 3
    assert truth["comparison"]["previous_total_cents"] > 0
    storage = Storage(settings)
    before = storage.path.read_bytes()
    assert Storage(settings).path.read_bytes() == before
    reset = storage.reset(1)
    assert reset.manifest.dataset_version == 2 and reset.manifest.seed == 42
    assert reset.manifest.reference_date == settings.demo_reference_date
    with pytest.raises(ValueError):
        storage.reset(1)


def test_corruption_not_regenerated(settings):
    storage = Storage(settings)
    storage.path.write_text('{"broken": true}')
    after = Storage(settings)
    assert after.dataset is None and after.error
    assert after.path.read_text() == '{"broken": true}'
    assert after.reset(0).manifest.dataset_version == 1


def test_older_generator_version_regenerates(settings):
    """A dataset built by an earlier shape is rebuilt, not reported as corrupt.

    Adding a field changes the content hash of every stored dataset, so without this an upgrade
    bricks every existing instance with the corruption message.
    """
    storage = Storage(settings)
    stored = json.loads(storage.path.read_text())
    stored["manifest"]["generator_version"] = "0.0.1"
    storage.path.write_text(json.dumps(stored))
    after = Storage(settings)
    assert after.error is None
    assert after.dataset.manifest.generator_version == GENERATOR_VERSION


def test_invalid_ledger_and_duplicate_ids():
    ds = generate(42, date(2026, 9, 15)).model_dump()
    ds["accounts"][0]["posted_balance_cents"] += 1
    with pytest.raises(ValueError):
        Dataset.model_validate(ds)
    ds = generate(42, date(2026, 9, 15)).model_dump()
    ds["transactions"].append(ds["transactions"][0])
    with pytest.raises(ValueError):
        Dataset.model_validate(ds)


def tx(identifier, day, amount, movement="purchase", status="posted"):
    return Transaction(
        id=identifier,
        account_id="everyday",
        posted_date=date.fromisoformat(day),
        merchant="Test",
        description="Test",
        category="restaurants",
        amount_cents=amount,
        movement_type=movement,
        status=status,
    )


def test_boundaries_refunds_exclusions_ties_zero_baseline():
    assert previous_months(date(2026, 1, 15)) == (
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2025, 11, 1),
        date(2025, 12, 1),
    )
    rows = [
        tx("b", "2026-08-01", -1000),
        tx("a", "2026-08-01", -1000),
        tx("c", "2026-08-31", -500),
        tx("refund", "2026-08-20", 200, "refund"),
        tx("exclusive", "2026-09-01", -8000),
        tx("pending", "2026-08-15", -9000, status="pending"),
        tx("repayment", "2026-08-16", -7000, "repayment"),
        tx("transfer", "2026-08-17", -6000, "transfer"),
    ]
    result = spending(
        rows,
        date(2026, 8, 1),
        date(2026, 9, 1),
        "dining",
        compare_start=date(2026, 7, 1),
        compare_end=date(2026, 8, 1),
    )
    assert result["total_cents"] == 2300 and result["purchase_count"] == 3 and result["refund_count"] == 1
    assert [t["id"] for t in result["top_purchases"]] == ["a", "b", "c"]
    assert result["comparison"]["percentage"] is None
