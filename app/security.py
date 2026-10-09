"""Leichte Security-Middleware auf Anwendungsebene.

Ergaenzt das Login/SSO (app/auth.py) um Basis-Haertungsmassnahmen, die
unabhaengig vom Auth-Konzept sinnvoll sind. TLS-Terminierung passiert
bewusst NICHT hier, sondern im Nginx-Reverse-Proxy (nginx/conf.d/default.conf).
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        return response
