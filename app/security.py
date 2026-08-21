"""Leichte Security-Middleware auf Anwendungsebene.

Das hier ersetzt KEIN Login/SSO (das kommt als naechster Schritt via
Keycloak/OIDC, siehe README) - es sind Basis-Haertungsmassnahmen, die
unabhaengig vom Auth-Konzept sinnvoll sind und schon jetzt nichts kosten.
TLS-Terminierung selbst passiert bewusst NICHT hier, sondern eine Ebene
davor im Nginx-Reverse-Proxy (siehe nginx/conf.d/default.conf).
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
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; connect-src 'self'",
        )
        return response
