"""Single-owner HTTP Basic authentication. Use HTTPS outside localhost."""
import base64
import binascii
import logging
import os
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlsplit
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = logging.getLogger("uvicorn.error")


def settings():
    return os.getenv("AUTH_USERNAME", "owner"), os.getenv("AUTH_PASSWORD", "")


def validate_security():
    username, password = settings()
    if not username or ":" in username or len(password) < 24:
        raise RuntimeError("Configure AUTH_USERNAME and an AUTH_PASSWORD of at least 24 characters; run scripts/setup_local.py")
    if os.getenv("DEPLOYMENT_MODE", "local") == "production":
        origin = os.getenv("PUBLIC_ORIGIN", "")
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError("Production requires PUBLIC_ORIGIN=https://your-domain without a trailing slash")
        hosts = os.getenv("ALLOWED_HOSTS", "").split(",")
        if "*" in hosts or parsed.hostname not in hosts:
            raise RuntimeError("Production ALLOWED_HOSTS must include the public hostname and cannot contain *")
        if len(urlsplit(os.getenv("DATABASE_URL", "")).password or "") < 24:
            raise RuntimeError("Production requires a database password of at least 24 characters")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.failures = OrderedDict()

    async def dispatch(self, request, call_next):
        started = time.monotonic()
        request_id = uuid4().hex
        response = None
        if request.url.path not in ("/health", "/ready"):
            username, password = settings()
            if not username or len(password) < 24:
                response = JSONResponse({"detail": "Authentication is not configured"}, status_code=503)
            else:
                # Do not trust client-supplied forwarded IP headers for rate limiting.
                peer = request.client.host if request.client else "unknown"
                count, until = self.failures.get(peer, (0, 0))
                if until <= started:
                    count = 0
                if count >= 10:
                    response = JSONResponse({"detail": "Too many failed sign-ins; retry in one minute"},
                                            status_code=429, headers={"Retry-After": "60"})
                else:
                    supplied_user = supplied_password = ""
                    try:
                        scheme, encoded = request.headers.get("authorization", "").split(" ", 1)
                        if scheme.lower() == "basic":
                            supplied_user, supplied_password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
                    except (ValueError, UnicodeError, binascii.Error):
                        pass
                    user_ok = secrets.compare_digest(supplied_user.encode(), username.encode())
                    password_ok = secrets.compare_digest(supplied_password.encode(), password.encode())
                    if not (user_ok and password_ok):
                        # The browser's initial unauthenticated challenge is not a failed attempt.
                        if request.headers.get("authorization"):
                            self.failures[peer] = (count + 1, until if count else started + 60)
                            self.failures.move_to_end(peer)
                            if len(self.failures) > 4096:
                                self.failures.popitem(last=False)
                        response = JSONResponse({"detail": "Sign in with your workspace credentials"}, status_code=401,
                                                headers={"WWW-Authenticate": 'Basic realm="Job Pipeline", charset="UTF-8"'})
                    else:
                        self.failures.pop(peer, None)
                if response is None and request.method not in ("GET", "HEAD", "OPTIONS"):
                    # Basic credentials are sent automatically by browsers: block cross-site writes.
                    origin = request.headers.get("origin")
                    expected = os.getenv("PUBLIC_ORIGIN") or str(request.base_url).rstrip("/")
                    if (origin is not None and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
                        response = JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        if os.getenv("DEPLOYMENT_MODE") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        # No credentials, query strings, job titles or résumé contents in request logs.
        log.info("request=%s method=%s status=%s duration_ms=%.1f", request_id, request.method,
                 response.status_code, (time.monotonic() - started) * 1000)
        return response
