"""Uvicorn-Worker fuer Gunicorn, der den X-Forwarded-Proto/-For-Headern von
nginx vertraut.

Ohne das wuerde die App hinter dem TLS-terminierenden Reverse Proxy jede
Anfrage faelschlich als "http" statt "https" sehen (nginx spricht intern nur
Klartext-HTTP mit der App) - z.B. mit der Folge, dass generierte
OIDC-Redirect-URIs (request.url_for(...)) auf "http://" statt "https://"
zeigen und Keycloak den Login mit "invalid redirect_uri" ablehnt.

forwarded_allow_ips="*": bewusst alle IPs vertrauenswuerdig, da der
App-Container im internen Docker-Netzwerk NUR von nginx erreichbar ist
(kein Host-Port-Mapping, siehe docker-compose.yml) - es gibt also keinen Weg,
diese Header von aussen zu faelschen, ohne bereits im Docker-Netz zu sein.
"""
from uvicorn.workers import UvicornWorker


class ProxyHeadersUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {"proxy_headers": True, "forwarded_allow_ips": "*"}
