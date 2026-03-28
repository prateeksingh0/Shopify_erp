"""
create_product.py

Case 1 — Create a brand new product with its first variant.
Called when Product ID = empty AND Variant ID = empty AND title is unique.

Two-step approach (required by Shopify API 2024+):
  Step 1: productCreate (no variants field — API rejects it)
  Step 2: productVariantsBulkCreate — add real variant
  Step 3: delete the auto-created "Default Title" placeholder

Returns:
    {product_id, variant_id, inventory_item_id}  or  None on failure
"""

from products.client import graphql_request
from syncing.payload_cleaner import clean_string

last_error = None


def create_product(row):
    global last_error
    last_error = None

    title = clean_string(row.get("Title"))
    if not title:
        print("[CREATE] Skipping — Title is required for new product")
        last_error = "Title is required"
        return None

    print(f"[CREATE] Creating new product: {title}")

    # ── Build product input ───────────────────────────────────────────────────

    tags_raw = clean_string(row.get("Tags"))
    tags     = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

    seo_title = clean_string(row.get("SEO Title"))
    seo_desc  = clean_string(row.get("SEO Description"))
    seo = {}
    if seo_title: seo["title"]       = seo_title
    if seo_desc:  seo["description"] = seo_desc

    product_input = {
        "title":           title,
        "handle":          clean_string(row.get("Handle")) or None,
        "descriptionHtml": clean_string(row.get("Body (HTML)")),
        "vendor":          clean_string(row.get("Vendor")),
        "productType":     clean_string(row.get("Type")),
        "status":          clean_string(row.get("Status")) or "DRAFT",
        "tags":            tags,
    }
    if seo:
        product_input["seo"] = seo

    # Remove None values — Shopify rejects null fields in ProductInput
    product_input = {k: v for k, v in product_input.items() if v is not None}

    # ── Step 1: Create product (no variants) ─────────────────────────────────

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

    result = graphql_request(mutation_create, {"input": product_input})

    if "errors" in result and result.get("data") is None:
        last_error = str(result["errors"])
        print("[CREATE] GraphQL errors:", last_error)
        return None

    if not result.get("data"):
        last_error = "Empty API response"
        print("[CREATE] Empty response:", result)
        return None

    user_errors = result["data"]["productCreate"]["userErrors"]
    if user_errors:
        last_error = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in user_errors)
        print("[CREATE] productCreate errors:", last_error)
        return None

    product_id = result["data"]["productCreate"]["product"]["id"]

    # Grab the auto-created Default Title variant to update
    default_edges = result["data"]["productCreate"]["product"]["variants"]["edges"]
    default_variant_id = default_edges[0]["node"]["id"] if default_edges else None
    default_inv_id     = default_edges[0]["node"]["inventoryItem"]["id"] if default_edges else None

    print(f"[CREATE] Product created: {product_id}")
    print(f"[CREATE] Default variant to update: {default_variant_id}")

    # ── Create options via productOptionsCreate (options not in ProductInput) ───
    options_list = []
    for i in range(1, 4):
        name  = clean_string(row.get(f"Option{i} Name"))
        value = clean_string(row.get(f"Option{i} Value"))
        if name and value:
            options_list.append({"name": name, "values": [{"name": value}]})

    if options_list:
        _opt_create = graphql_request("""
        mutation productOptionsCreate($productId: ID!, $options: [OptionCreateInput!]!) {
          productOptionsCreate(productId: $productId, options: $options) {
            product { options { id name } }
            userErrors { field message }
          }
        }
        """, {"productId": product_id, "options": options_list})
        _opt_errs = (_opt_create.get("data") or {}).get("productOptionsCreate", {}).get("userErrors") or []
        if _opt_errs:
            print("[CREATE] productOptionsCreate errors:", _opt_errs)
        else:
            print(f"[CREATE] Options created: {[o['name'] for o in options_list]}")

    # ── Fetch option IDs for optionValues mapping ─────────────────────────────
    _opt_r = graphql_request("""
    query($id: ID!) { product(id: $id) { options { id name } } }
    """, {"id": product_id})
    product_options = (_opt_r.get("data") or {}).get("product", {}).get("options") or []
    option_id_map = {o["name"]: o["id"] for o in product_options}

    # ── Step 2: UPDATE the auto-created Default Title variant ────────────────
    # Shopify always creates a "Default Title" variant on productCreate.
    # We UPDATE it with real data instead of deleting it — avoids the
    # "cannot delete last variant" restriction entirely.

    price      = clean_string(row.get("Variant Price"))
    compare    = clean_string(row.get("Variant Compare At Price"))
    sku        = clean_string(row.get("Variant SKU"))
    barcode    = clean_string(row.get("Variant Barcode"))
    tax_code   = clean_string(row.get("Variant Tax Code"))
    inv_policy = clean_string(row.get("Variant Inventory Policy")) or "DENY"

    variant_update = {"id": default_variant_id, "inventoryPolicy": inv_policy}
    if price:    variant_update["price"]          = price
    if compare:  variant_update["compareAtPrice"] = compare
    if sku:      variant_update["sku"]            = sku
    if barcode:  variant_update["barcode"]        = barcode
    if tax_code: variant_update["taxCode"]        = tax_code

    # Add optionValues if options were defined
    opt_vals = []
    for i in range(1, 4):
        name  = clean_string(row.get(f"Option{i} Name"))
        value = clean_string(row.get(f"Option{i} Value"))
        if name and value and name in option_id_map:
            opt_vals.append({"optionId": option_id_map[name], "name": value})
    if opt_vals:
        variant_update["optionValues"] = opt_vals

    mutation_update = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants {
          id
          inventoryItem { id }
        }
        userErrors { field message }
      }
    }
    """

    var_result = graphql_request(mutation_update, {
        "productId": product_id,
        "variants":  [variant_update]
    })

    if not var_result.get("data"):
        last_error = "Empty response on variant update"
        print("[CREATE] Empty variant update response:", var_result)
        return None

    var_errors = var_result["data"]["productVariantsBulkUpdate"]["userErrors"]
    if var_errors:
        last_error = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in var_errors)
        print("[CREATE] Variant update errors:", last_error)
        return None

    var_nodes = var_result["data"]["productVariantsBulkUpdate"]["productVariants"]
    variant_id        = var_nodes[0]["id"]        if var_nodes else default_variant_id
    inventory_item_id = var_nodes[0]["inventoryItem"]["id"] if var_nodes else default_inv_id

    print(f"[CREATE] Variant updated:   {variant_id}")
    print(f"[CREATE] Inventory item ID: {inventory_item_id}")

    return {
        "product_id":        product_id,
        "variant_id":        variant_id,
        "inventory_item_id": inventory_item_id,
    }