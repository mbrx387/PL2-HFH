"""Run with python -m GetDataFromAPI; API endpoint comes exclusively from configuration."""

import argparse
import logging
import os
from pathlib import Path

from GetDataFromAPI.pipeline import ImportFailure, run


def main():
    parser = argparse.ArgumentParser(
        description="ZQP ETL: Excel, JSON, CSV and changes / Excel, JSON, CSV und Aenderungen"
    )
    parser.add_argument("--baseline", type=Path, default=Path("app/data/pflegestellen.csv"))
    parser.add_argument("--output", type=Path, default=Path("build/GetDataFromAPI/pflegestellen.csv"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run(os.environ.get("ZQP_API_URL", ""), args.baseline, args.output)
    except ImportFailure as error:
        logging.error("%s", error)
        return 1
    except OSError:
        # Never print exception URLs, tokens, payloads or contact details to Actions logs.
        logging.error(
            "ETL failed; no candidate published / ETL fehlgeschlagen; kein Kandidat veroeffentlicht."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
