"""Die E2E-Infrastruktur nutzt dieselben Images wie der Produktivbetrieb.

e2e/docker-compose.e2e.yml wird separat gepflegt. Ohne diesen Test liefe die
Test-Datenbank nach einem manuellen Image-Wechsel in docker-compose.yml
unbemerkt auf einer anderen Version als die Produktion.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
IMAGE_LINE = re.compile(r"^\s+image:\s*(\S+)\s*$", re.M)


def _images(path: Path) -> set[str]:
    return set(IMAGE_LINE.findall(path.read_text(encoding="utf-8")))


def test_e2e_compose_uses_production_images():
    e2e_images = _images(ROOT / "e2e" / "docker-compose.e2e.yml")
    production_images = _images(ROOT / "docker-compose.yml")

    assert e2e_images, "Keine image:-Zeilen in e2e/docker-compose.e2e.yml gefunden"
    assert e2e_images <= production_images, (
        f"E2E-Images {sorted(e2e_images - production_images)} fehlen in docker-compose.yml - "
        "e2e/docker-compose.e2e.yml an die Produktiv-Images angleichen."
    )
