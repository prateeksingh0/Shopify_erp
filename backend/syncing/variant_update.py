from products.client import graphql_request
from syncing.payload_cleaner import clean_value, clean_string


def update_variant(row):

    product_id = row.get("Product ID")
    variant_id = row.get("Variant ID")

    print(f"[VARIANT] Updating variant {variant_id}")

    # Build variant input — clean every value to remove NaN
    variant_input = {
        "id": variant_id,
    }

    price = clean_value(row.get("Variant Price"))
    if price is not None:
        variant_input["price"] = str(price)

    compare_at_price = clean_value(row.get("Variant Compare At Price"))
    if compare_at_price is not None:
        variant_input["compareAtPrice"] = str(compare_at_price)

    barcode = clean_value(row.get("Variant Barcode"))
    if barcode is not None:
        variant_input["barcode"] = str(barcode)

    inventory_policy = clean_value(row.get("Variant Inventory Policy"))
    if inventory_policy is not None:
        variant_input["inventoryPolicy"] = str(inventory_policy)

    # ── Option values (Option1/2/3 Name+Value) ────────────────────────────────
    # If any option columns are filled, fetch product option IDs and map values.

    row_options = []
    for i in range(1, 4):
        name  = str(row.get(f"Option{i} Name") or "").strip()
        value = str(row.get(f"Option{i} Value") or "").strip()
        if name and value and name.lower() not in ("nan", "none") and value.lower() not in ("nan", "none"):
            row_options.append({"name": name, "value": value})

    if row_options:
        opt_r = graphql_request("""
        query($id: ID!) { product(id: $id) { options { id name } } }
        """, {"id": product_id})
        product_options = (opt_r.get("data") or {}).get("product", {}).get("options") or []
        option_id_map = {o["name"]: o["id"] for o in product_options}

        opt_vals = []
        for opt in row_options:
            opt_id = option_id_map.get(opt["name"])
            if opt_id:
                opt_vals.append({"optionId": opt_id, "name": opt["value"]})

        if opt_vals:
            variant_input["optionValues"] = opt_vals
            print(f"[VARIANT] Option values: {opt_vals}")

    payload = {
        "productId": product_id,
        "variants": [variant_input]
    }

    print("[VARIANT] Payload:", payload)

    mutation = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants {
          id
          price
          compareAtPrice
        }
        userErrors {
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, payload)

    errors = result["data"]["productVariantsBulkUpdate"]["userErrors"]

    if errors:
        msg = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in errors)
        print("[VARIANT] Errors:", errors)
        raise Exception(f"[VARIANT] {msg}")
    else:
        print("[VARIANT] SUCCESS")