"""Offline regression tests: no production API requests or data changes."""

import io
from decimal import Decimal
from urllib.error import HTTPError, URLError

import pytest

from GetDataFromAPI.pipeline import (
    ImportFailure,
    fetch_point,
    grid,
    merge_records,
    read_baseline,
    run,
    write_candidate,
)
from GetDataFromAPI.transform import convert_item, parse_contacts


def baseline():
    record = convert_item({"id": "known", "name": "Existing", "email": "old@example.org"}, 42)
    record.pop("zqp_raw")
    record["leistungen"] = ", ".join(record["leistungen"])
    return [record]


def test_stable_ids_deduplication_updates_and_no_mutation():
    previous = baseline()
    result = merge_records(
        previous,
        [
            {"id": "known", "name": "Renamed", "lat": 0},
            {"id": "new", "name": "New"},
            {"id": "new", "name": "New"},
        ],
    )
    assert [row["unsere_id"] for row in result] == [42, 43]
    assert result[0]["name"] == "Renamed"
    assert result[0]["email"] == "old@example.org"
    assert result[0]["latitude"] == 0
    assert previous[0]["name"] == "Existing"
    assert merge_records(previous, [{"id": "new", "name": "New"}])[0]["unsere_id"] == 42


def test_failed_extraction_preserves_both_files(tmp_path):
    original = tmp_path / "baseline.csv"
    output = tmp_path / "candidate.csv"
    write_candidate(original, baseline())
    output.write_text("last successful candidate")
    before = original.read_bytes()
    calls = []

    def fetch(*args):
        calls.append(args)
        if len(calls) == 2:
            raise ImportFailure("failed")
        return [{"id": "new", "name": "New"}]

    with pytest.raises(ImportFailure):
        run("https://source.example/api", original, output, coordinates=[(1, 1), (2, 2)], fetch=fetch)
    assert original.read_bytes() == before
    assert output.read_text() == "last successful candidate"


def test_successful_run_produces_postgres_import_compatible_csv(tmp_path):
    original, output = tmp_path / "baseline.csv", tmp_path / "out.csv"
    write_candidate(original, baseline())
    assert (
        run(
            "https://source.example/api",
            original,
            output,
            coordinates=[(1, 1)],
            fetch=lambda *args: [{"id": "known", "name": "Updated"}],
        )
        == 1
    )
    records = read_baseline(output)
    assert records[0]["unsere_id"] == "42"
    assert records[0]["name"] == "Updated"


@pytest.mark.parametrize("payload", [b"{}", b'{"data": {}}', b'{"data": [1]}', b"not json"])
def test_invalid_response_fails(payload):
    with pytest.raises(ImportFailure):
        fetch_point(
            "https://source.example",
            1,
            1,
            sleep=lambda _: None,
            open_url=lambda *args, **kwargs: io.BytesIO(payload),
        )


def test_transient_error_retries_then_succeeds():
    attempts = []

    def open_url(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise URLError("offline")
        return io.BytesIO(b'{"data": []}')

    assert fetch_point("https://source.example", 1, 1, sleep=lambda _: None, open_url=open_url) == []
    assert len(attempts) == 3


@pytest.mark.parametrize("status, expected_attempts", [(401, 1), (429, 3), (503, 3)])
def test_http_errors_are_bounded(status, expected_attempts):
    attempts = []

    def open_url(*args, **kwargs):
        attempts.append(1)
        raise HTTPError("https://source.example", status, "failed", {}, None)

    with pytest.raises(ImportFailure):
        fetch_point("https://source.example", 1, 1, sleep=lambda _: None, open_url=open_url)
    assert len(attempts) == expected_attempts


def test_grid_and_legacy_contact_parsing():
    points = list(grid())
    assert len(points) == 53 * 63
    assert points[0] == (47.2, 5.8)
    assert points[-1] == (55.0, 15.1)
    with pytest.raises(ImportFailure):
        list(grid(Decimal("0")))
    assert parse_contacts("[{'email': ' person@example.org ', 'phone': '123'}]") == (
        ["person@example.org"],
        ["123"],
    )


def test_empty_source_and_overwrite_are_rejected(tmp_path):
    original = tmp_path / "baseline.csv"
    write_candidate(original, baseline())
    with pytest.raises(ImportFailure):
        run("https://source.example", original, original, coordinates=[])
    with pytest.raises(ImportFailure):
        run("https://source.example", original, tmp_path / "out.csv", coordinates=[], fetch=lambda *a: [])
    assert not (tmp_path / "out.csv").exists()


@pytest.mark.parametrize("raw", [{"name": ""}, {"name": "Bad", "lat": "nan"}])
def test_invalid_records_fail(raw):
    with pytest.raises(ImportFailure):
        merge_records(baseline(), [raw])


def test_service_removal_does_not_leave_stale_text():
    previous = baseline()
    previous[0]["pflegeberatung"] = 1
    previous[0]["leistungen"] = "Pflegeberatung"
    result = merge_records(previous, [{"id": "known", "name": "Updated"}])
    assert result[0]["pflegeberatung"] == 0
    assert result[0]["leistungen"] == ""


def test_failed_atomic_replace_preserves_candidate(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.csv"
    candidate.write_text("previous")

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr("GetDataFromAPI.pipeline.os.replace", fail)
    with pytest.raises(OSError):
        write_candidate(candidate, baseline())
    assert candidate.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [candidate]


def test_existing_project_baseline_is_preserved(tmp_path):
    from pathlib import Path

    path = Path(__file__).parent.parent / "app/data/pflegestellen.csv"
    records = read_baseline(path)
    candidate = tmp_path / "out.csv"
    result = merge_records(records, [{"id": "etl-test-new", "name": "Offline test center"}])
    write_candidate(candidate, result)
    restored = read_baseline(candidate)
    assert len(restored) == len(records) + 1
    assert {row["unsere_id"] for row in records}.issubset({row["unsere_id"] for row in restored})


def test_json_contacts_with_null_values():
    assert parse_contacts('[{"email": "person@example.org", "phone": null}]') == (
        ["person@example.org"],
        [],
    )


@pytest.mark.parametrize(
    "endpoint", ["", "http://source.example", "https://[invalid", "https://source.example?q=1"]
)
def test_invalid_endpoint_is_controlled(endpoint, tmp_path):
    with pytest.raises(ImportFailure):
        run(endpoint, tmp_path / "missing.csv", tmp_path / "out.csv", coordinates=[])


@pytest.mark.parametrize("content", ["wrong;header\n1;2\n", "", "header only"])
def test_bad_baseline_is_rejected(tmp_path, content):
    path = tmp_path / "baseline.csv"
    path.write_text(content)
    with pytest.raises(ImportFailure):
        read_baseline(path)


@pytest.mark.parametrize("issue", ["duplicate_id", "duplicate_key", "short_row", "long_row", "header_only"])
def test_corrupt_baseline_rows_are_rejected(tmp_path, issue):
    from GetDataFromAPI.pipeline import COLUMNS

    path = tmp_path / "baseline.csv"
    records = baseline()
    if issue == "duplicate_id":
        records.append({**records[0], "zqp_id": "other"})
    elif issue == "duplicate_key":
        records.append({**records[0], "unsere_id": 43})
    write_candidate(path, records)
    if issue == "short_row":
        path.write_text(";".join(COLUMNS) + "\n42;known\n", encoding="utf-8-sig")
    elif issue == "long_row":
        path.write_text(path.read_text(encoding="utf-8-sig").rstrip() + ";extra\n", encoding="utf-8-sig")
    elif issue == "header_only":
        path.write_text(";".join(COLUMNS) + "\n", encoding="utf-8-sig")
    with pytest.raises(ImportFailure):
        read_baseline(path)


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), URLError("offline")])
def test_exhausted_network_errors(error):
    calls, pauses = [], []

    def open_url(*args, **kwargs):
        calls.append(1)
        raise error

    with pytest.raises(ImportFailure):
        fetch_point("https://source.example", 1, 1, open_url=open_url, sleep=pauses.append)
    assert len(calls) == 3
    assert pauses == [0.3, 1, 0.3, 2, 0.3]


def test_request_parameters_and_timeout():
    from urllib.parse import parse_qs, urlsplit

    def open_url(request, timeout):
        assert parse_qs(urlsplit(request.full_url).query) == {
            "lat": ["47.2"],
            "lng": ["5.8"],
            "filter": ["2,1,3,6,4,5"],
        }
        assert request.get_header("User-agent") == "ZQP-Studienprojekt/1.0"
        assert timeout == 30
        return io.BytesIO(b'{"data": [{"id": "source", "name": "Center"}]}')

    assert len(fetch_point("https://source.example", 47.2, 5.8, open_url=open_url, sleep=lambda _: None)) == 1


@pytest.mark.parametrize("value", [None, "", "not valid", "{}", 42, "[1, null]"])
def test_contact_parser_handles_missing_and_malformed_values(value):
    assert parse_contacts(value) == ([], [])


def test_all_service_types_and_contact_deduplication():
    from GetDataFromAPI.pipeline import SERVICE_FIELDS
    from GetDataFromAPI.transform import detect_services, extract_contacts

    flags, labels = detect_services(
        {
            "services": [
                {
                    "label": (
                        "Pflegestützpunkt Pflegeberatung Wohnberatung "
                        "Demenzberatung Angehörigenberatung Betreuungsberatung"
                    )
                }
            ]
        }
    )
    assert set(flags) == set(SERVICE_FIELDS)
    assert all(flags.values()) and len(labels) == 6
    assert extract_contacts(
        {
            "email": "p@example.org",
            "contacts": [{"email": "p@example.org", "phone": "123"}, {"telephone": "123"}],
        }
    ) == ("p@example.org", "123")


def test_cli_success_and_failure(tmp_path, monkeypatch, caplog):
    import sys

    from GetDataFromAPI import __main__ as cli

    original, output = tmp_path / "baseline.csv", tmp_path / "result.csv"
    write_candidate(original, baseline())
    monkeypatch.setenv("ZQP_API_URL", "https://source.example/secret-token")
    data_output = tmp_path / "app" / "data" / "pflegestellen.csv"
    write_candidate(data_output, baseline())
    monkeypatch.setattr(
        sys, "argv",
        ["GetDataFromAPI", "--baseline", str(original), "--output", str(output),
         "--data-output", str(data_output)],
    )
    real_run = run

    def local_run(endpoint, baseline_path, output_path):
        return real_run(
            endpoint,
            baseline_path,
            output_path,
            coordinates=[(1, 1)],
            fetch=lambda *args: [{"id": "known", "name": "CLI Updated"}],
        )

    monkeypatch.setattr(cli, "run", local_run)
    assert cli.main() == 0
    assert read_baseline(output)[0]["name"] == "CLI Updated"
    assert data_output.read_bytes() == output.read_bytes()
    published = data_output.read_bytes()
    previous = output.read_bytes()
    monkeypatch.delenv("ZQP_API_URL")
    assert cli.main() == 1
    assert output.read_bytes() == previous
    assert data_output.read_bytes() == published
    assert "secret-token" not in caplog.text


def test_cli_file_error_does_not_leak_details(monkeypatch, caplog):
    import sys

    from GetDataFromAPI import __main__ as cli

    def fail(*args):
        raise OSError("private-sensitive-path")

    monkeypatch.setattr(sys, "argv", ["GetDataFromAPI"])
    monkeypatch.setattr(cli, "run", fail)
    assert cli.main() == 1
    assert "private-sensitive-path" not in caplog.text


def test_module_entrypoint_without_secret(tmp_path):
    import os
    import subprocess
    import sys

    environment = {**os.environ, "ZQP_API_URL": ""}
    result = subprocess.run(
        [sys.executable, "-m", "GetDataFromAPI", "--output", str(tmp_path / "out.csv")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "out.csv").exists()
