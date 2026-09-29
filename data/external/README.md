# External data

These files are small, reviewable fixtures used by the VoiceShop demo.

## Product catalog

`amazon-products-train.parquet` is a 4.6 MB Apache-2.0 dataset subset from
`cvnberk/amazon-products`. `amazon-products-import-100.json` contains 100 filtered
records with product name, source category, description, price, image URL, and source
metadata. The imported records use the `其他` category because the source taxonomy does
not map reliably to VoiceShop's four recommendation categories.

`products-100-cc0.json` and `catalog_import_100.json` are 100-row CC0 catalog fixtures
from ExploreMyData. They are retained as import-format references and are not used to
guess product categories.

## Evaluation and rules

`ecommerce_eval_100.json` contains 100 retail customer-service examples derived from
the Bitext retail ecommerce dataset. Its license is CDLA-Sharing-1.0. The examples are
used for intent and response evaluation, not model training.

`intent_rule_taxonomy.json` is a compact intent summary generated from that sample.
It is used as a reviewable rule reference; it does not replace model-first intent
classification.

All external prices are source snapshots. They are not live quotes, inventory, or
commercial availability guarantees.
