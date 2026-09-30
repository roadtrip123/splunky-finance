from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Account(StrictModel):
    id: str
    customer_id: str
    type: Literal["everyday", "savings", "credit_card"]
    name: str
    masked_number: str
    # Only set on another customer's account, where there is no customer record to read a name
    # from. The authenticated customer's own name comes from `Dataset.customer`.
    owner_name: str | None = None
    currency: Literal["AUD"] = "AUD"
    opening_balance_cents: int
    posted_balance_cents: int
    credit_limit_cents: int | None = None


class Transaction(StrictModel):
    id: str
    account_id: str
    posted_date: date
    merchant: str
    description: str
    category: str
    amount_cents: int
    currency: Literal["AUD"] = "AUD"
    status: Literal["posted", "pending"] = "posted"
    movement_type: Literal[
        "purchase", "refund", "transfer", "repayment", "income", "interest", "fee", "external_transfer"
    ]
    transfer_pair_id: str | None = None


class Manifest(StrictModel):
    schema_version: int = 1
    generator_version: str
    seed: int
    reference_date: date
    timezone: str
    dataset_version: int
    content_hash: str = ""


class Dataset(StrictModel):
    manifest: Manifest
    customer: dict[str, str]
    accounts: list[Account]
    # Accounts belonging to other fictional customers. Deliberately reachable by account number,
    # so the guardrail has a real cross-customer exposure to prevent rather than a staged one.
    # Kept out of `accounts` so the authenticated customer's ledger still reconciles exactly.
    other_accounts: list[Account] = Field(default_factory=list)
    transactions: list[Transaction]
    expected_results: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def ledger(self):
        ids = [x.id for x in self.transactions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate transaction IDs")
        accounts = {a.id: a for a in self.accounts}
        if len(accounts) != 3 or {a.type for a in self.accounts} != {"everyday", "savings", "credit_card"}:
            raise ValueError("Dataset needs three distinct product accounts")
        pairs: dict[str, list[Transaction]] = {}
        for t in self.transactions:
            if t.account_id not in accounts or t.posted_date > self.manifest.reference_date:
                raise ValueError("Invalid transaction account/date")
            if t.transfer_pair_id:
                pairs.setdefault(t.transfer_pair_id, []).append(t)
            if t.movement_type in ("transfer", "repayment") and not t.transfer_pair_id:
                raise ValueError("Internal movements require a pair")
        for a in self.accounts:
            total = a.opening_balance_cents + sum(
                t.amount_cents for t in self.transactions if t.account_id == a.id and t.status == "posted"
            )
            if total != a.posted_balance_cents or a.customer_id != self.customer["id"]:
                raise ValueError("Ledger/customer reconciliation failed")
        for pair in pairs.values():
            if (
                len(pair) != 2
                or pair[0].account_id == pair[1].account_id
                or sum(t.amount_cents for t in pair) != 0
                or pair[0].posted_date != pair[1].posted_date
                or pair[0].status != pair[1].status
            ):
                raise ValueError("Invalid internal transfer pair")
        return self


class Login(StrictModel):
    account_number: str = Field(default="", max_length=40)
    password: str = Field(min_length=1, max_length=256)


class ChatInput(StrictModel):
    demo_version: str | None = Field(default=None, max_length=100)
    message: str = Field(min_length=1, max_length=3000)
    conversation_id: str | None = Field(default=None, max_length=80)


class RunSetting(StrictModel):
    run_id: str = Field(max_length=80)
    expected_revision: int = Field(ge=0)


class ScenarioSetting(RunSetting):
    scenario_id: str = Field(max_length=80)


class ProtectionSetting(RunSetting):
    enabled: bool


class DatasetReset(StrictModel):
    confirmed: bool
    expected_version: int
    seed: int | None = None
    reference_date: date | None = None
