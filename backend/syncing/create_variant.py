"""
create_variant.py

Case 2 — Add a new variant to an existing product.
Called when Product ID = filled AND Variant ID = empty.

The product already exists — only variant is created.
Product-level fields (Title, Tags, SEO etc) are ignored here.

Handles options dynamically:
  - Reads Option1 Name/Value, Option2 Name/Value, Option3 Name/Value from row
  - If product has no options yet → creates option via productOptionsCreate first
  - If product already has options → uses existing option names
  - Placeholder (Default Title) → updated in-place with option values

Returns:
    {variant_id, inventory_item_id}  or  None on failure
"""

from products.client import graphql_request
from syncing.payload_cleaner import clean_string

last_error = None


def create_variant(row):
    global last_error
    last_error = None

    product_id = clean_string(row.get("Product ID"))
    if not product_id:
        print("[CREATE VARIANT] No Product ID — cannot create variant")
        last_error = "No Product ID"
        return None

    print(f"[CREATE VARIANT] Adding variant to product: {product_id}")

    # ── Build base variant input ──────────────────────────────────────────────

    price      = clean_string(row.get("Variant Price"))
    compare    = clean_string(row.get("Variant Compare At Price"))
    sku        = clean_string(row.get("Variant SKU"))
    barcode    = clean_string(row.get("Variant Barcode"))
    tax_code   = clean_string(row.get("Variant Tax Code"))
    inv_policy = clean_string(row.get("Variant Inventory Policy")) or "DENY"

    variant_input = {
        "price":           price,
        "compareAtPrice":  compare,
        "sku":             sku,
        "barcode":         barcode,
        "taxCode":         tax_code,
        "inventoryPolicy": inv_policy,
    }
    variant_input = {k: v for k, v in variant_input.items() if v is not None}

    # ── Read option values from row ───────────────────────────────────────────
    # Supports up to 3 options (Shopify max)
    # Columns: Option1 Name, Option1 Value, Option2 Name, Option2 Value, ...

    row_options = []  # list of {name, value} from the sheet row
    for i in range(1, 4):
        name  = clean_string(row.get(f"Option{i} Name"))
        value = clean_string(row.get(f"Option{i} Value"))
        if name and value:
            row_options.append({"name": name, "value": value})

    # ── Fetch existing product options and variants ───────────────────────────

    existing, product_options = _get_variants_and_options(product_id)

    # ── Decide: update placeholder or create new variant ─────────────────────

    if len(existing) == 1 and _is_placeholder(existing[0]):
        print("[CREATE VARIANT] Only Default Title exists — updating it with real data")

        default_id  = existing[0]["id"]
        default_inv = existing[0]["inventoryItem"]["id"]

        update_input = {"id": default_id}
        update_input.update(variant_input)

        # If options provided, ensure product has options then set optionValues
        if row_options:
            # Check if product only has the default "Title" option
            has_only_title_option = (
                not product_options or
                (len(product_options) == 1 and product_options[0].get("name") == "Title")
            )

            if has_only_title_option and product_options:
                # RENAME "Title" → user's option name via productOptionUpdate
                # This avoids adding a second option alongside "Title"
                title_option_id = product_options[0]["id"]
                print(f"[CREATE VARIANT] Renaming 'Title' option → '{row_options[0]['name']}'")
                ok = _rename_product_option(product_id, title_option_id, row_options[0]["name"])
                if not ok:
                    return None
                # Re-fetch options after rename
                _, product_options = _get_variants_and_options(product_id)

            elif not product_options:
                # No options at all — create from scratch
                print(f"[CREATE VARIANT] Creating product option: {row_options[0]['name']}")
                ok = _create_product_option(product_id, row_options[0]["name"], [row_options[0]["value"]])
                if not ok:
                    return None
                _, product_options = _get_variants_and_options(product_id)

            # Build optionValues list matching current product options order
            option_values = _build_option_values(row_options, product_options)
            if option_values:
                update_input["optionValues"] = option_values

        upd_result = graphql_request("""
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants { id inventoryItem { id } }
            userErrors { field message }
          }
        }
        """, {"productId": product_id, "variants": [update_input]})

        if not upd_result.get("data"):
            last_error = "Empty response on Default Title update"
            print("[CREATE VARIANT]", last_error)
            return None

        upd_errors = upd_result["data"]["productVariantsBulkUpdate"]["userErrors"]
        if upd_errors:
            last_error = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in upd_errors)
            print("[CREATE VARIANT] Update errors:", last_error)
            return None

        nodes = upd_result["data"]["productVariantsBulkUpdate"]["productVariants"]
        variant_id        = nodes[0]["id"]                  if nodes else default_id
        inventory_item_id = nodes[0]["inventoryItem"]["id"] if nodes else default_inv

        print(f"[CREATE VARIANT] Variant updated:   {variant_id}")
        print(f"[CREATE VARIANT] Inventory item ID: {inventory_item_id}")
        return {"variant_id": variant_id, "inventory_item_id": inventory_item_id}

    # ── Product already has real variants — CREATE a new one ─────────────────

    # If options provided, ensure the option name exists on the product
    if row_options:
        existing_option_names = [o.get("name") for o in (product_options or [])]
        for opt in row_options:
            if opt["name"] not in existing_option_names:
                print(f"[CREATE VARIANT] Adding new option '{opt['name']}' to product")
                ok = _create_product_option(product_id, opt["name"], [opt["value"]])
                if not ok:
                    return None
        # Re-fetch options after any additions
        _, product_options = _get_variants_and_options(product_id)

    # ── Build all variant combinations ────────────────────────────────────────
    # Shopify requires ALL product options to have a value on every variant.
    # If user only specified Size/L but product also has Weight (H, MH),
    # create: [Size L / Weight H] AND [Size L / Weight MH]
    # i.e. one variant per value of each missing option — same as Shopify admin.

    row_option_names = {opt["name"] for opt in row_options}

    # Collect missing options and their existing values
    missing_options = []
    for prod_opt in (product_options or []):
        opt_name = prod_opt.get("name")
        if opt_name and opt_name not in row_option_names:
            existing_values = prod_opt.get("values") or []
            if existing_values:
                missing_options.append((opt_name, existing_values))

    # Generate all combinations via cartesian product
    def _cartesian(base_options, missing):
        if not missing:
            return [base_options]
        opt_name, values = missing[0]
        rest = missing[1:]
        result = []
        for val in values:
            combo = base_options + [{"name": opt_name, "value": val}]
            result.extend(_cartesian(combo, rest))
        return result

    all_combinations = _cartesian(list(row_options), missing_options)
    print(f"[CREATE VARIANT] Creating {len(all_combinations)} variant combination(s)")

    # Build one variant input per combination
    variants_to_create = []
    for combo in all_combinations:
        v_input = dict(variant_input)
        opt_vals = _build_option_values(combo, product_options)
        if opt_vals:
            v_input["optionValues"] = opt_vals
        variants_to_create.append(v_input)

    result = graphql_request("""
    mutation productVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkCreate(productId: $productId, variants: $variants) {
        productVariants { id inventoryItem { id } }
        userErrors { field message }
      }
    }
    """, {"productId": product_id, "variants": variants_to_create})

    if not result.get("data"):
        last_error = "Empty API response"
        print("[CREATE VARIANT] Empty response:", result)
        return None

    errors = result["data"]["productVariantsBulkCreate"]["userErrors"]
    if errors:
        last_error = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in errors)
        print("[CREATE VARIANT] Errors:", last_error)
        return None

    var_nodes = result["data"]["productVariantsBulkCreate"]["productVariants"]
    if not var_nodes:
        last_error = "No variant returned"
        print("[CREATE VARIANT]", last_error)
        return None

    # Return first variant's IDs — additional combinations visible after FETCH
    variant_id        = var_nodes[0]["id"]
    inventory_item_id = var_nodes[0]["inventoryItem"]["id"]

    print(f"[CREATE VARIANT] {len(var_nodes)} variant(s) created")
    print(f"[CREATE VARIANT] First variant ID: {variant_id}")
    return {"variant_id": variant_id, "inventory_item_id": inventory_item_id}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_variants_and_options(product_id):
    """Fetch existing variants and product options in one call."""
    query = """
    query($id: ID!) {
      product(id: $id) {
        options { id name values }
        variants(first: 50) {
          edges { node { id title price sku inventoryItem { id } selectedOptions { name value } } }
        }
      }
    }
    """
    r = graphql_request(query, {"id": product_id})
    if not r.get("data") or not r["data"].get("product"):
        return [], []
    p = r["data"]["product"]
    variants = [e["node"] for e in p["variants"]["edges"]]
    options  = p.get("options") or []
    return variants, options


def _is_placeholder(variant):
    """
    Detect a Shopify auto-created placeholder variant.
    Reliable signals:
      - title is "Default Title"
      - price is 0
      - no SKU
      - selectedOptions only has {"name": "Title", "value": "Default Title"}
    All conditions must be true.
    """
    title = variant.get("title")
    price = variant.get("price")
    sku   = variant.get("sku")
    title_is_default = (not title) or str(title).strip() == "Default Title"
    price_is_zero    = (not price) or str(price).strip() in ("0", "0.0", "0.00")
    sku_is_empty     = not sku

    selected_opts = variant.get("selectedOptions") or []
    options_are_default = (
        not selected_opts or
        (
            len(selected_opts) == 1 and
            selected_opts[0].get("name") == "Title" and
            selected_opts[0].get("value") == "Default Title"
        )
    )

    return title_is_default and price_is_zero and sku_is_empty and options_are_default


def _rename_product_option(product_id, option_id, new_name):
    """
    Rename an existing product option via productOptionUpdate.
    Used to rename Shopify's auto-created 'Title' option to the user's option name.
    This avoids creating a second option alongside 'Title'.
    """
    result = graphql_request("""
    mutation productOptionUpdate($productId: ID!, $option: OptionUpdateInput!) {
      productOptionUpdate(productId: $productId, option: $option) {
        product { options { id name values } }
        userErrors { field message }
      }
    }
    """, {
        "productId": product_id,
        "option": {"id": option_id, "name": new_name}
    })

    if not result.get("data"):
        print("[CREATE VARIANT] Empty response on productOptionUpdate")
        return False

    errors = result["data"]["productOptionUpdate"]["userErrors"]
    if errors:
        err = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in errors)
        print(f"[CREATE VARIANT] productOptionUpdate error: {err}")
        return False

    print(f"[CREATE VARIANT] Option renamed → '{new_name}'")
    return True


def _create_product_option(product_id, option_name, option_values):
    """Add a new option to an existing product."""
    result = graphql_request("""
    mutation productOptionsCreate($productId: ID!, $options: [OptionCreateInput!]!) {
      productOptionsCreate(productId: $productId, options: $options) {
        product { options { id name values } }
        userErrors { field message }
      }
    }
    """, {
        "productId": product_id,
        "options": [{"name": option_name, "values": [{"name": v} for v in option_values]}]
    })

    if not result.get("data"):
        print("[CREATE VARIANT] Empty response on productOptionsCreate")
        return False

    errors = result["data"]["productOptionsCreate"]["userErrors"]
    if errors:
        err = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in errors)
        print(f"[CREATE VARIANT] productOptionsCreate error: {err}")
        return False

    print(f"[CREATE VARIANT] Option '{option_name}' created on product")
    return True


def _build_option_values(row_options, product_options):
    """
    Build optionValues list for variant input.
    Maps row option names to product option IDs.
    Format: [{"optionId": "...", "name": "value"}, ...]
    """
    if not product_options:
        return []

    option_id_map = {o["name"]: o["id"] for o in product_options}
    result = []
    for opt in row_options:
        opt_id = option_id_map.get(opt["name"])
        if opt_id:
            result.append({"optionId": opt_id, "name": opt["value"]})
    return result