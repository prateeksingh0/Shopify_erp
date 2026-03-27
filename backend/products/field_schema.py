"""
field_schema.py
===============
Fetches and stores a store-level field schema at FETCH time.
Two data sources:

1. Shopify GraphQL introspection  → enum values for columns like
   'Variant Inventory Policy' and 'Variant Weight Unit'.  These are
   read live from the API so new enum values added by Shopify show up
   automatically on the next FETCH — nothing is hardcoded.

2. Static rule table (_FIELD_VALIDATIONS) stored as DATA here so that
   validation logic in updater.py / ProductGrid.jsx never needs to be
   changed when a rule changes — only this file.

Output: <store_dir>/field_schema.json
Schema:
{
  "enums": {
    "Variant Inventory Policy": ["DENY", "CONTINUE"],
    "Variant Weight Unit":      ["GRAMS", "KILOGRAMS", "OUNCES", "POUNDS"]
  },
  "validations": {
    "Variant Price":            {"type": "decimal",  "min": 0},
    "Variant Compare At Price": {"type": "decimal",  "min": 0},
    "Cost per item":            {"type": "decimal",  "min": 0},
    "Variant Grams":            {"type": "decimal",  "min": 0},
    "SEO Title":                {"type": "text",     "max_length": 70},
    "SEO Description":          {"type": "text",     "max_length": 320},
    "Inventory Qty -":          {"type": "integer",  "min": 0, "prefix_match": true}
  }
}

To add a new validated column in the future:
  - If it has a Shopify enum type → add to _ENUM_FIELDS
  - If it has numeric/text limits → add to _FIELD_VALIDATIONS
  No logic changes anywhere else.
"""

import os
import json

from products.client import graphql_request

# ── Column → Shopify GraphQL enum type name ──────────────────────────────────
# Add new rows here when Shopify adds new enum-backed fields.
_ENUM_FIELDS = {
    "Variant Inventory Policy": "ProductVariantInventoryPolicy",
    "Variant Weight Unit":      "WeightUnit",
}

# ── Static validation rules ───────────────────────────────────────────────────
# "prefix_match": true means the rule applies to any column whose name STARTS
# with the key (used for "Inventory Qty -" dynamic location columns).
_FIELD_VALIDATIONS = {
    "Variant Price":            {"type": "decimal",  "min": 0},
    "Variant Compare At Price": {"type": "decimal",  "min": 0},
    "Cost per item":            {"type": "decimal",  "min": 0},
    "Variant Grams":            {"type": "decimal",  "min": 0},
    "SEO Title":                {"type": "text",     "max_length": 70},
    "SEO Description":          {"type": "text",     "max_length": 320},
    "Inventory Qty -":          {"type": "integer",  "min": 0, "prefix_match": True},
    "Title":              {"type": "required"},
    "Image URLs":         {"type": "url_list"},
    "Collection Handles": {"type": "collection_handles"},
    "Option1 Name":  {"type": "paired", "partner": "Option1 Value"},
    "Option1 Value": {"type": "paired", "partner": "Option1 Name"},
    "Option2 Name":  {"type": "paired", "partner": "Option2 Value"},
    "Option2 Value": {"type": "paired", "partner": "Option2 Name"},
    "Option3 Name":  {"type": "paired", "partner": "Option3 Value"},
    "Option3 Value": {"type": "paired", "partner": "Option3 Name"},
}


def _fetch_enum_values(type_name):
    """Query Shopify GraphQL schema introspection for enum values of `type_name`."""
    result = graphql_request(
        "query($n: String!) { __type(name: $n) { enumValues { name } } }",
        {"n": type_name},
    )
    vals = ((result.get("data") or {}).get("__type") or {}).get("enumValues") or []
    return [v["name"] for v in vals]


def fetch_and_store_field_schema(store_dir):
    """
    Fetch live enum values from Shopify + combine with static rules.
    Writes <store_dir>/field_schema.json and returns the schema dict.
    Called once per FETCH in main.py.
    """
    enums = {}
    for column, gql_type in _ENUM_FIELDS.items():
        try:
            values = _fetch_enum_values(gql_type)
            if values:
                enums[column] = values
                print(f"[SCHEMA] {column}: {values}")
            else:
                print(f"[SCHEMA] Warning: empty enum for '{gql_type}'")
        except Exception as e:
            print(f"[SCHEMA] Warning: could not fetch enum '{gql_type}': {e}")

    schema = {"enums": enums, "validations": _FIELD_VALIDATIONS}

    path = os.path.join(store_dir, "field_schema.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print(f"[SCHEMA] Saved field_schema.json — {len(enums)} enums, {len(_FIELD_VALIDATIONS)} rules")
    return schema


def load_field_schema(store_dir):
    """Load the stored field schema. Returns empty schema if not yet fetched."""
    path = os.path.join(store_dir, "field_schema.json")
    if not os.path.exists(path):
        return {"enums": {}, "validations": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)