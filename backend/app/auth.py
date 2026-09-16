import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


@dataclass
class Session:
    id: str
    role: str
    expires: float
    csrf: str
    run_id: str | None = None


class Authentication:
    def __init__(self, settings):
        self.settings = settings
        self.signer = URLSafeTimedSerializer(
            settings.session_secret.get_secret_value(), salt="splunky-session-v1"
        )
        hasher = PasswordHasher()
        self.hasher = hasher
        self.hashes = {
            "customer": hasher.hash(settings.demo_password.get_secret_value()),
            "admin": hasher.hash(settings.demo_admin_password.get_secret_value()),
        }
        self.sessions: dict[str, Session] = {}
        self.attempts: dict[tuple, deque] = defaultdict(deque)

    @staticmethod
    def cookie(role):
        return f"splunky_{role}_session"

    def prune(self):
        now = time.time()
        self.sessions = {k: s for k, s in self.sessions.items() if s.expires > now}
        for key in list(self.attempts):
            if not self.attempts[key] or self.attempts[key][-1] < now - 300:
                del self.attempts[key]

    def login(self, request, role, credentials, response):
        self.prune()
        key = (request.client.host if request.client else "unknown", role)
        if len(self.attempts) >= 1000 and key not in self.attempts:
            raise HTTPException(429, "Login temporarily unavailable")
        attempts = self.attempts[key]
        now = time.time()
        while attempts and attempts[0] < now - 300:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, "Too many login attempts; try again in five minutes")
        attempts.append(now)
        try:
            valid = self.hasher.verify(self.hashes[role], credentials.password)
        except VerifyMismatchError:
            valid = False
        identifier = role == "admin" or hmac.compare_digest(
            credentials.account_number, self.settings.demo_account_number
        )
        if not valid or not identifier:
            raise HTTPException(401, "Invalid login details")
        if len(self.sessions) >= 500:
            raise HTTPException(429, "Session capacity reached; try again later")
        existing = self.get(request, role, required=False)
        if existing:
            self.sessions.pop(existing.id, None)
        session = Session(secrets.token_urlsafe(32), role, now + 3600, secrets.token_urlsafe(32))
        self.sessions[session.id] = session
        response.set_cookie(
            self.cookie(role),
            self.signer.dumps({"id": session.id, "role": role}),
            max_age=3600,
            httponly=True,
            secure=self.settings.session_cookie_secure,
            samesite="strict",
            path="/",
        )
        return self.summary(session)

    def get(self, request: Request, role="customer", required=True):
        self.prune()
        token = request.cookies.get(self.cookie(role))
        session = None
        if token:
            try:
                data = self.signer.loads(token, max_age=3600)
                session = self.sessions.get(data["id"]) if data.get("role") == role else None
            except (BadSignature, SignatureExpired, KeyError):
                pass
        if not session and required:
            raise HTTPException(401, "Please log in")
        return session

    def csrf(self, request, session=None):
        origin = request.headers.get("origin", "").rstrip("/")
        if origin != self.settings.app_origin.rstrip("/"):
            raise HTTPException(403, "Request origin rejected")
        if session and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
            raise HTTPException(403, "Request verification failed")

    @staticmethod
    def summary(session):
        return {
            "authenticated": bool(session),
            "role": session.role if session else None,
            "expires_at": session.expires if session else None,
            "csrf_token": session.csrf if session else None,
        }
