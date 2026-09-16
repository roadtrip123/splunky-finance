from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.schemas import Transaction

CATEGORY_ALIASES = {"restaurant": "restaurants", "dining": "restaurants", "food out": "restaurants"}


def month_shift(day: date, months: int):
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def previous_months(reference: date):
    end = reference.replace(day=1)
    start = month_shift(end, -1)
    return start, end, month_shift(start, -1), start


def spending(
    transactions: list[Transaction],
    start: date,
    end: date,
    category: str | None = None,
    account_id: str | None = None,
    compare_start: date | None = None,
    compare_end: date | None = None,
    top_count: int = 3,
):
    category = CATEGORY_ALIASES.get((category or "").lower(), (category or "").lower()) or None
    selected = [
        t
        for t in transactions
        if t.status == "posted"
        and start <= t.posted_date < end
        and (not category or t.category == category)
        and (not account_id or t.account_id == account_id)
    ]
    purchases = [t for t in selected if t.movement_type == "purchase" and t.amount_cents < 0]
    refunds = [t for t in selected if t.movement_type == "refund" and t.amount_cents > 0]
    purchases.sort(key=lambda t: (-abs(t.amount_cents), t.posted_date, t.id))
    result = {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "category": category,
        "total_cents": -sum(t.amount_cents for t in purchases) - sum(t.amount_cents for t in refunds),
        "purchase_count": len(purchases),
        "refund_count": len(refunds),
        "top_purchases": [t.model_dump(mode="json") for t in purchases[:top_count]],
    }
    if compare_start is not None and compare_end is not None:
        previous = spending(transactions, compare_start, compare_end, category, account_id, top_count=0)
        baseline = previous["total_cents"]
        delta = result["total_cents"] - baseline
        percent = (
            (Decimal(delta) * 100 / Decimal(baseline)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if baseline
            else None
        )
        result["comparison"] = {
            "previous_total_cents": baseline,
            "difference_cents": delta,
            "percentage": str(percent) if percent is not None else None,
            "status": "zero_baseline" if not baseline else "available",
        }
    return result


def money(cents: int):
    return f"{'-' if cents < 0 else ''}${abs(cents) // 100:,}.{abs(cents) % 100:02d} AUD"
