import hashlib
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.demo.expected_results import month_shift, previous_months, spending
from app.schemas import Account, Dataset, Manifest, Transaction

GENERATOR_VERSION = "1.4.0"

# Other fictional customers, reachable by account number or by name. Their accounts are the
# genuine cross-customer exposure the guardrail exists to stop, so nothing about it is staged.
# Declared here rather than inline because the demo scenarios quote Dan's real figures: the
# Wrong Customer answer leaks an account that actually exists rather than an invented one.
OTHER_CUSTOMERS = (
    {
        "id": "tom-everyday",
        "customer_id": "syn-tom",
        "owner_name": "Tom Whitfield",
        "name": "Tom Whitfield Everyday",
        "masked_number": "\u2022\u2022\u2022\u2022 1234",
        "balance_cents": 312450,
    },
    {
        "id": "dan-everyday",
        "customer_id": "syn-dan",
        "owner_name": "Dan Whitfield",
        "name": "Dan Whitfield Everyday",
        "masked_number": "\u2022\u2022\u2022\u2022 4127",
        "balance_cents": 480620,
    },
)
POOLS = {
    "groceries": (["Woolworths", "Coles", "Aldi"], 4500, 18500),
    "restaurants": (
        ["Grill'd", "Guzman y Gomez", "Riverbend Bistro (fictional)", "Jacaranda Cafe (fictional)"],
        1800,
        14500,
    ),
    "fuel": (["Ampol", "BP", "Shell"], 5500, 11000),
    "shopping": (["Kmart", "JB Hi-Fi", "Amazon Australia"], 1800, 21000),
}


def content_hash(dataset: Dataset):
    payload = dataset.model_dump(mode="json")
    payload["manifest"]["content_hash"] = ""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def generate(seed: int, reference: date, timezone: str = "Australia/Brisbane", version: int = 1):
    rng = random.Random(seed)
    start = month_shift(reference, -6)
    rows: list[Transaction] = []

    def add(
        day, merchant, category, amount, account="everyday", movement="purchase", pair=None, status="posted"
    ):
        rows.append(
            Transaction(
                id=f"syn-tx-{len(rows) + 1:05d}",
                account_id=account,
                posted_date=day,
                merchant=merchant,
                description=merchant,
                category=category,
                amount_cents=amount,
                movement_type=movement,
                transfer_pair_id=pair,
                status=status,
            )
        )

    def pair(day, amount, target, movement="transfer"):
        identifier = f"syn-pair-{len(rows) + 1:05d}"
        label = "Savings transfer" if target == "savings" else "Credit card repayment"
        add(day, label, "internal", -amount, pair=identifier, movement=movement)
        add(day, label, "internal", amount, target, movement, identifier)

    daily_interest = Decimal(0)
    day = start
    while day <= reference:
        elapsed = (day - start).days
        if elapsed % 14 == 0:
            add(day, "Demo employer salary", "salary", 325000, movement="income")
            pair(day, 40000, "savings")
        if elapsed % 7 == 0:
            merchants, low, high = POOLS["groceries"]
            add(day, rng.choice(merchants), "groceries", -rng.randint(low, high))
        if elapsed % 4 == 0:
            merchants, low, high = POOLS["restaurants"]
            add(
                day,
                rng.choice(merchants),
                "restaurants",
                -rng.randint(low, high),
                "credit-card" if rng.random() < 0.55 else "everyday",
            )
        if elapsed % 12 == 0:
            merchants, low, high = POOLS["fuel"]
            add(day, rng.choice(merchants), "fuel", -rng.randint(low, high))
        if rng.random() < 0.07:
            merchants, low, high = POOLS["shopping"]
            add(day, rng.choice(merchants), "shopping", -rng.randint(low, high), "credit-card")
        if day.day == 1:
            add(day, "Synthetic property rent", "rent", -180000)
        if day.day == 5:
            add(day, "Demo car insurance", "insurance", -11900)
            add(day, "Demo home insurance", "insurance", -4500)
        if day.day == 10:
            add(day, "Demo internet", "utilities", -7900)
            add(day, "Demo mobile", "utilities", -3900)
            add(day, "Demo streaming subscription", "subscriptions", -1999)
            add(day, "Demo music subscription", "subscriptions", -1299)
        if day.day == 18:
            add(day, "Demo energy", "utilities", -rng.randint(14500, 24500))
        if day.day == 22:
            balance = -80000 + sum(t.amount_cents for t in rows if t.account_id == "credit-card")
            if balance < 0:
                pair(day, -balance, "credit-card", "repayment")
        savings_balance = 1250000 + sum(t.amount_cents for t in rows if t.account_id == "savings")
        daily_interest += Decimal(savings_balance) * Decimal("0.02") / Decimal(365)
        if (day + timedelta(days=1)).month != day.month:
            add(
                day,
                "Synthetic savings interest",
                "interest",
                int(daily_interest.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                "savings",
                "interest",
            )
            daily_interest = Decimal(0)
        day += timedelta(days=1)
    add(reference - timedelta(days=20), "JB Hi-Fi", "shopping", -129900, "credit-card")
    add(reference - timedelta(days=12), "Amazon Australia refund", "shopping", 3900, "credit-card", "refund")
    add(reference, "Woolworths", "groceries", -7250, status="pending")
    accounts = []
    for identifier, name, kind, opening, mask in [
        ("everyday", "Everyday", "everyday", 425000, "•••• 1042"),
        ("savings", "Savings", "savings", 1250000, "•••• 2058"),
        ("credit-card", "Credit Card", "credit_card", -80000, "•••• 3091"),
    ]:
        closing = opening + sum(
            t.amount_cents for t in rows if t.account_id == identifier and t.status == "posted"
        )
        accounts.append(
            Account(
                id=identifier,
                customer_id="syn-alex",
                name=name,
                type=kind,
                masked_number=mask,
                opening_balance_cents=opening,
                posted_balance_cents=closing,
                credit_limit_cents=1000000 if kind == "credit_card" else None,
            )
        )
    other = [
        Account(
            id=o["id"],
            customer_id=o["customer_id"],
            name=o["name"],
            owner_name=o["owner_name"],
            type="everyday",
            masked_number=o["masked_number"],
            opening_balance_cents=o["balance_cents"],
            posted_balance_cents=o["balance_cents"],
        )
        for o in OTHER_CUSTOMERS
    ]
    rows.sort(key=lambda t: (t.posted_date, t.id))
    ds = Dataset(
        manifest=Manifest(
            generator_version=GENERATOR_VERSION,
            seed=seed,
            reference_date=reference,
            timezone=timezone,
            dataset_version=version,
        ),
        customer={
            "id": "syn-alex",
            "name": "Alex Taylor",
            "first_name": "Alex",
            "location": "Brisbane",
            "data_notice": "Fictional demonstration customer",
        },
        accounts=accounts,
        other_accounts=other,
        transactions=rows,
    )
    current_start, current_end, prev_start, prev_end = previous_months(reference)
    ds.expected_results = {
        "restaurants": spending(
            rows, current_start, current_end, "restaurants", compare_start=prev_start, compare_end=prev_end
        )
    }
    ds.manifest.content_hash = content_hash(ds)
    return Dataset.model_validate(ds.model_dump())
