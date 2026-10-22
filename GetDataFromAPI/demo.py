"""Repeatable offline demonstration: generate old/new Excel, JSON and changes."""

from pathlib import Path

from GetDataFromAPI.export import publish_exports
from GetDataFromAPI.pipeline import merge_records
from GetDataFromAPI.transform import convert_item


def main():
    old = convert_item(
        {"id": "demo-1", "name": "Demo Pflegeberatung", "zip": "01067", "email": "old@example.org"}, 1
    )
    old.pop("zqp_raw")
    old["leistungen"] = ", ".join(old["leistungen"])
    new = merge_records(
        [old],
        [
            {"id": "demo-1", "name": "Demo Pflegeberatung", "zip": "01067", "email": "new@example.org"},
            {"id": "demo-2", "name": "Demo Wohnberatung", "zip": "10115"},
        ],
    )
    output = Path("build/GetDataFromAPI/demo/pflegestellen.csv")
    count = publish_exports(output, [old], new)
    print(f"OFFLINE DEMO: {len(new)} records, {count} changes. Files: {output.parent.resolve()}")


if __name__ == "__main__":
    main()
