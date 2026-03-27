"""
creator.py — Handles all product/variant creation cases.

Called from updater.py BEFORE the update loop so new rows
get IDs assigned before any update logic runs on them.

CASES:
    Case 1 — Product ID empty, Variant ID empty, unique Title
             → productCreate (no variants) + productVariantsBulkCreate

    Case 2 — Product ID filled, Variant ID empty
             → productVariantsBulkCreate on existing product

    Case 4 — Product ID empty, Variant ID empty, same Title as another new row
             → productCreate once, productVariantsBulkCreate for all variants

    Invalid — Product ID empty, Variant ID filled → skip with ERROR

After creation (all cases):
    - IDs written back to DataFrame
    - Inventory activated + quantities set per location
    - Inventory item updated (SKU/cost/weight)
    - Metafields set
    - Collections assigned (Cases 1 and 4 only)
"""

import math
import pandas as pd

import re
import syncing.create_product as _cp_module
from syncing.create_product import create_product
from syncing.create_variant import create_variant
from products.client import graphql_request
from syncing.payload_cleaner import clean_string, clean_value
from syncing.inventory_update import activate_inventory_at_location
from syncing.inventory_item_update import update_inventory_item, enable_inventory_tracking
from syncing.metafield_update import update_metafields
from syncing.collection_update import update_collections
from syncing.image_update import upload_image


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_empty(val):
    """True for None, NaN, '', 'nan', 'none'."""
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    return str(val).strip().lower() in ("", "nan", "none")


def sanitize_row(row):
    """Convert all NaN values in a row dict to None before API calls."""
    return {
        k: (None if (isinstance(v, float) and math.isnan(v)) else v)
        for k, v in (row.to_dict() if hasattr(row, "to_dict") else row).items()
    }


def split_meta_cols(all_columns, snapshot_products=None, product_id=None, variant_id=None):
    """
    Split metafield columns into product-level vs variant-level.

    During creation there is no snapshot yet — default all to product-level.
    During update the snapshot is used to determine ownership correctly.

    SEO metafields are always excluded — handled by product_update via seo.title/description.
    """
    SEO_METAFIELDS = {"global.title_tag", "global.description_tag"}

    product_meta_cols = []
    variant_meta_cols = []

    # Try to use snapshot for accurate split
    variant_mf_keys = set()
    if snapshot_products and product_id and variant_id:
        product_snap = snapshot_products.get(product_id, {})
        for v_entry in product_snap.get("variants", []):
            if v_entry["variant"].get("id") == variant_id:
                variant_mf_keys = set(v_entry.get("metafields", {}).keys())
                break

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


# ── ID write-back ─────────────────────────────────────────────────────────────

def write_ids_back(df, index, product_id, variant_id, inventory_item_id):
    if product_id:
        df.at[index, "Product ID"] = product_id
    if variant_id:
        df.at[index, "Variant ID"] = variant_id
    if inventory_item_id:
        df.at[index, "Inventory Item ID"] = inventory_item_id
    print(f"[CREATE] IDs written back to row {index}")


def _upload_images(product_id, row):
    """Upload all images for a newly created product."""
    def _split_csv(val):
        parts = re.split(r',\s*(?=https?://)', str(val or ""))
        return [v.strip() for v in str(val or "").split(",")
                if v.strip() and v.strip().lower() not in ("nan", "none")]

    raw_urls = _split_csv(row.get("Image URLs", ""))
    raw_alts = _split_csv(row.get("Image Alt Text", ""))
    while len(raw_alts) < len(raw_urls):
        raw_alts.append("")

    for url, alt in zip(raw_urls, raw_alts):
        try:
            upload_image(product_id, url, alt)
            print(f"[CREATE] Image uploaded: {url}")
        except Exception as e:
            print(f"[CREATE] Image upload failed ({url}): {e}")


# ── Post-creation inventory setup ─────────────────────────────────────────────

def setup_inventory(row, inventory_item_id, location_map, all_columns):
    """
    Activate inventory item at every location and set initial quantities.
    New items are not stocked anywhere by default.
    """
    row = sanitize_row(row)
    print(f"[CREATE] Setting up inventory for {inventory_item_id}")

    for col in all_columns:
        if not col.startswith("Inventory Qty -"):
            continue

        location_name = col.replace("Inventory Qty - ", "")
        location_id   = location_map.get(location_name)

        if not location_id:
            print(f"[CREATE] Unknown location: {location_name} — skipping")
            continue

        qty_raw = row.get(col)
        try:
            qty = int(float(str(qty_raw))) if qty_raw is not None else 0
        except (ValueError, TypeError):
            qty = 0

        # Ensure tracking is on before activating/setting quantities
        enable_inventory_tracking(inventory_item_id)

        activated = activate_inventory_at_location(inventory_item_id, location_id)
        if not activated:
            print(f"[CREATE] Could not activate at {location_name} — skipping qty")
            continue

        mutation = """
        mutation inventorySetOnHandQuantities($input: InventorySetOnHandQuantitiesInput!) {
          inventorySetOnHandQuantities(input: $input) {
            inventoryAdjustmentGroup { reason }
            userErrors { field message }
          }
        }
        """
        r = graphql_request(mutation, {
            "input": {
                "reason": "correction",
                "setQuantities": [{
                    "inventoryItemId": inventory_item_id,
                    "locationId":      location_id,
                    "quantity":        qty
                }]
            }
        })

        if r.get("data"):
            errs = r["data"]["inventorySetOnHandQuantities"]["userErrors"]
            if errs:
                print(f"[CREATE] Inventory errors at {location_name}:", errs)
            else:
                print(f"[CREATE] Inventory set at {location_name}: {qty}")


# ── Group rows for Case 1 / 4 ─────────────────────────────────────────────────

def group_new_rows(df):
    """
    Find all rows with empty Product ID AND empty Variant ID.
    Group by Title — same Title = same product, multiple variants.

    Returns:
        groups:  {title: [index, ...]}
        invalid: [index, ...]  — Variant ID filled but Product ID empty
    """
    groups  = {}
    invalid = []

    for index, row in df.iterrows():
        pid_empty = is_empty(row.get("Product ID"))
        vid_empty = is_empty(row.get("Variant ID"))

        # Both filled = existing row, skip
        if not pid_empty and not vid_empty:
            continue

        # Invalid: Variant ID without Product ID
        if pid_empty and not vid_empty:
            print(f"[CREATE] Row {index} has Variant ID but no Product ID — invalid")
            invalid.append(index)
            continue

        # Case 2 handled separately
        if not pid_empty and vid_empty:
            continue

        # Both empty → Case 1 or 4
        title = str(row.get("Title") or "").strip()
        if not title:
            print(f"[CREATE] Row {index} has no Title — skipping")
            invalid.append(index)
            continue

        groups.setdefault(title, []).append(index)

    return groups, invalid


# ── Case 4: product with multiple variants ────────────────────────────────────

def create_product_with_variants(df, indices, location_map, all_columns):
    """
    Case 4 — Create one product with multiple variants.
    All rows share the same Title.

    Step 1: productCreate (product fields only)
    Step 2: productVariantsBulkCreate with ALL variants at once
    Step 3: delete Default Title placeholder
    Step 4: post-creation setup per variant
    """
    first_row = df.loc[indices[0]]
    title     = clean_string(first_row.get("Title"))

    print(f"[CREATE] Case 4 — creating '{title}' with {len(indices)} variant(s)")

    # ── Product input ─────────────────────────────────────────────────────────

    tags_raw = clean_string(first_row.get("Tags"))
    tags     = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

    seo_title = clean_string(first_row.get("SEO Title"))
    seo_desc  = clean_string(first_row.get("SEO Description"))
    seo = {}
    if seo_title: seo["title"]       = seo_title
    if seo_desc:  seo["description"] = seo_desc

    product_input = {
        "title":           title,
        "descriptionHtml": clean_string(first_row.get("Body (HTML)")),
        "vendor":          clean_string(first_row.get("Vendor")),
        "productType":     clean_string(first_row.get("Type")),
        "status":          clean_string(first_row.get("Status")) or "DRAFT",
        "tags":            tags,
    }
    if seo:
        product_input["seo"] = seo
    product_input = {k: v for k, v in product_input.items() if v is not None}

    # ── Collect options across all rows (Option1/2/3 Name+Value) ─────────────
    # Build unique option names in order, with all values seen across rows

    options_map = {}  # option_name → [values in order]
    for idx in indices:
        r = df.loc[idx]
        for i in range(1, 4):
            name  = clean_string(r.get(f"Option{i} Name"))
            value = clean_string(r.get(f"Option{i} Value"))
            if name and value:
                if name not in options_map:
                    options_map[name] = []
                if value not in options_map[name]:
                    options_map[name].append(value)

    # ── Step 1: Create product ────────────────────────────────────────────────

    mutation_create = """
    mutation productCreate($input: ProductInput!) {
      productCreate(input: $input) {
        product {
          id
          variants(first: 1) {
            edges { node { id inventoryItem { id } } }
          }
        }
        userErrors { field message }
      }
    }
    """
    r = graphql_request(mutation_create, {"input": product_input})
    if not r.get("data"):
        print("[CREATE] Case 4 — empty productCreate response")
        return False

    p_errors = r["data"]["productCreate"]["userErrors"]
    if p_errors:
        print("[CREATE] Case 4 — productCreate errors:", p_errors)
        return False

    product    = r["data"]["productCreate"]["product"]
    product_id = product["id"]
    print(f"[CREATE] Case 4 — product created: {product_id}")

    # ── Create options via productOptionsCreate ───────────────────────────────
    if options_map:
        _opts_input = [
            {"name": name, "values": [{"name": v} for v in vals]}
            for name, vals in options_map.items()
        ]
        _opt_create = graphql_request("""
        mutation productOptionsCreate($productId: ID!, $options: [OptionCreateInput!]!) {
          productOptionsCreate(productId: $productId, options: $options) {
            product { options { id name } }
            userErrors { field message }
          }
        }
        """, {"productId": product_id, "options": _opts_input})
        _opt_errs = (_opt_create.get("data") or {}).get("productOptionsCreate", {}).get("userErrors") or []
        if _opt_errs:
            print("[CREATE] Case 4 productOptionsCreate errors:", _opt_errs)
        else:
            print(f"[CREATE] Case 4 options created: {list(options_map.keys())}")

    # Fetch product options (id + name) for optionValues mapping
    _opt_r = graphql_request("""
    query($id: ID!) { product(id: $id) { options { id name } } }
    """, {"id": product_id})
    product_options = (_opt_r.get("data") or {}).get("product", {}).get("options") or []
    option_id_map = {o["name"]: o["id"] for o in product_options}

    def _build_option_values_case4(row_):
        """Build optionValues list for a variant from a df row."""
        result_ = []
        for i in range(1, 4):
            name_  = clean_string(row_.get(f"Option{i} Name"))
            value_ = clean_string(row_.get(f"Option{i} Value"))
            if name_ and value_ and name_ in option_id_map:
                result_.append({"optionId": option_id_map[name_], "name": value_})
        return result_

    # Get Default Title variant to UPDATE with first row's data
    default_edges      = product["variants"]["edges"]
    default_variant_id = default_edges[0]["node"]["id"] if default_edges else None
    default_inv_id     = default_edges[0]["node"]["inventoryItem"]["id"] if default_edges else None

    # ── Step 2a: Update Default Title variant with first row's data ──────────
    # Same strategy as Case 1 — update instead of delete

    first_row  = df.loc[indices[0]]
    inv_policy = clean_string(first_row.get("Variant Inventory Policy")) or "DENY"
    first_v = {
        "id":              default_variant_id,
        "price":           clean_string(first_row.get("Variant Price")),
        "compareAtPrice":  clean_string(first_row.get("Variant Compare At Price")),
        "sku":             clean_string(first_row.get("Variant SKU")),
        "barcode":         clean_string(first_row.get("Variant Barcode")),
        "taxCode":         clean_string(first_row.get("Variant Tax Code")),
        "inventoryPolicy": inv_policy,
    }
    first_v = {k: val for k, val in first_v.items() if val is not None}

    opt_vals_first = _build_option_values_case4(df.loc[indices[0]])
    if opt_vals_first:
        first_v["optionValues"] = opt_vals_first

    upd_r = graphql_request("""
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id inventoryItem { id } }
        userErrors { field message }
      }
    }
    """, {"productId": product_id, "variants": [first_v]})

    if not upd_r.get("data"):
        print("[CREATE] Case 4 — empty Default Title update response")
        return False

    upd_errors = upd_r["data"]["productVariantsBulkUpdate"]["userErrors"]
    if upd_errors:
        print("[CREATE] Case 4 — Default Title update errors:", upd_errors)
        return False

    upd_nodes = upd_r["data"]["productVariantsBulkUpdate"]["productVariants"]
    first_variant_id  = upd_nodes[0]["id"]                  if upd_nodes else default_variant_id
    first_inv_item_id = upd_nodes[0]["inventoryItem"]["id"] if upd_nodes else default_inv_id

    # ── Step 2b: Build and create remaining variants (indices[1:]) ────────────

    variants_input = []
    for idx in indices[1:]:
        row        = df.loc[idx]
        inv_policy = clean_string(row.get("Variant Inventory Policy")) or "DENY"
        v = {
            "price":           clean_string(row.get("Variant Price")),
            "compareAtPrice":  clean_string(row.get("Variant Compare At Price")),
            "sku":             clean_string(row.get("Variant SKU")),
            "barcode":         clean_string(row.get("Variant Barcode")),
            "taxCode":         clean_string(row.get("Variant Tax Code")),
            "inventoryPolicy": inv_policy,
        }
        v_clean = {k: val for k, val in v.items() if val is not None}
        opt_vals = _build_option_values_case4(row)
        if opt_vals:
            v_clean["optionValues"] = opt_vals
        variants_input.append(v_clean)

    # Write IDs back for first row immediately
    write_ids_back(df, indices[0], product_id, first_variant_id, first_inv_item_id)
    first_row_updated = df.loc[indices[0]]
    update_inventory_item(first_row_updated)
    setup_inventory(first_row_updated, first_inv_item_id, location_map, all_columns)

    # If only one variant (indices has just one item), we're done with variants
    if not variants_input:
        product_meta_cols, variant_meta_cols = split_meta_cols(all_columns)
        if product_meta_cols:
            update_metafields(first_row_updated, product_meta_cols,
                              snapshot_products=None, owner_id_override=product_id)
        if variant_meta_cols:
            update_metafields(first_row_updated, variant_meta_cols,
                              snapshot_products=None, owner_id_override=first_variant_id)
        update_collections(first_row_updated)
        _upload_images(product_id, first_row_updated)
        return True

    mutation_variants = """
    mutation productVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkCreate(productId: $productId, variants: $variants) {
        productVariants {
          id
          inventoryItem { id }
        }
        userErrors { field message }
      }
    }
    """

    vr = graphql_request(mutation_variants, {
        "productId": product_id,
        "variants":  variants_input
    })

    if not vr.get("data"):
        print("[CREATE] Case 4 — empty variant creation response")
        return False

    v_errors = vr["data"]["productVariantsBulkCreate"]["userErrors"]

    if v_errors:
        print("[CREATE] Case 4 — variant creation errors:", v_errors)
        return False

    var_nodes = vr["data"]["productVariantsBulkCreate"]["productVariants"]
    print(f"[CREATE] Case 4 — {len(var_nodes)} variant(s) created")

    # ── Step 3: Post-creation setup for remaining variants (indices[1:]) ────────

    product_meta_cols, _ = split_meta_cols(all_columns)

    for i, idx in enumerate(indices[1:]):
        if i >= len(var_nodes):
            print(f"[CREATE] Case 4 — no variant node for row {idx}")
            continue

        variant_id        = var_nodes[i]["id"]
        inventory_item_id = var_nodes[i]["inventoryItem"]["id"]

        write_ids_back(df, idx, product_id, variant_id, inventory_item_id)

        row = df.loc[idx]

        update_inventory_item(row)
        setup_inventory(row, inventory_item_id, location_map, all_columns)

        # Variant metafields
        _, variant_meta_cols = split_meta_cols(all_columns)
        if variant_meta_cols:
            update_metafields(row, variant_meta_cols, snapshot_products=None, owner_id_override=variant_id)

    # Product-level post-creation — once only (use already-updated first row)
    first_row_final = df.loc[indices[0]]

    if product_meta_cols:
        update_metafields(first_row_final, product_meta_cols, snapshot_products=None, owner_id_override=product_id)

    update_collections(first_row_final)
    _upload_images(product_id, first_row_final)

    return True


# ── Main creation runner ──────────────────────────────────────────────────────

def run_creation(df, location_map, all_columns, snapshot_products=None):
    """
    Detect and handle all creation cases in the DataFrame.
    Called from updater.py before the update loop.
    Modifies df in place.

    Returns:
        created_indices: set of row indices successfully created
        error_indices:   set of row indices that failed
    """

    created_indices = set()
    error_indices   = set()

    # ── Case 2: new variant on existing product ───────────────────────────────
    # Handle first, individually per row

    for index, row in df.iterrows():
        pid_empty = is_empty(row.get("Product ID"))
        vid_empty = is_empty(row.get("Variant ID"))

        # Case 2: Product ID filled, Variant ID empty
        if pid_empty or not vid_empty:
            continue

        product_id = row.get("Product ID")

        print(f"[CREATE] Case 2 — new variant on product {product_id} (row {index})")

        result = create_variant(sanitize_row(row))

        if not result:
            print(f"[CREATE] Case 2 failed for row {index}")
            df.at[index, "Sync Status"] = f"ERROR: {_get_last_error('create_variant')}"
            error_indices.add(index)
            continue

        write_ids_back(df, index, product_id,
                       result["variant_id"], result["inventory_item_id"])

        row = df.loc[index]
        update_inventory_item(row)
        setup_inventory(row, result["inventory_item_id"], location_map, all_columns)

        _upload_images(product_id, row)

        _, variant_meta_cols = split_meta_cols(all_columns)
        if variant_meta_cols:
            update_metafields(row, variant_meta_cols, snapshot_products=None, owner_id_override=result["variant_id"])

        created_indices.add(index)
        print(f"[CREATE] Case 2 complete for row {index}")

    # ── Case 1 / 4: group by Title ────────────────────────────────────────────

    groups, invalid = group_new_rows(df)

    for idx in invalid:
        df.at[idx, "Sync Status"] = "ERROR: Variant ID set but Product ID empty"
        error_indices.add(idx)

    for title, indices in groups.items():

        if len(indices) == 1:
            # ── Case 1: single new product + first variant ────────────────────
            index = indices[0]
            row   = df.loc[index]

            print(f"[CREATE] Case 1 — new product: '{title}' (row {index})")

            result = create_product(sanitize_row(row))

            if not result:
                err = _cp_module.last_error or "product creation failed"
                print(f"[CREATE] Case 1 failed for row {index}: {err}")
                df.at[index, "Sync Status"] = f"ERROR: {err}"
                error_indices.add(index)
                continue

            write_ids_back(df, index,
                           result["product_id"],
                           result["variant_id"],
                           result["inventory_item_id"])

            row = df.loc[index]

            update_inventory_item(row)
            setup_inventory(row, result["inventory_item_id"], location_map, all_columns)

            product_meta_cols, variant_meta_cols = split_meta_cols(all_columns)

            if product_meta_cols:
                update_metafields(row, product_meta_cols, snapshot_products=None, owner_id_override=result["product_id"])
            if variant_meta_cols:
                update_metafields(row, variant_meta_cols, snapshot_products=None, owner_id_override=result["variant_id"])

            update_collections(row)
            _upload_images(result["product_id"], row)

            created_indices.add(index)
            print(f"[CREATE] Case 1 complete for row {index}")

        else:
            # ── Case 4: multiple rows, same Title = one product multi-variant ──
            print(f"[CREATE] Case 4 — '{title}' with {len(indices)} variants")

            success = create_product_with_variants(
                df, indices, location_map, all_columns
            )

            if success:
                for idx in indices:
                    created_indices.add(idx)
            else:
                for idx in indices:
                    df.at[idx, "Sync Status"] = "ERROR: multi-variant creation failed"
                    error_indices.add(idx)

    print(f"\n[CREATE] Created: {len(created_indices)} rows | Errors: {len(error_indices)} rows")

    return created_indices, error_indices


def _get_last_error(module_name):
    """Read last_error from the relevant create module."""
    try:
        if module_name == "create_variant":
            import syncing.create_variant as m
            return m.last_error or "unknown error"
        if module_name == "create_product":
            return _cp_module.last_error or "unknown error"
    except Exception:
        pass
    return "unknown error"