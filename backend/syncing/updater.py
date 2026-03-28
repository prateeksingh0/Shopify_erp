import pandas as pd
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from syncing.product_update import update_product
from syncing.variant_update import update_variant
from syncing.inventory_item_update import update_inventory_item
from syncing.inventory_update import update_inventory
from syncing.metafield_update import update_metafields
from syncing.collection_update import update_collections, validate_collection_handles
from syncing.image_update import upload_image, update_image_alt, delete_image
from syncing.creator import run_creation
from products.client import graphql_request
from products.metafield_defs import load_metafield_defs
from products.field_schema import load_field_schema


# ── Delete mutations ─────────────────────────────────────────────────────────

PRODUCT_DELETE = """
mutation productDelete($id: ID!) {
  productDelete(input: {id: $id}) {
    deletedProductId
    userErrors { field message }
  }
}
"""

VARIANT_DELETE = """
mutation productVariantsBulkDelete($productId: ID!, $variantsIds: [ID!]!) {
  productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
    product { id }
    userErrors { field message }
  }
}
"""

# ── Tuning ──────────────────────────────────────────────────────────────────
MAX_WORKERS = 8   # concurrent row workers — conservative to stay under throttle
# ────────────────────────────────────────────────────────────────────────────


# ------------------------------------------------
# Normalize helper
# ------------------------------------------------

def normalize(value):
    """
    Converts any value to a clean comparable string.

    Numeric normalization prevents false deltas:
      '850.00' → '850'
      '850'    → '850'
      '24.95'  → '24.95'
      NaN/None → ''
    """

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    if value is None:
        return ""

    if isinstance(value, float) and value != value:
        return ""

    try:
        f = float(str(value).strip())
        if f == int(f):
            return str(int(f))
        return str(f)
    except (ValueError, TypeError):
        pass

    return str(value).strip()


def normalize_url(url):
    """
    Strip CDN query parameters (?v=timestamp) from Shopify image URLs
    before comparison.  Without this, every row looks like the image
    changed on every sync because Shopify rotates the ?v= stamp.
    """
    if not url:
        return ""
    return str(url).split("?")[0].strip()


def _first_csv(val):
    """
    Extract the first value from a comma-separated CSV cell.
    Returns empty string for nan/none placeholders.
    """
    s = str(val or "").split(",")[0].strip()
    return "" if s.lower() in ("nan", "none") else s


def _normalize_tags_text(raw):
    """Normalize comma-separated tags: trim, dedupe (case-insensitive), stable sort."""
    seen = set()
    out = []
    for t in str(raw or "").split(","):
        tag = t.strip()
        if not tag:
            continue
        low = tag.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(tag)
    out.sort(key=lambda x: x.lower())
    return ", ".join(out)


# ------------------------------------------------
# Snapshot loader
# ------------------------------------------------

def load_snapshot(snapshot_path):

    print("[SYNC] Loading snapshot:", snapshot_path)

    if not os.path.exists(snapshot_path):
        raise Exception(f"[SYNC] Snapshot not found: {snapshot_path}")

    with open(snapshot_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    products = snapshot["data"]

    print("[SYNC] Snapshot products:", len(products))

    return products


# ------------------------------------------------
# Snapshot path resolver
# ------------------------------------------------

def resolve_snapshot_path(csv_path):

    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    store_dir = os.path.dirname(csv_dir)
    return os.path.join(store_dir, "snapshots", "latest_snapshot.json")


# ------------------------------------------------
# Variant lookup
# ------------------------------------------------

def get_variant(snapshot_products, product_id, variant_id):

    product = snapshot_products.get(product_id)

    if not product:
        return None

    for v in product["variants"]:
        if v["variant"]["id"] == variant_id:
            return v

    return None


# ------------------------------------------------
# Propagate product-level fields to all variant rows
# ------------------------------------------------

def propagate_product_fields(df, product_id, changed_fields, source_row):
    """
    When a product-level field changes on one variant row,
    copy that new value to ALL other rows with the same Product ID.

    WHY THIS IS NEEDED:
    Product has 5 variants = 5 rows in CSV.
    User edits SEO Title on row 15 only.
    Rows 16-19 still have the old value.

    After sync:
      Shopify = NEW VALUE
      Row 15  = NEW VALUE  ← correct
      Row 16  = OLD VALUE  ← stale

    Next sync after re-fetch:
      Snapshot = NEW VALUE (from Shopify)
      Row 16 CSV = OLD VALUE → looks changed → false delta → fires again

    Fix: after updating product, copy new value to all sibling rows.
    This keeps all variant rows in sync with Shopify state.
    """

    sibling_mask = df["Product ID"] == product_id

    for field in changed_fields:
        if field in df.columns:
            new_value = source_row.get(field)
            df.loc[sibling_mask, field] = new_value

    sibling_count = sibling_mask.sum()
    if sibling_count > 1:
        print(f"[PROPAGATE] Synced {len(changed_fields)} product field(s) to {sibling_count} variant rows")


# ------------------------------------------------
# Separate product vs variant metafield columns
# ------------------------------------------------

def split_metafield_columns(all_columns, snapshot_products, product_id, variant_id):
    """
    Split metafield columns into two groups:
      - product_meta_cols: belong to the product (shared across all variants)
      - variant_meta_cols: belong specifically to this variant
    """

    product_meta_cols = []
    variant_meta_cols = []

    if not snapshot_products or not product_id:
        product_meta_cols = [
            c for c in all_columns
            if "." in c and not c.startswith("Inventory Qty -")
        ]
        return product_meta_cols, variant_meta_cols

    product_snap = snapshot_products.get(product_id, {})
    product_mf_keys = set(product_snap.get("product_metafields", {}).keys())

    variant_mf_keys = set()
    for v_entry in product_snap.get("variants", []):
        if v_entry["variant"].get("id") == variant_id:
            variant_mf_keys = set(v_entry.get("metafields", {}).keys())
            break

    SEO_METAFIELDS = {"global.title_tag", "global.description_tag"}

    for col in all_columns:

        if "." not in col:
            continue

        if col.startswith("Inventory Qty -"):
            continue

        if col in SEO_METAFIELDS:
            continue

        if col in variant_mf_keys:
            variant_meta_cols.append(col)
        else:
            product_meta_cols.append(col)

    return product_meta_cols, variant_meta_cols


# ------------------------------------------------
# Change detection
# ------------------------------------------------

def detect_changes(row, snapshot_products, all_columns):

    product_id = row.get("Product ID")
    variant_id = row.get("Variant ID")

    product = snapshot_products.get(product_id)

    if not product:
        print("[DELTA] New product detected:", product_id)
        return ["NEW_PRODUCT"]

    variant = get_variant(snapshot_products, product_id, variant_id)

    if not variant:
        print("[DELTA] New variant detected:", variant_id)
        return ["NEW_VARIANT"]

    product_data = product["product"]
    variant_data = variant["variant"]

    changes = []

    # -------------------------
    # Product fields
    # -------------------------

    product_mapping = {
        "Title":           product_data.get("title"),
        "Body (HTML)":     product_data.get("descriptionHtml"),
        "Vendor":          product_data.get("vendor"),
        "Type":            product_data.get("productType"),
        "Status":          product_data.get("status"),
        "Handle":          product_data.get("handle"),
        "Tags":            ", ".join(product_data.get("tags", [])),
        "SEO Title":       (product_data.get("seo") or {}).get("title"),
        "SEO Description": (product_data.get("seo") or {}).get("description"),
    }

    for column, snapshot_value in product_mapping.items():
        if column not in all_columns:
            continue
        current = normalize(row.get(column))
        previous = normalize(snapshot_value)
        if current != previous:
            print(f"[DELTA] {column}: {repr(previous)} → {repr(current)}")
            changes.append(column)

    # -------------------------
    # Variant fields
    # -------------------------

    selected_options = variant_data.get("selectedOptions") or []
    option_snap = {}
    for i, opt in enumerate(selected_options[:3], start=1):
        option_snap[f"Option{i} Name"]  = opt.get("name")
        option_snap[f"Option{i} Value"] = opt.get("value")

    variant_mapping = {
        "Variant Price":            variant_data.get("price"),
        "Variant Compare At Price": variant_data.get("compareAtPrice"),
        "Variant Barcode":          variant_data.get("barcode"),
        "Variant Inventory Policy": variant_data.get("inventoryPolicy"),
        "Variant Tax Code":         variant_data.get("taxCode"),
    }

    for column, snapshot_value in variant_mapping.items():
        if column not in all_columns:
            continue
        current = normalize(row.get(column))
        previous = normalize(snapshot_value)
        if current != previous:
            print(f"[DELTA] {column}: {repr(previous)} → {repr(current)}")
            changes.append(column)

    # Option columns — plain string compare, never numeric normalize
    option_columns = {
        "Option1 Name":  option_snap.get("Option1 Name"),
        "Option1 Value": option_snap.get("Option1 Value"),
        "Option2 Name":  option_snap.get("Option2 Name"),
        "Option2 Value": option_snap.get("Option2 Value"),
        "Option3 Name":  option_snap.get("Option3 Name"),
        "Option3 Value": option_snap.get("Option3 Value"),
    }

    def _norm_option(val):
        """Normalize option value — treat nan/none/empty as empty string."""
        s = str(val or "").strip()
        return "" if s.lower() in ("nan", "none") else s

    for column, snapshot_value in option_columns.items():
        if column not in all_columns:
            continue
        current  = _norm_option(row.get(column))
        previous = _norm_option(snapshot_value)
        if current != previous:
            print(f"[DELTA] {column}: {repr(previous)} → {repr(current)}")
            changes.append(column)

    # -------------------------
    # Inventory item fields
    # -------------------------

    inventory_item = (variant_data.get("inventoryItem") or {})
    unit_cost = (inventory_item.get("unitCost") or {})
    measurement = (inventory_item.get("measurement") or {})
    weight = (measurement.get("weight") or {})

    inventory_item_mapping = {
        "Variant SKU":         variant_data.get("sku"),
        "Cost per item":       unit_cost.get("amount"),
        "Variant Grams":       weight.get("value"),
        "Variant Weight Unit": weight.get("unit"),
    }

    for column, snapshot_value in inventory_item_mapping.items():
        if column not in all_columns:
            continue
        current = normalize(row.get(column))
        previous = normalize(snapshot_value)
        if current != previous:
            print(f"[DELTA] {column}: {repr(previous)} → {repr(current)}")
            changes.append(column)

    # -------------------------
    # Metafields
    # -------------------------

    SEO_METAFIELDS = {"global.title_tag", "global.description_tag"}

    product_metafields = product.get("product_metafields", {})
    variant_metafields = variant.get("metafields", {})

    for column in all_columns:

        if "." not in column:
            continue

        if column.startswith("Inventory Qty -"):
            continue

        if column in SEO_METAFIELDS:
            continue

        current = normalize(row.get(column))

        p_entry = product_metafields.get(column)
        v_entry = variant_metafields.get(column)
        raw = p_entry or v_entry

        if isinstance(raw, dict):
            snapshot_value = raw.get("value")
        else:
            snapshot_value = raw

        previous = normalize(snapshot_value)

        if current != previous:
            print(f"[DELTA] Metafield {column}: {repr(previous)} → {repr(current)}")
            changes.append(column)

    # -------------------------
    # Inventory levels
    # -------------------------

    snapshot_inventory = variant.get("inventory", {})

    for column in all_columns:

        if not column.startswith("Inventory Qty -"):
            continue

        location = column.replace("Inventory Qty - ", "")
        current = normalize(row.get(column))
        previous = normalize(snapshot_inventory.get(location))

        if current != previous:
            print(f"[DELTA] Inventory at {location}: {repr(previous)} → {repr(current)}")
            changes.append(column)

    # -------------------------
    # Collections
    # -------------------------

    def _csv_tokens(val):
        return [
            x.strip().lower() for x in str(val or "").split(",")
            if x.strip() and x.strip().lower() not in ("nan", "none", "null")
        ]

    if "Collection Handles" not in all_columns:
        pass  # skip collection check
    else:
        current_handles = sorted(dict.fromkeys(_csv_tokens(row.get("Collection Handles", ""))))
        snapshot_handles = sorted(dict.fromkeys(_csv_tokens(product.get("collection_handles", ""))))
        if current_handles != snapshot_handles:
            print(f"[DELTA] Collection Handles: {repr(', '.join(snapshot_handles))} → {repr(', '.join(current_handles))}")
            changes.append("Collection Handles")

    # -------------------------
    # Images (all images, comma-separated)
    # Normalize URLs to strip ?v=timestamp before comparing so CDN
    # cache-busting params never cause false deltas.
    # -------------------------

    snapshot_images = product.get("images", [])
    snap_urls = [normalize_url(i.get("url", "")) for i in snapshot_images]
    snap_alts = [normalize(i.get("alt", "") or "") for i in snapshot_images]

    def _split_csv(val):
        """Split comma-separated cell into cleaned list, drop empties."""
        return [v.strip() for v in str(val or "").split(",") if v.strip() and v.strip().lower() not in ("nan", "none")]

    if "Image URLs" in all_columns or "Image Alt Text" in all_columns:
        current_urls = [normalize_url(u) for u in _split_csv(row.get("Image URLs", ""))]
        current_alts = _split_csv(row.get("Image Alt Text", ""))
        while len(current_alts) < len(current_urls):
            current_alts.append("")
        if current_urls != snap_urls:
            print(f"[DELTA] Image URLs: {snap_urls} → {current_urls}")
            changes.append("Image URLs")
        else:
            for i, (cur_alt, snp_alt) in enumerate(zip(current_alts, snap_alts)):
                if normalize(cur_alt) != snp_alt:
                    print(f"[DELTA] Image Alt Text[{i}]: {repr(snp_alt)} → {repr(cur_alt)}")
                    changes.append("Image Alt Text")
                    break

    return list(set(changes))


# ------------------------------------------------
# Conflict detection
# ------------------------------------------------

def check_conflict(product_id, snapshot_products):
    """
    Compare Shopify's current updatedAt against snapshot's updatedAt.
    If Shopify was updated after the snapshot → conflict.

    Returns True if conflict detected, False if safe to update.
    """
    try:
        product_snap = snapshot_products.get(product_id, {})
        snapshot_updated_at = product_snap.get("product", {}).get("updatedAt")

        if not snapshot_updated_at:
            return False  # No timestamp in snapshot — allow update

        query = """
        query($id: ID!) {
          product(id: $id) {
            updatedAt
          }
        }
        """
        result = graphql_request(query, {"id": product_id})
        live_updated_at = (
            (result.get("data") or {})
            .get("product", {})
            .get("updatedAt")
        )

        if not live_updated_at:
            return False

        if live_updated_at > snapshot_updated_at:
            print(f"[CONFLICT] Product {product_id} was updated on Shopify after your snapshot")
            print(f"[CONFLICT] Snapshot: {snapshot_updated_at}")
            print(f"[CONFLICT] Shopify:  {live_updated_at}")
            print(f"[CONFLICT] Skipping row — Refresh to get latest data")
            return True

        return False

    except Exception as e:
        # On error — allow update rather than block everything
        print(f"[CONFLICT] Check failed ({e}) — proceeding with update")
        return False


# ------------------------------------------------
# Field groups
# ------------------------------------------------

PRODUCT_FIELDS = [
    "Title",
    "Body (HTML)",
    "Vendor",
    "Type",
    "Tags",
    "Status",
    "Handle",
    "SEO Title",
    "SEO Description"
]

VARIANT_FIELDS = [
    "Variant Price",
    "Variant Compare At Price",
    "Variant Barcode",
    "Variant Tax Code",
    "Variant Inventory Policy",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Option3 Name",
    "Option3 Value",
]

INVENTORY_ITEM_FIELDS = [
    "Variant SKU",
    "Cost per item",
    "Variant Grams",
    "Variant Weight Unit"
]

IMAGE_FIELDS = [
    "Image URLs",
    "Image Alt Text",
]


def _build_allowed_vendor_set(snapshot_products):
    """Build a normalized vendor set from snapshot data (dynamic, per store)."""
    allowed = set()
    for product in snapshot_products.values():
        vendor = ((product.get("product") or {}).get("vendor") or "").strip()
        if vendor:
            allowed.add(vendor.lower())
    return allowed


def _build_allowed_status_set(snapshot_products):
    """Build a normalized product status set from snapshot data (dynamic, per store)."""
    allowed = set()
    for product in snapshot_products.values():
        status = ((product.get("product") or {}).get("status") or "").strip()
        if status:
            allowed.add(status.lower())
    return allowed


def _build_allowed_type_set(snapshot_products):
    """Build a normalized product type set from snapshot data (dynamic, per store)."""
    allowed = set()
    for product in snapshot_products.values():
        product_type = ((product.get("product") or {}).get("productType") or "").strip()
        if product_type:
            allowed.add(product_type.lower())
    return allowed


def _build_handle_owner_map(snapshot_products):
    """Build handle -> product id map from snapshot data (dynamic, per store)."""
    owners = {}
    for product_id, product in snapshot_products.items():
        handle = ((product.get("product") or {}).get("handle") or "").strip().lower()
        if handle:
            owners[handle] = product_id
    return owners


def _validate_from_schema(row, changes, field_schema):
    """
    Validate changed columns against the stored field_schema.
    Raises ValueError on the first violation found.
    Covers: enum-backed fields, decimal/integer range checks, text length checks.
    prefix_match=True rules apply to any column whose name starts with the pattern
    (e.g. 'Inventory Qty -' matches all dynamic location qty columns).
    """
    enums       = field_schema.get("enums", {})
    validations = field_schema.get("validations", {})

    for col in changes:
        raw   = str(row.get(col) or "").strip()
        empty = not raw or raw.lower() in ("nan", "none")

        # Enum check
        if col in enums and not empty:
            allowed_upper = [v.upper() for v in enums[col]]
            if raw.upper() not in allowed_upper:
                raise ValueError(f"'{col}': '{raw}' must be one of {enums[col]}")

        # Rule-based check
        for pattern, rule in validations.items():
            matches = col.startswith(pattern) if rule.get("prefix_match") else col == pattern
            if not matches:
                continue
            vtype = rule.get("type")

            if vtype == "required":
                if empty:
                    raise ValueError(f"'{col}' is required and cannot be empty")

            elif vtype == "url_list" and not empty:
                import re as _re
                for token in raw.split(","):
                    token = token.strip()
                    if token and not _re.match(r"^https?://", token, _re.IGNORECASE):
                        raise ValueError(
                            f"'{col}': '{token}' is not a valid URL (must start with http:// or https://)"
                        )

            elif vtype == "paired" and not empty:
                partner = rule.get("partner")
                if partner:
                    partner_raw = str(row.get(partner) or "").strip()
                    if not partner_raw or partner_raw.lower() in ("nan", "none"):
                        raise ValueError(
                            f"'{col}' is set but '{partner}' is empty — both must be filled together"
                        )

            elif vtype == "decimal" and not empty:
                try:
                    fv = float(raw)
                except (ValueError, TypeError):
                    raise ValueError(f"'{col}' must be a valid number, got: '{raw}'")
                if rule.get("min") is not None and fv < rule["min"]:
                    raise ValueError(f"'{col}' must be ≥ {rule['min']}, got: {raw}")

            elif vtype == "integer" and not empty:
                try:
                    fv = float(raw)
                    if fv != int(fv):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ValueError(f"'{col}' must be a whole number, got: '{raw}'")
                if rule.get("min") is not None and fv < rule["min"]:
                    raise ValueError(f"'{col}' must be ≥ {rule['min']}, got: {raw}")

            elif vtype == "text" and not empty and rule.get("max_length"):
                if len(raw) > rule["max_length"]:
                    raise ValueError(
                        f"'{col}' is too long ({len(raw)} chars, max {rule['max_length']}"
                    )
            break


def _validate_metafield_value(column, value, defn):
    """
    Validate a single metafield value against its stored definition.
    Returns (ok, error_message, normalized_value).

        Validates:
            - choices  → value must be one of the allowed list
      - boolean  → must be 'true' or 'false'
      - number_integer → must parse as int, optional min/max
      - number_decimal → must parse as float, optional min/max
      - date          → YYYY-MM-DD format
      - date_time     → ISO 8601 format
        All other types pass through without blocking.

        Choice matching is tolerant for numeric-like values from CSV parsing:
            '1.0' can match choice '1'
            '2' can match choice '2.0'
        The matched canonical choice string is returned as normalized_value.
    """
    import re as _re

    mf_type = defn.get("type", "single_line_text_field")
    choices  = defn.get("choices")
    min_val  = defn.get("min")
    max_val  = defn.get("max")

    normalized_value = value

    # ── Choice validation (highest priority) ─────────────────────────────────
    if choices is not None:
        str_choices = [str(c) for c in choices]

        if value in str_choices:
            normalized_value = value
        else:
            # Tolerate numeric formatting differences (e.g., 1.0 vs 1)
            matched = None
            try:
                n_value = float(value)
                for c in str_choices:
                    try:
                        if float(c) == n_value:
                            matched = c
                            break
                    except (ValueError, TypeError):
                        continue
            except (ValueError, TypeError):
                matched = None

            if matched is None:
                return False, (
                    f"Metafield '{column}' value '{value}' is not in allowed choices: {str_choices}",
                    normalized_value,
                )

            normalized_value = matched

    # ── Type-based validation ─────────────────────────────────────────────────
    if mf_type == "boolean":
        low = normalized_value.lower()
        if low not in ("true", "false"):
            return False, (
                f"Metafield '{column}' must be 'true' or 'false', got: '{value}'"
            ), normalized_value
        normalized_value = low

    elif mf_type == "number_integer":
        try:
            int_val = int(normalized_value)
        except (ValueError, TypeError):
            return False, f"Metafield '{column}' must be an integer, got: '{value}'", normalized_value
        if min_val is not None:
            try:
                if int_val < int(min_val):
                    return False, (
                        f"Metafield '{column}' value {int_val} is below minimum {min_val}"
                    )
            except (ValueError, TypeError):
                pass
        if max_val is not None:
            try:
                if int_val > int(max_val):
                    return False, (
                        f"Metafield '{column}' value {int_val} exceeds maximum {max_val}"
                    ), normalized_value
            except (ValueError, TypeError):
                pass

        normalized_value = str(int_val)

    elif mf_type == "number_decimal":
        try:
            float_val = float(normalized_value)
        except (ValueError, TypeError):
            return False, (
                f"Metafield '{column}' must be a decimal number, got: '{value}'"
            ), normalized_value
        if min_val is not None:
            try:
                if float_val < float(min_val):
                    return False, (
                        f"Metafield '{column}' value {float_val} is below minimum {min_val}"
                    )
            except (ValueError, TypeError):
                pass
        if max_val is not None:
            try:
                if float_val > float(max_val):
                    return False, (
                        f"Metafield '{column}' value {float_val} exceeds maximum {max_val}"
                    ), normalized_value
            except (ValueError, TypeError):
                pass

        normalized_value = str(float_val)

    elif mf_type == "date":
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", normalized_value):
            return False, (
                f"Metafield '{column}' must be YYYY-MM-DD date format, got: '{value}'"
            ), normalized_value

    elif mf_type == "date_time":
        if not _re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", normalized_value):
            return False, (
                f"Metafield '{column}' must be ISO 8601 datetime format, got: '{value}'"
            ), normalized_value

    return True, "", normalized_value


# ------------------------------------------------
# Image update handler
# ------------------------------------------------

def _handle_image_update(row, product_id, snapshot_products):
    """
    Reconcile the full image list for a product.

    Algorithm (order-based, positional):
      - Build snapshot dict: normalized_url → {id, alt}
      - Build current list: [(normalized_url, raw_url, alt), ...]
      - URLs in current but NOT in snapshot → upload (new image)
      - URLs in snapshot but NOT in current → delete (removed image)
      - Same URL, different alt             → update_image_alt only

    Uploads happen before deletes so the product is never left image-less.
    """

    def _split_csv(val):
        return [v.strip() for v in str(val or "").split(",") if v.strip() and v.strip().lower() not in ("nan", "none")]

    snapshot_images = snapshot_products.get(product_id, {}).get("images", [])
    # snap_map: normalized_url → {id, alt}
    snap_map = {
        normalize_url(img.get("url", "")): {
            "id":  img.get("id"),
            "alt": normalize(img.get("alt") or ""),
        }
        for img in snapshot_images
        if img.get("url")
    }

    raw_urls = _split_csv(row.get("Image URLs", ""))
    raw_alts = _split_csv(row.get("Image Alt Text", ""))
    # Pad alts so every URL has a matching alt (empty string if missing)
    while len(raw_alts) < len(raw_urls):
        raw_alts.append("")

    current_normalized = [normalize_url(u) for u in raw_urls]

    # ── Step 1: Upload new images first ──────────────────────────────────────
    for i, (norm_url, raw_url, alt) in enumerate(zip(current_normalized, raw_urls, raw_alts)):
        if norm_url not in snap_map:
            print(f"[IMAGE] New image at position {i}: {norm_url}")
            upload_image(product_id, norm_url, alt)

    # ── Step 2: Delete removed images ────────────────────────────────────────
    for norm_url, snap_entry in snap_map.items():
        if norm_url not in current_normalized:
            media_id = snap_entry.get("id")
            if media_id:
                # Cache locally before deleting so rollback can restore it
                # even after Shopify permanently removes the CDN file
                from syncing.image_update import _cache_image_locally
                _cache_image_locally(norm_url)
                print(f"[IMAGE] Removing image: {norm_url}")
                delete_image(product_id, media_id)

    # ── Step 3: Update alt text for unchanged URLs ────────────────────────────
    for norm_url, alt in zip(current_normalized, raw_alts):
        if norm_url in snap_map:
            snap_entry = snap_map[norm_url]
            if normalize(alt) != snap_entry["alt"]:
                media_id = snap_entry.get("id")
                if media_id:
                    print(f"[IMAGE] Updating alt for: {norm_url}")
                    update_image_alt(product_id, media_id, alt)


# ------------------------------------------------
# Single row processor
# ------------------------------------------------

def process_row(
    index, row, all_columns,
    snapshot_products, location_map,
    updated_products, updated_metafields, updated_collections, updated_images,
    allowed_vendors,
    allowed_statuses,
    allowed_types,
    handle_owners,
    metafield_defs,
    field_schema,
    lock
):
    """
    Process a single CSV row — detect changes and fire updates.
    Returns (index, status, propagations) where propagations is a list of
    (product_id, fields, row) tuples to apply after all workers finish.
    """

    propagations = []

    try:

        pid = str(row.get("Product ID") or "").strip().lower()
        if not pid or pid in ("nan", "none", ""):
            return index, "SKIPPED", propagations

        vid = str(row.get("Variant ID") or "").strip().lower()
        if not vid or vid in ("nan", "none", ""):
            return index, "SKIPPED", propagations

        changes = detect_changes(row, snapshot_products, all_columns)

        if not changes:
            print(f"[SYNC] No changes detected — skipping")
            return index, "SKIPPED", propagations

        print(f"[SYNC] Changes detected: {changes}")

        product_id = row.get("Product ID")
        variant_id = row.get("Variant ID")

        # ── Conflict check ───────────────────────────────────────────────────
        # Only check if there are actual field changes (not just inventory)
        non_inventory_changes = [
            c for c in changes
            if not c.startswith("Inventory Qty -")
        ]
        if non_inventory_changes:
            if check_conflict(product_id, snapshot_products):
                return index, "CONFLICT", propagations

        # ── Product fields — once per product ────────────────────────────────
        if any(c in PRODUCT_FIELDS for c in changes):

            if "Tags" in changes:
                row["Tags"] = _normalize_tags_text(row.get("Tags"))

            if "Vendor" in changes:
                new_vendor = str(row.get("Vendor") or "").strip().lower()
                if new_vendor and new_vendor not in allowed_vendors:
                    raise ValueError(
                        f"Invalid Vendor: {row.get('Vendor')} (not found in store vendor list)"
                    )

            if "Status" in changes:
                new_status = str(row.get("Status") or "").strip().lower()
                if new_status and new_status not in allowed_statuses:
                    raise ValueError(
                        f"Invalid Status: {row.get('Status')} (not found in store status list)"
                    )

            if "Type" in changes:
                new_type = str(row.get("Type") or "").strip().lower()
                if new_type and new_type not in allowed_types:
                    raise ValueError(
                        f"Invalid Type: {row.get('Type')} (not found in store type list)"
                    )

            if "Handle" in changes:
                new_handle = str(row.get("Handle") or "").strip().lower()
                if new_handle:
                    owner = handle_owners.get(new_handle)
                    if owner and owner != product_id:
                        raise ValueError(
                            f"Invalid Handle: {row.get('Handle')} (already used by another product)"
                        )

            # SEO length + any other product-level text rules from field_schema
            _validate_from_schema(row, [c for c in changes if c in PRODUCT_FIELDS], field_schema)

            with lock:
                already_done = product_id in updated_products
                if not already_done:
                    updated_products.add(product_id)

            if not already_done:
                print("[ACTION] Updating product fields")
                update_product(row)
                changed_product_fields = [c for c in changes if c in PRODUCT_FIELDS]
                propagations.append((product_id, changed_product_fields, dict(row)))
            else:
                print("[SKIP] Product fields already updated this run")

        # ── Variant fields ───────────────────────────────────────────────────
        if any(c in VARIANT_FIELDS for c in changes):
            _validate_from_schema(row, [c for c in changes if c in VARIANT_FIELDS], field_schema)
            print("[ACTION] Updating variant")
            update_variant(row)

        # ── Inventory item fields ────────────────────────────────────────────
        if any(c in INVENTORY_ITEM_FIELDS for c in changes):
            _validate_from_schema(row, [c for c in changes if c in INVENTORY_ITEM_FIELDS], field_schema)
            print("[ACTION] Updating inventory item")
            update_inventory_item(row)

        # ── Inventory levels ─────────────────────────────────────────────────
        if any(c.startswith("Inventory Qty -") for c in changes):
            _validate_from_schema(row, [c for c in changes if c.startswith("Inventory Qty -")], field_schema)
            print("[ACTION] Updating inventory levels")
            update_inventory(row, location_map, all_columns, snapshot_products)

        # ── Metafields ───────────────────────────────────────────────────────
        has_metafield_changes = any(
            "." in c and not c.startswith("Inventory Qty -")
            for c in changes
        )

        if has_metafield_changes:

            # ── Validate metafield values against stored definitions ──────────
            _SEO_METAS = {"global.title_tag", "global.description_tag"}
            _product_mf_defs = metafield_defs.get("product", {})
            _variant_mf_defs = metafield_defs.get("variant", {})
            normalized_mf_values = {}

            for col in changes:
                if "." not in col or col.startswith("Inventory Qty -") or col in _SEO_METAS:
                    continue
                val = str(row.get(col) or "").strip()
                if not val or val.lower() in ("nan", "none"):
                    continue
                # Variant definition takes priority over product definition
                defn = _variant_mf_defs.get(col) or _product_mf_defs.get(col)
                if not defn:
                    continue
                ok, msg, normalized_val = _validate_metafield_value(col, val, defn)
                if not ok:
                    raise ValueError(msg)
                # Keep canonical value for Shopify payload only.
                # Do not mutate pandas row object here; dtype coercion can crash later.
                normalized_mf_values[col] = normalized_val
            # ────────────────────────────────────────────────────────────────

            row_for_metafields = dict(row)
            row_for_metafields.update(normalized_mf_values)

            product_meta_cols, variant_meta_cols = split_metafield_columns(
                all_columns, snapshot_products, product_id, variant_id
            )

            product_meta_changes = [c for c in changes if c in product_meta_cols]

            if product_meta_changes:
                with lock:
                    already_done = product_id in updated_metafields
                    if not already_done:
                        updated_metafields.add(product_id)

                if not already_done:
                    print("[ACTION] Updating product metafields")
                    update_metafields(
                        row_for_metafields, product_meta_cols, snapshot_products,
                        owner_id_override=product_id
                    )
                    propagations.append((product_id, product_meta_changes, dict(row)))
                else:
                    print("[SKIP] Product metafields already updated this run")

            variant_meta_changes = [c for c in changes if c in variant_meta_cols]

            if variant_meta_changes:
                print("[ACTION] Updating variant metafields")
                update_metafields(
                    row_for_metafields, variant_meta_cols, snapshot_products,
                    owner_id_override=variant_id
                )

        # ── Collections — once per product ───────────────────────────────────
        if "Collection Handles" in changes:

            ok, validation_msg = validate_collection_handles(row)
            if not ok:
                raise ValueError(validation_msg)

            with lock:
                already_done = product_id in updated_collections
                if not already_done:
                    updated_collections.add(product_id)

            if not already_done:
                print("[ACTION] Updating collections")
                update_collections(row)
            else:
                print("[SKIP] Collections already updated for this product")

        # ── Images — once per product ─────────────────────────────────────────
        if any(c in IMAGE_FIELDS for c in changes):

            with lock:
                already_done = product_id in updated_images
                if not already_done:
                    updated_images.add(product_id)

            if not already_done:
                print("[ACTION] Updating product image")
                _handle_image_update(row, product_id, snapshot_products)
                image_changes = [c for c in changes if c in IMAGE_FIELDS]
                propagations.append((product_id, image_changes, dict(row)))
            else:
                print("[SKIP] Image already updated for this product this run")

        return index, "UPDATED", propagations

    except Exception as e:
        print(f"[ERROR] Row {index} failed: {e}")
        import traceback
        traceback.print_exc()
        return index, "ERROR", propagations


# ------------------------------------------------
# Delete phase
# ------------------------------------------------

def run_delete_phase(df, progress_callback=None):
    """
    Scan rows where Delete == 'YES', delete from Shopify, return (deleted_indices, count).

    Decision:
      - No Variant ID OR deleting all variants of a product → productDelete (whole product)
      - Deleting some variants of a multi-variant product   → productVariantsBulkDelete
    """
    if "Delete" not in df.columns:
        return set(), 0

    delete_mask = df["Delete"].astype(str).str.strip().str.upper() == "YES"
    delete_rows = df[delete_mask]

    if delete_rows.empty:
        return set(), 0

    print(f"\n[DELETE] Found {len(delete_rows)} row(s) marked for deletion")

    # Group DELETE=YES rows by Product ID
    product_groups = {}
    for idx, row in delete_rows.iterrows():
        pid = str(row.get("Product ID") or "").strip()
        vid = str(row.get("Variant ID") or "").strip()
        if not pid or pid.lower() in ("nan", "none", ""):
            continue
        if pid not in product_groups:
            product_groups[pid] = []
        product_groups[pid].append((idx, vid))

    # Count total variant rows per product across the entire dataframe
    total_variant_counts = df.groupby("Product ID").size().to_dict()

    deleted_indices = set()
    deleted_count = 0

    for pid, entries in product_groups.items():
        total_variants = total_variant_counts.get(pid, 1)
        delete_count = len(entries)
        first_vid = entries[0][1]
        no_vid = not first_vid or first_vid.lower() in ("nan", "none", "")

        try:
            if no_vid or total_variants <= delete_count:
                # Delete entire product
                print(f"[DELETE] Deleting product {pid}")
                result = graphql_request(PRODUCT_DELETE, {"id": pid})
                errors = (((result.get("data") or {})
                           .get("productDelete") or {})
                          .get("userErrors") or [])
                if errors:
                    print(f"[DELETE] userErrors for {pid}: {errors}")
                    continue
            else:
                # Delete specific variants only
                variant_ids = [
                    vid for _, vid in entries
                    if vid and vid.lower() not in ("nan", "none", "")
                ]
                print(f"[DELETE] Deleting {len(variant_ids)} variant(s) from {pid}")
                result = graphql_request(
                    VARIANT_DELETE,
                    {"productId": pid, "variantsIds": variant_ids}
                )
                errors = (((result.get("data") or {})
                           .get("productVariantsBulkDelete") or {})
                          .get("userErrors") or [])
                if errors:
                    print(f"[DELETE] userErrors for {pid}: {errors}")
                    continue

            for idx, vid in entries:
                deleted_indices.add(idx)
                deleted_count += 1
                if progress_callback:
                    progress_callback(
                        row_index=int(idx),
                        variant_id=vid,
                        status="DELETED",
                        changes=[],
                        error=None,
                    )

        except Exception as e:
            print(f"[DELETE] Failed for product {pid}: {e}")
            import traceback
            traceback.print_exc()

    print(f"[DELETE] Deleted {deleted_count} row(s)\n")
    return deleted_indices, deleted_count


# ------------------------------------------------
# Main updater
# ------------------------------------------------

def run_updates(csv_path, location_map, product_id_filter=None, progress_callback=None):

    print("\n====================================")
    print("[UPDATE] Shopify Sync Started")
    print("====================================\n")

    df = pd.read_csv(csv_path, dtype=str).fillna('')

    if "Sync Status" not in df.columns:
        df["Sync Status"] = ""

    df["Sync Status"] = df["Sync Status"].astype(str)

    snapshot_path = resolve_snapshot_path(csv_path)
    snapshot_products = load_snapshot(snapshot_path)
    allowed_vendors  = _build_allowed_vendor_set(snapshot_products)
    allowed_statuses = _build_allowed_status_set(snapshot_products)
    allowed_types    = _build_allowed_type_set(snapshot_products)
    handle_owners    = _build_handle_owner_map(snapshot_products)

    # Load definition-driven metafield validation map (best-effort — empty if not fetched yet)
    store_dir = os.path.dirname(os.path.dirname(os.path.abspath(csv_path)))
    metafield_defs = load_metafield_defs(store_dir)
    field_schema   = load_field_schema(store_dir)

    all_columns = list(df.columns)

    if product_id_filter:
        df = df[df["Product ID"].astype(str) == str(product_id_filter)].reset_index(drop=True)

    print("[SYNC] Rows loaded:", len(df))
    print("[SYNC] Columns detected:", len(all_columns))
    print()

    # ── Delete phase — runs before create/update ─────────────────────────────
    deleted_indices, deleted_count = run_delete_phase(df, progress_callback)

    for idx in deleted_indices:
        df.at[idx, "Sync Status"] = "DELETED"

    # Remove deleted rows so they don't get re-processed in update phase
    df = df[~df.index.isin(deleted_indices)].reset_index(drop=True)

    print(f"[DELETE] Removed {len(deleted_indices)} deleted row(s) from update queue")

    # ── Creation phase — must run first, assigns IDs ─────────────────────────
    created_indices, creation_errors = run_creation(
        df, location_map, all_columns, snapshot_products=snapshot_products
    )

    for idx in created_indices:
        df.at[idx, "Sync Status"] = "CREATED"
        if progress_callback:
            row = df.iloc[idx]
            progress_callback(
                row_index=int(idx),
                variant_id=str(row.get("Variant ID", "")),
                status="CREATED",
                changes=[],
                error=None,
            )

    for idx in creation_errors:
        existing = str(df.at[idx, "Sync Status"])
        if not existing.startswith("ERROR:"):
            df.at[idx, "Sync Status"] = "ERROR"
        if progress_callback:
            progress_callback(
                row_index=int(idx),
                variant_id="",
                status="ERROR",
                changes=[],
                error=None,
            )

    print(f"[CREATE] Created: {len(created_indices)} rows | Errors: {len(creation_errors)} rows")

    # ── Refresh snapshot updatedAt for products touched by creation ───────────
    # Prevents false conflicts caused by our own creation while still detecting
    # real external changes made after our creation.
    created_product_ids = set()
    for idx in created_indices:
        pid = str(df.at[idx, "Product ID"] or "").strip()
        if pid and pid.lower() not in ("nan", "none", ""):
            created_product_ids.add(pid)

    if created_product_ids:
        refresh_query = """
        query($id: ID!) {
          product(id: $id) { updatedAt }
        }
        """
        for pid in created_product_ids:
            try:
                result = graphql_request(refresh_query, {"id": pid})
                fresh_ts = (result.get("data") or {}).get("product", {}).get("updatedAt")
                if fresh_ts and pid in snapshot_products:
                    snapshot_products[pid]["product"]["updatedAt"] = fresh_ts
                    print(f"[CREATE] Refreshed snapshot updatedAt for {pid}: {fresh_ts}")
            except Exception:
                pass

    # ── Thread-safe dedup sets ────────────────────────────────────────────────
    updated_products    = set()
    updated_metafields  = set()
    updated_collections = set()
    updated_images      = set()
    lock = threading.Lock()

    # ── Build update rows — skip creation/error rows ──────────────────────────
    skip_indices = set(created_indices) | set(creation_errors)
    update_rows = [
        (index, row)
        for index, row in df.iterrows()
        if index not in skip_indices
    ]

    # ── Parallel row processing ───────────────────────────────────────────────
    results   = {}   # index → status
    all_propagations = []

    workers = min(MAX_WORKERS, len(update_rows)) if update_rows else 1

    with ThreadPoolExecutor(max_workers=workers) as executor:

        futures = {
            executor.submit(
                process_row,
                index, row, all_columns,
                snapshot_products, location_map,
                updated_products, updated_metafields, updated_collections, updated_images,
                allowed_vendors,
                allowed_statuses,
                allowed_types,
                handle_owners,
                metafield_defs,
                field_schema,
                lock
            ): index
            for index, row in update_rows
        }

        for future in as_completed(futures):
            index = futures[future]
            try:
                idx, status, propagations = future.result()
                results[idx] = status
                all_propagations.extend(propagations)
                print(f"[SYNC] Row {idx} → {status}")

                # Stream result to web frontend (WebSocket) if callback provided
                if progress_callback:
                    row = df.iloc[idx]
                    progress_callback(
                        row_index=int(idx),
                        variant_id=str(row.get("Variant ID", "")),
                        status=status,
                        changes=[],   # full changes list not tracked here yet
                        error=None,
                    )

            except Exception as e:
                results[index] = "ERROR"
                print(f"[SYNC] Row {index} → ERROR: {e}")

                if progress_callback:
                    progress_callback(
                        row_index=int(index),
                        variant_id="",
                        status="ERROR",
                        changes=[],
                        error=str(e),
                    )

    # ── Apply results to DataFrame ────────────────────────────────────────────
    for idx, status in results.items():
        df.at[idx, "Sync Status"] = status

    # ── Apply propagations (all after parallel phase — safe) ─────────────────
    for product_id, fields, source_row in all_propagations:
        propagate_product_fields(df, product_id, fields, source_row)

    # ── Save CSV ──────────────────────────────────────────────────────────────
    df.to_csv(csv_path, index=False)

    total    = len(df)
    created  = len(df[df["Sync Status"] == "CREATED"])
    updated  = len(df[df["Sync Status"] == "UPDATED"])
    skipped  = len(df[df["Sync Status"] == "SKIPPED"])
    conflicts= len(df[df["Sync Status"] == "CONFLICT"])
    errors   = len(df[df["Sync Status"] == "ERROR"])

    print("\n====================================")
    print("[SYNC] Update Completed")
    print(f"[SYNC] Total rows:   {total}")
    print(f"[SYNC] Created:      {created}")
    print(f"[SYNC] Updated:      {updated}")
    print(f"[SYNC] Deleted:      {deleted_count}")
    print(f"[SYNC] Skipped:      {skipped}")
    if conflicts:
        print(f"[SYNC] Conflicts:    {conflicts}  ← Refresh to get latest data")
    print(f"[SYNC] Errors:       {errors}")
    print("====================================\n")

    return {
        "total":     total,
        "created":   created,
        "updated":   updated,
        "skipped":   skipped,
        "conflicts": conflicts,
        "errors":    errors,
        "deleted":   deleted_count,
    }