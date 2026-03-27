"""
Metafield definition fetcher and loader.

Fetches PRODUCT and PRODUCTVARIANT metafield definitions from Shopify's
Admin GraphQL API, then stores them as metafield_defs.json in the store
directory so they can be used:

  - Frontend: pick the right cell editor (dropdown for choice fields,
    true/false for boolean, plain text for others)

  - Backend: validate values before calling metafieldsSet so errors
    surface as row ERRORs rather than silent Shopify rejections

Definition structure in metafield_defs.json:
{
  "product": {
    "custom.material": {
      "name":    "Material",
      "type":    "single_line_text_field",
      "choices": ["Cotton", "Polyester", "Silk"],
      "min":     null,
      "max":     null,
      "regex":   null
    },
    "custom.is_sale": {
      "name":    "Is Sale",
      "type":    "boolean",
      "choices": null,
      ...
    }
  },
  "variant": {
    "custom.size_guide": { ... }
  }
}
"""

import json
import os

from products.client import graphql_request


# ── GraphQL query (paginated) ────────────────────────────────────────────────

_DEFS_QUERY = """
query metafieldDefs($ownerType: MetafieldOwnerType!, $cursor: String) {
  metafieldDefinitions(ownerType: $ownerType, first: 250, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      namespace
      key
      name
      type { name }
      validations { name value }
    }
  }
}
"""


# ── Validation parser ─────────────────────────────────────────────────────────

def _parse_validations(validations):
    """
    Parse a Shopify metafield definition's validations list into structured fields.

    Shopify validation names: choices, min, max, min_length, max_length, regex
    Returns (choices, min_val, max_val, regex).
    """
    choices  = None
    min_val  = None
    max_val  = None
    regex    = None

    for v in (validations or []):
        name  = v.get("name", "")
        value = v.get("value", "")

        if name == "choices":
          try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
              choices = [str(x).strip() for x in parsed if str(x).strip()]
            else:
              parsed_str = str(parsed).strip()
              choices = [parsed_str] if parsed_str else []
          except Exception:
            # Fallback: comma-separated plain text
            choices = [x.strip() for x in str(value).split(",") if x.strip()]

        elif name == "min":
            min_val = value

        elif name == "max":
            max_val = value

        elif name == "regex":
            regex = value

    return choices, min_val, max_val, regex


# ── Paginated definition fetcher ─────────────────────────────────────────────

def _fetch_definitions(owner_type):
    """
    Fetch all metafield definitions for a given owner type (PRODUCT / PRODUCTVARIANT).
    Handles Shopify pagination automatically.

    Returns {ns_key: {name, type, choices, min, max, regex}}.
    """
    all_defs = {}
    cursor   = None

    while True:
        variables = {"ownerType": owner_type}
        if cursor:
            variables["cursor"] = cursor

        result = graphql_request(_DEFS_QUERY, variables)
        data   = (result.get("data") or {}).get("metafieldDefinitions", {})

        for node in (data.get("nodes") or []):
            ns_key = f"{node['namespace']}.{node['key']}"
            choices, min_val, max_val, regex = _parse_validations(node.get("validations"))

            all_defs[ns_key] = {
                "name":    node.get("name", ""),
                "type":    (node.get("type") or {}).get("name", "single_line_text_field"),
                "choices": choices,
                "min":     min_val,
                "max":     max_val,
                "regex":   regex,
            }

        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return all_defs


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_and_store_metafield_defs(store_dir):
    """
    Fetch PRODUCT and PRODUCTVARIANT metafield definitions from Shopify.
    Stores result in {store_dir}/metafield_defs.json.

    Called during bulk fetch so definitions are always up to date
    alongside the snapshot.

    Returns the defs dict.
    """
    print("[METAFIELD DEFS] Fetching product definitions...")
    product_defs = _fetch_definitions("PRODUCT")
    print(f"[METAFIELD DEFS] {len(product_defs)} product definition(s) found")

    print("[METAFIELD DEFS] Fetching variant definitions...")
    variant_defs = _fetch_definitions("PRODUCTVARIANT")
    print(f"[METAFIELD DEFS] {len(variant_defs)} variant definition(s) found")

    defs = {"product": product_defs, "variant": variant_defs}

    path = os.path.join(store_dir, "metafield_defs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(defs, f, indent=2, ensure_ascii=False)

    print(f"[METAFIELD DEFS] Saved to {path}")
    return defs


def load_metafield_defs(store_dir):
    """
    Load stored metafield definitions from {store_dir}/metafield_defs.json.
    Returns {"product": {}, "variant": {}} if the file doesn't exist yet.
    """
    path = os.path.join(store_dir, "metafield_defs.json")
    if not os.path.exists(path):
        return {"product": {}, "variant": {}}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
