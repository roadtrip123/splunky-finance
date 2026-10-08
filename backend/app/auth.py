import hmac
import secrets
import time
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

    @staticmethod
    def cookie(role):
        return f"splunky_{role}_session"

    def prune(self):
        now = time.time()
        self.sessions = {k: s for k, s in self.sessions.items() if s.expires > now}

    def login(self, request, role, credentials, response):
        self.prune()
        now = time.time()
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
        expected = self.settings.app_origin.rstrip("/")
        if origin != expected:
            # The expected origin is named, because the bare rejection is undiagnosable: it fires
            # both for a stale container still holding a previous APP_ORIGIN and for a browser on a
            # different address than the one configured, and those need opposite fixes. It is the
            # URL the deployment is reached at, not a secret -- and every participant configuring
            # their own box will hit this at least once.
            raise HTTPException(
                403,
                f"Request origin rejected: this deployment answers only to {expected}, "
                f"but the request came from {origin or 'no origin'}. "
                "Browse that address, or set APP_ORIGIN to match and restart.",
            )
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
