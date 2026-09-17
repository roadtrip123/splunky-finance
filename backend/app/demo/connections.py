"""Session-scoped demo links; browser clients communicate only with the server."""

import secrets
import time

from fastapi import HTTPException


class Connections:
    def __init__(self, auth, chat):
        self.auth, self.chat = auth, chat
        self.codes = {}
        self.blocked = set()
        self.seen = {}

    def target(self, run):
        customer = self.auth.sessions.get(run.get("customer_id"))
        return (
            customer if customer and customer.expires > time.time() and customer.run_id == run["id"] else None
        )

    def stale(self, customer):
        """Drop a binding to a run that no longer exists.

        Presenter logout deletes the run but cannot reach into the customer session to clear its
        id. Left in place that dead id blocks auto-relink and makes pairing raise 409, so the
        banking session has no way back to a presenter.
        """
        if customer and customer.run_id and customer.run_id not in self.chat.runs:
            customer.run_id = None
            self.seen.pop(customer.id, None)

    def attach(self, customer, run):
        self.stale(customer)
        if run.get("customer_id") and run["customer_id"] != customer.id:
            raise HTTPException(409, "Disconnect the existing banking session first")
        if customer.run_id and customer.run_id != run["id"]:
            raise HTTPException(409, "Disconnect the current demo before pairing another")
        customer.run_id = run["id"]
        run["customer_id"] = customer.id
        run["auto_disabled"] = False
        self.blocked.discard(customer.id)
        self.seen.pop(customer.id, None)

    def auto(self, customer, admin):
        if not customer or not admin or customer.id in self.blocked:
            return
        self.stale(customer)
        run = self.chat.run(admin)
        if run and not run.get("auto_disabled") and not run.get("customer_id") and not customer.run_id:
            self.attach(customer, run)

    def state(self, customer):
        run = self.chat.run(customer)
        if customer.run_id and not run:
            return {
                "version": f"expired:{customer.run_id}",
                "scenario": "normal_spending",
                "connected": False,
                "expired": True,
            }
        return {
            "version": f"{run['id']}:{run['revision']}" if run else "normal",
            "scenario": run["scenario"] if run else "normal_spending",
            "connected": bool(run),
            "expired": False,
        }

    def disconnect(self, customer, run=None):
        run = run or self.chat.runs.get(customer.run_id)
        if run:
            run.pop("customer_id", None)
            run["auto_disabled"] = True
        customer.run_id = None
        self.blocked.add(customer.id)
        self.seen.pop(customer.id, None)

    def issue(self, run):
        now = time.time()
        self.codes = {k: v for k, v in self.codes.items() if v[1] > now and v[0] != run["id"]}
        if run.get("customer_id"):
            raise HTTPException(409, "Disconnect the existing banking session first")
        code = secrets.token_hex(6).upper()
        self.codes[code] = (run["id"], now + 300)
        return {"code": code, "expires_at": now + 300}

    def pair(self, customer, code):
        record = self.codes.get(code.strip().upper())
        if not record or record[1] <= time.time():
            raise HTTPException(400, "Pairing code is invalid or expired")
        run = self.chat.runs.get(record[0])
        owner = self.auth.sessions.get(run["owner"]) if run else None
        if not run or run["expires"] <= time.time() or not owner or owner.expires <= time.time():
            raise HTTPException(400, "Presenter session expired; request a new code")
        self.attach(customer, run)
        del self.codes[code.strip().upper()]

    def status(self, run):
        if not run or not run.get("customer_id"):
            return {"state": "unlinked", "session": None}
        customer = self.target(run)
        if not customer:
            return {"state": "disconnected", "session": run["customer_id"][:8]}
        version, timestamp = self.seen.get(customer.id, (None, 0))
        state = "applied" if version == self.state(customer)["version"] else "updating"
        if time.time() - timestamp > 10:
            state = "waiting"
        return {"state": state, "session": customer.id[:8]}
