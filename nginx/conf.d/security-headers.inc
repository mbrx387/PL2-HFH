# Wird per "include" in jeden Block mit eigenen add_header-Anweisungen
# eingebunden: nginx vererbt add_header nur, wenn ein Block selbst KEINE
# add_header-Anweisung hat. Endung .inc (nicht .conf), damit nginx.conf die
# Datei nicht zusaetzlich auf http-Ebene laedt.
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Content-Type-Options $hdr_xcto always;
add_header X-Frame-Options $hdr_xfo always;
add_header Referrer-Policy $hdr_referrer always;
