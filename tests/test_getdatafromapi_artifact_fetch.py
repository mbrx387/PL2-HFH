import zipfile

import pytest

from scripts import fetch_latest_getdatafromapi_artifact as fetcher


def artifact(artifact_id=42):
    return {
        "id": artifact_id,
        "name": f"pflegestellen-{artifact_id}",
        "created_at": "2026-10-24T07:02:37Z",
        "expired": False,
        "workflow_run": {"head_branch": "main"},
    }


def test_latest_artifact_uses_only_unexpired_main_branch(monkeypatch):
    monkeypatch.setattr(
        fetcher,
        "_api_request",
        lambda *_: b'{"artifacts":['
        b'{"id":1,"name":"pflegestellen-1","created_at":"2026-10-26T00:00:00Z",'
        b'"expired":true,"workflow_run":{"head_branch":"main"}},'
        b'{"id":2,"name":"pflegestellen-2","created_at":"2026-10-25T00:00:00Z",'
        b'"expired":false,"workflow_run":{"head_branch":"feature"}},'
        b'{"id":3,"name":"pflegestellen-3","created_at":"2026-10-24T00:00:00Z",'
        b'"expired":false,"workflow_run":{"head_branch":"main"}}]}',
    )

    assert fetcher.latest_artifact("mbrx387/PL2-HFH", "token")["id"] == 3


def test_latest_artifact_can_be_restricted_to_a_run(monkeypatch):
    monkeypatch.setattr(
        fetcher,
        "_api_request",
        lambda *_: b'{"artifacts":['
        b'{"id":3,"name":"pflegestellen-3","created_at":"2026-10-24T00:00:00Z",'
        b'"expired":false,"workflow_run":{"head_branch":"main","id":70}},'
        b'{"id":4,"name":"pflegestellen-4","created_at":"2026-10-25T00:00:00Z",'
        b'"expired":false,"workflow_run":{"head_branch":"main","id":71}}]}',
    )

    assert fetcher.latest_artifact("mbrx387/PL2-HFH", "token", "70")["id"] == 3


def test_fetch_latest_publishes_csv_and_marks_artifact(monkeypatch, tmp_path):
    csv_content = b"unsere_id;name\n1;Beratungsstelle\n"
    monkeypatch.setattr(fetcher, "latest_artifact", lambda *_: artifact())

    def write_zip(_repository, _artifact_id, _token, target):
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("build/GetDataFromAPI/pflegestellen.csv", csv_content)

    monkeypatch.setattr(fetcher, "_download_archive", write_zip)
    destination = tmp_path / "db" / "temp" / "pflegestellen.csv"

    assert fetcher.fetch_latest("mbrx387/PL2-HFH", "token", destination) is True
    assert destination.read_bytes() == csv_content
    assert (destination.parent / ".last_getdatafromapi_artifact").read_text().strip() == "42"


def test_fetch_latest_skips_already_processed_artifact(monkeypatch, tmp_path):
    destination = tmp_path / "db" / "temp" / "pflegestellen.csv"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing", encoding="utf-8")
    (destination.parent / ".last_getdatafromapi_artifact").write_text("42", encoding="utf-8")
    monkeypatch.setattr(fetcher, "latest_artifact", lambda *_: artifact())
    monkeypatch.setattr(
        fetcher,
        "_download_archive",
        lambda *_: pytest.fail("already-processed artifact must not be downloaded"),
    )

    assert fetcher.fetch_latest("mbrx387/PL2-HFH", "token", destination) is False
    assert destination.read_text(encoding="utf-8") == "existing"


def test_fetch_latest_rejects_archive_without_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(fetcher, "latest_artifact", lambda *_: artifact())

    def write_zip(_repository, _artifact_id, _token, target):
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("other.csv", "not the expected export")

    monkeypatch.setattr(fetcher, "_download_archive", write_zip)
    destination = tmp_path / "db" / "temp" / "pflegestellen.csv"

    with pytest.raises(fetcher.ArtifactError, match="genau eine"):
        fetcher.fetch_latest("mbrx387/PL2-HFH", "token", destination)
    assert not destination.exists()
