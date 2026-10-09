def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Content-Security-Policy" in res.headers
    assert "unsafe-inline" not in res.headers["Content-Security-Policy"]


def test_list_centers_uses_csv_ids(client):
    data = client.get("/api/centers").json()
    assert data["total"] == 3
    assert sorted(c["id"] for c in data["items"]) == [10, 20, 30]


def test_filter_bundesland_case_insensitive(client):
    data = client.get("/api/centers", params={"bundesland": "sn"}).json()
    assert data["total"] == 2
    assert {c["ort"] for c in data["items"]} == {"Dresden", "Leipzig"}


def test_filter_angebot(client):
    data = client.get("/api/centers", params={"angebot": "demenzberatung"}).json()
    assert [c["id"] for c in data["items"]] == [30]


def test_response_maps_normalized_services_to_api_fields(client):
    data = client.get("/api/centers", params={"search": "Dresden"}).json()
    center = data["items"][0]
    assert center["pflegeberatung"] is True
    assert center["angehoerigenberatung"] is True
    assert center["demenzberatung"] is False
    assert "Pflegeberatung" in center["leistungen"]


def test_invalid_angebot_rejected(client):
    assert client.get("/api/centers", params={"angebot": "foo"}).status_code == 422


def test_search_escapes_like_wildcards(client):
    # Ohne Escaping wuerde "%" bzw. "_" als Wildcard alle Eintraege treffen.
    assert client.get("/api/centers", params={"search": "%"}).json()["total"] == 0
    assert client.get("/api/centers", params={"search": "_"}).json()["total"] == 0
    assert client.get("/api/centers", params={"search": "Leip"}).json()["total"] == 1


def test_pagination_total_independent_of_limit(client):
    data = client.get("/api/centers", params={"limit": 1}).json()
    assert data["total"] == 3
    assert len(data["items"]) == 1


def test_limit_capped(client):
    assert client.get("/api/centers", params={"limit": 501}).status_code == 422


def test_bundeslaender(client):
    assert client.get("/api/bundeslaender").json() == ["BY", "SN"]
