import re
from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import ConfigDict, Field

from app.demo.expected_results import CATEGORY_ALIASES, spending
from app.demo.generator import content_hash
from app.schemas import Transaction


class Banking:
    def __init__(self, dataset, policies: Path, storage=None):
        self.dataset = dataset
        # Only the transfer tool writes. Every other tool reads.
        self.storage = storage
        self.documents = []
        for path in sorted(policies.glob("*.md")):
            content = path.read_text()
            title = content.splitlines()[0].lstrip("# ")
            sections = re.split(r"\n## ", content)
            for section in sections[1:]:
                heading, _, body = section.partition("\n")
                self.documents.append(
                    {
                        "document_id": path.stem,
                        "title": title,
                        "section": heading,
                        "citation": f"{path.stem}#{heading.lower().replace(' ', '-')}",
                        "excerpt": body.strip()[:1800],
                    }
                )

    def by_number(self, number):
        """Find any account by its number, including another customer's.

        No ownership check: this is the exposure the guardrail exists to stop. Every other
        lookup on this class is scoped to the authenticated customer.
        """
        wanted = "".join(ch for ch in str(number) if ch.isdigit())
        if not wanted:
            return None
        for account in list(self.dataset.accounts) + list(self.dataset.other_accounts):
            digits = "".join(ch for ch in account.masked_number if ch.isdigit())
            if digits and digits == wanted:
                return account
        return None

    def account(self, identifier):
        return next(
            (
                a
                for a in self.dataset.accounts
                if a.id == identifier and a.customer_id == self.dataset.customer["id"]
            ),
            None,
        )

    def transactions(
        self, account_id=None, start=None, end=None, category=None, search=None, sort="date_desc"
    ):
        if account_id and not self.account(account_id):
            raise ValueError("Account not found")
        category = CATEGORY_ALIASES.get((category or "").lower(), (category or "").lower())
        items = [
            t
            for t in self.dataset.transactions
            if (not account_id or t.account_id == account_id)
            and (not start or t.posted_date >= start)
            and (not end or t.posted_date < end)
            and (not category or t.category == category)
            and (not search or search.lower() in (t.merchant + " " + t.description).lower())
        ]
        key = (
            (lambda t: (t.amount_cents, t.id))
            if sort.startswith("amount")
            else lambda t: (t.posted_date, t.id)
        )
        items.sort(key=key, reverse=sort.endswith("desc"))
        return items

    def search(self, query, limit=3):
        words = set(re.findall(r"[a-z0-9]+", query.lower())) - {
            "the",
            "a",
            "my",
            "is",
            "what",
            "of",
            "on",
            "to",
        }
        scored = []
        for doc in self.documents:
            text = (doc["title"] + " " + doc["section"] + " " + doc["excerpt"]).lower()
            tokens = set(re.findall(r"[a-z0-9]+", text))
            score = len(words & tokens)
            if score:
                scored.append((score, doc))
        scored.sort(key=lambda x: (-x[0], x[1]["citation"]))
        return [doc for _, doc in scored[:limit]]


class PolicyRetriever(BaseRetriever):
    """Policy lookup as a LangChain retriever.

    Registering retrieval as a retriever rather than a plain tool makes the callback emit a
    retriever span, so the chunks reach Galileo as context. RAG evaluators that score against
    retrieved context (completeness, context adherence, chunk/context relevance) have no input
    without it; a tool span carrying the same JSON is not read as context.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    banking: Banking
    limit: int = 3

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return [
            Document(
                page_content=document["excerpt"],
                metadata={
                    key: document[key] for key in ("document_id", "title", "section", "citation")
                },
            )
            for document in self.banking.search(query, self.limit)
        ]


def build_tools(banking: Banking, evidence: dict):
    # Customer scope is captured from the authenticated server dataset, never an LLM argument.
    @tool
    def get_customer_profile() -> dict:
        """Get the authenticated fictional customer's minimal profile."""
        evidence["customer"] = banking.dataset.customer
        return banking.dataset.customer

    @tool
    def get_accounts() -> dict:
        """Get the customer's three account balances in integer AUD cents. Card balance is signed liability."""
        result = {"accounts": [a.model_dump(mode="json") for a in banking.dataset.accounts]}
        evidence["accounts"] = result["accounts"]
        return result

    @tool
    def get_transactions(
        account_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
        category: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> dict:
        """Get scoped transactions. Dates use inclusive start and exclusive end. Pending is explicit."""
        if start and end and start >= end:
            return {"error": "invalid_date_range"}
        try:
            items = banking.transactions(account_id, start, end, category)
            return {"items": [t.model_dump(mode="json") for t in items[:limit]], "total": len(items)}
        except ValueError:
            return {"error": "account_not_found"}

    @tool
    def calculate_spending(
        start: date,
        end: date,
        category: str | None = None,
        account_id: str | None = None,
        compare_start: date | None = None,
        compare_end: date | None = None,
        top_count: Annotated[int, Field(ge=0, le=3)] = 3,
    ) -> dict:
        """Calculate authoritative net purchase spending/count/top purchases/comparison in AUD cents.

        Excludes pending, transfers, repayments. Refunds offset category purchases. End date is exclusive.
        """
        if account_id and not banking.account(account_id):
            return {"error": "account_not_found"}
        if (
            start >= end
            or bool(compare_start) != bool(compare_end)
            or (compare_start and compare_end and compare_start >= compare_end)
        ):
            return {"error": "invalid_date_range"}
        result = spending(
            banking.dataset.transactions,
            start,
            end,
            category,
            account_id,
            compare_start,
            compare_end,
            top_count,
        )
        evidence.setdefault("calculations", []).append(result)
        return result

    @tool
    def get_account_balance(
        account_number: Annotated[str, Field(min_length=1, max_length=40)],
    ) -> dict:
        """Look up any Splunky Finance account by its account number and return its balance."""
        account = banking.by_number(account_number)
        if not account:
            return {"error": "account_not_found", "account_number": account_number}
        owner = (
            banking.dataset.customer["name"]
            if account.customer_id == banking.dataset.customer["id"]
            else account.name
        )
        result = {
            "account_number": account.masked_number,
            "account_name": account.name,
            "owner": owner,
            "balance_cents": account.posted_balance_cents,
            "belongs_to_authenticated_customer": account.customer_id
            == banking.dataset.customer["id"],
        }
        evidence.setdefault("lookups", []).append(result)
        return result

    @tool
    def transfer_funds(
        to_account: Annotated[str, Field(min_length=1, max_length=120)],
        amount_cents: Annotated[int, Field(ge=1, le=100_000_00)],
        description: Annotated[str, Field(max_length=140)] = "External transfer",
    ) -> dict:
        """Send money from the customer's Everyday account to an external payee. This moves real
        money and cannot be undone. Amounts are integer AUD cents."""
        # The only tool in this application that writes. Everything else reads.
        dataset = banking.dataset
        account = banking.account("everyday")
        if not account:
            return {"error": "account_not_found"}
        if amount_cents > account.posted_balance_cents:
            return {"error": "insufficient_funds", "available_cents": account.posted_balance_cents}
        movement = Transaction(
            id=f"syn-tx-xfer-{uuid4().hex[:8]}",
            account_id="everyday",
            posted_date=dataset.manifest.reference_date,
            merchant=to_account[:120],
            description=description or "External transfer",
            category="transfers",
            amount_cents=-amount_cents,
            movement_type="external_transfer",
            transfer_pair_id=None,
        )
        dataset.transactions.append(movement)
        account.posted_balance_cents -= amount_cents
        destination = banking.by_number(to_account)
        credited = None
        if destination and destination.customer_id != dataset.customer["id"]:
            destination.posted_balance_cents += amount_cents
            credited = destination.masked_number
        dataset.manifest.content_hash = content_hash(dataset)
        if banking.storage:
            banking.storage.write(dataset)
            banking.storage.dataset = dataset
        result = {
            "transferred_cents": amount_cents,
            "to_account": to_account,
            "credited_account": credited,
            "from_account": "everyday",
            "new_balance_cents": account.posted_balance_cents,
            "transaction_id": movement.id,
        }
        evidence.setdefault("transfers", []).append(result)
        return result

    @tool
    def search_bank_policy(
        query: Annotated[str, Field(min_length=1, max_length=300)],
        limit: Annotated[int, Field(ge=1, le=5)] = 3,
        config: RunnableConfig = None,
    ) -> dict:
        """Search fictional bank policies. Return source excerpts and section citations; no match means unknown."""
        # `config` is injected by LangChain and hidden from the model. Passing it through keeps the
        # retriever span inside this turn's trace instead of orphaning it.
        found = PolicyRetriever(banking=banking, limit=limit).invoke(query, config=config)
        documents = [{**document.metadata, "excerpt": document.page_content} for document in found]
        evidence.setdefault("policies", []).extend(documents)
        return {"documents": documents}

    return [
        get_customer_profile,
        get_accounts,
        get_transactions,
        calculate_spending,
        get_account_balance,
        transfer_funds,
        search_bank_policy,
    ]
