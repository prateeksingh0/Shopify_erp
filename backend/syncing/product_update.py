from products.client import graphql_request
from syncing.payload_cleaner import clean_dict, clean_string


def update_product(row):

    product_id = row.get("Product ID")

    print("[PRODUCT] Updating product", product_id)

    # Tags — Shopify expects a list, not a comma-separated string
    tags_raw = clean_string(row.get("Tags"))
    tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else None

    # SEO — only include if at least one field has a value
    seo_title = clean_string(row.get("SEO Title"))
    seo_desc  = clean_string(row.get("SEO Description"))
    seo = {}
    if seo_title: seo["title"]       = seo_title
    if seo_desc:  seo["description"] = seo_desc

    product_input = {
        "id":              product_id,
        "title":           row.get("Title"),
      "handle":          row.get("Handle"),
        "descriptionHtml": row.get("Body (HTML)"),
        "vendor":          row.get("Vendor"),
        "productType":     row.get("Type"),
        "tags":            tags,
        "status":          row.get("Status"),
    }
    if seo:
        product_input["seo"] = seo

    payload = clean_dict({"input": product_input})

    print("[PRODUCT] Payload:", payload)

    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id }
        userErrors { field message }
      }
    }
    """

    result = graphql_request(mutation, payload)

    errors = result["data"]["productUpdate"]["userErrors"]

    if errors:
        msg = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in errors)
        print("[PRODUCT] Errors:", errors)
        raise Exception(f"[PRODUCT] {msg}")
    else:
        print("[PRODUCT] SUCCESS")