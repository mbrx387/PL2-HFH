"""Download the newest unprocessed GetDataFromAPI artifact from GitHub Actions."""

import argparse
import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
    urlopen,
)

API_BASE = "https://api.github.com"
ARTIFACT_PREFIX = "pflegestellen-"
CSV_NAME = "pflegestellen.csv"
logger = logging.getLogger(__name__)


class ArtifactError(Exception):
    """A GitHub Actions artifact could not be safely retrieved or published."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api_request(url: str, token: str):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PL2-HFH-artifact-fetcher",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        code = getattr(error, "code", None)
        detail = f"HTTP {code}" if code else "Netzwerkfehler"
        raise ArtifactError(f"GitHub-API-Aufruf fehlgeschlagen ({detail}).") from None


def latest_artifact(repository: str, token: str, run_id: str | None = None) -> dict | None:
    """Return the newest unexpired artifact for the main branch."""
    encoded_repo = quote(repository, safe="/")
    artifacts = []
    page = 1
    while True:
        url = f"{API_BASE}/repos/{encoded_repo}/actions/artifacts?per_page=100&page={page}"
        try:
            payload = json.loads(_api_request(url, token))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ArtifactError("GitHub lieferte eine ungueltige Artifact-Antwort.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise ArtifactError("GitHub-Antwort enthaelt keine Artifact-Liste.")

        batch = payload["artifacts"]
        artifacts.extend(
            item
            for item in batch
            if isinstance(item, dict)
            and item.get("expired") is False
            and str(item.get("name", "")).startswith(ARTIFACT_PREFIX)
            and isinstance(item.get("workflow_run"), dict)
            and item["workflow_run"].get("head_branch") == "main"
            and (
                run_id is None
                or str(item["workflow_run"].get("id")) == str(run_id)
            )
        )
        if len(batch) < 100:
            break
        page += 1

    if not artifacts:
        return None
    try:
        return max(artifacts, key=lambda item: (item["created_at"], int(item["id"])))
    except (KeyError, TypeError, ValueError):
        raise ArtifactError("GitHub-Artifact-Metadaten sind unvollstaendig.") from None


def _download_archive(repository: str, artifact_id: int, token: str, target: Path) -> None:
    url = f"{API_BASE}/repos/{quote(repository, safe='/')}/actions/artifacts/{artifact_id}/zip"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PL2-HFH-artifact-fetcher",
        },
    )

    try:
        with build_opener(_NoRedirectHandler).open(request, timeout=30) as response:
            if response.status != 200:
                raise ArtifactError(f"Artifact-Download fehlgeschlagen (HTTP {response.status}).")
            with target.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            return
    except HTTPError as error:
        if error.code != 302:
            raise ArtifactError(f"Artifact-Download fehlgeschlagen (HTTP {error.code}).") from None
        download_url = error.headers.get("Location")
    except (URLError, TimeoutError, OSError):
        raise ArtifactError("Artifact-Download fehlgeschlagen (Netzwerk-/Dateifehler).") from None

    if not download_url or urlparse(download_url).scheme != "https":
        raise ArtifactError("GitHub lieferte keine sichere Download-Adresse.")
    try:
        # The signed redirect URL is sufficient; never forward the GitHub token to it.
        with urlopen(download_url, timeout=60) as response, target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise ArtifactError("Artifact-Archiv konnte nicht heruntergeladen werden.") from None


def _copy_csv_from_archive(archive_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                item for item in archive.infolist()
                if not item.is_dir() and Path(item.filename).name == CSV_NAME
            ]
            if len(matches) != 1:
                raise ArtifactError(
                    f"Im Artifact muss genau eine {CSV_NAME} enthalten sein; gefunden: {len(matches)}."
                )
            if matches[0].file_size == 0:
                raise ArtifactError(f"{CSV_NAME} im Artifact ist leer.")
            with archive.open(matches[0]) as source, destination.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
    except (zipfile.BadZipFile, RuntimeError, OSError):
        raise ArtifactError("Artifact ist kein gueltiges ZIP oder die CSV ist nicht lesbar.") from None


def fetch_latest(
    repository: str,
    token: str,
    destination: Path,
    *,
    run_id: str | None = None,
) -> bool:
    """Publish the latest CSV if its artifact ID has not been processed yet."""
    artifact = latest_artifact(repository, token, run_id)
    if artifact is None:
        raise ArtifactError("Kein unverfallenes pflegestellen-Artifact fuer main gefunden.")

    try:
        artifact_id = int(artifact["id"])
        created_at = datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        raise ArtifactError("GitHub-Artifact-Metadaten sind unvollstaendig.") from None

    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = destination.parent / ".last_getdatafromapi_artifact"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == str(artifact_id):
        logger.info("Artifact %s vom %s ist bereits verarbeitet.", artifact_id, created_at.isoformat())
        return False

    with tempfile.TemporaryDirectory(prefix=".getdatafromapi-", dir=destination.parent) as temp_dir:
        temporary = Path(temp_dir)
        archive_path = temporary / "artifact.zip"
        csv_path = temporary / CSV_NAME
        _download_archive(repository, artifact_id, token, archive_path)
        _copy_csv_from_archive(archive_path, csv_path)

        # Publish the CSV and marker atomically so a failed download never replaces good data.
        staged_marker = temporary / ".last_getdatafromapi_artifact.tmp"
        try:
            staged_marker.write_text(f"{artifact_id}\n", encoding="utf-8")
            os.replace(csv_path, destination)
            os.replace(staged_marker, marker)
        finally:
            staged_marker.unlink(missing_ok=True)

    logger.info(
        "Artifact %s vom %s heruntergeladen; CSV gespeichert unter %s.",
        artifact_id,
        created_at.isoformat(),
        destination,
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Holt die neueste noch nicht verarbeitete GetDataFromAPI-CSV."
    )
    parser.add_argument("--repo", default=os.environ.get("GH_REPO", "mbrx387/PL2-HFH"))
    parser.add_argument("--destination", type=Path, default=Path("db/temp/pflegestellen.csv"))
    parser.add_argument(
        "--run-id",
        help="Optional: nur Artifacts dieses GitHub-Actions-Laufs berücksichtigen.",
    )
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        parser.error("GH_TOKEN oder GITHUB_TOKEN muss gesetzt sein.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        fetch_latest(args.repo, token, args.destination, run_id=args.run_id)
    except ArtifactError as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
