"""Batch-import an external catalog into the demo product catalog.

The importer keeps the source category in ``source_category`` and assigns
unmapped records to ``其他`` instead of guessing a VoiceShop category.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_FILE = ROOT / "data" / "products.json"


def parse_price(value: Any) -> float:
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", str(value or ""))
    return round(float(match.group(0)), 2) if match else 0.0


def load_products(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def convert_record(record: dict[str, Any], product_id: int) -> dict[str, Any]:
    return {
        "id": product_id,
        "name": record.get("name") or record.get("Product Name") or record.get("product_name"),
        "category": record.get("category") or "其他",
        "source_category": record.get("source_category") or record.get("Category"),
        "brand": record.get("brand") or "External Catalog",
        "price": parse_price(record.get("price") or record.get("Selling Price") or record.get("price_usd")),
        "currency": record.get("currency") or "USD",
        "stock": int(record.get("stock") or 0),
        "rating": record.get("rating"),
        "scene_tags": record.get("scene_tags") or [],
        "feature_tags": record.get("feature_tags") or [],
        "description": record.get("description") or "External catalog product.",
        "image": record.get("image") or record.get("Image"),
        "price_type": "external_snapshot",
        "source_dataset": record.get("source_dataset"),
        "source_url": record.get("source_url"),
    }


def import_catalog(input_path: Path, output_path: Path, start_id: int) -> int:
    records = json.loads(input_path.read_text(encoding="utf-8-sig"))
    current = load_products(output_path)
    existing_names = {item.get("name") for item in current}
    next_id = max([item.get("id", 0) for item in current] + [start_id - 1]) + 1
    added = []
    for record in records:
        name = record.get("name") or record.get("Product Name") or record.get("product_name")
        if not name or name in existing_names:
            continue
        added.append(convert_record(record, next_id))
        existing_names.add(name)
        next_id += 1
    output_path.write_text(json.dumps(current + added, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(added)


def main() -> None:
    parser = argparse.ArgumentParser(description="Append a normalized product catalog to products.json")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=PRODUCTS_FILE)
    parser.add_argument("--start-id", type=int, default=16)
    args = parser.parse_args()
    print(f"imported={import_catalog(args.input, args.output, args.start_id)} output={args.output}")


if __name__ == "__main__":
    main()
