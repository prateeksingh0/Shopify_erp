import json
from datetime import datetime, timezone


def build_metafield_owner_map(snapshot):
    """
    Build a dynamic ownership map:
      {"namespace.key": "product" | "variant" | "both"}

    Rules:
      - seen only on product metafields -> product
      - seen only on variant metafields -> variant
      - seen in both scopes             -> both
    """
    owners = {}

    for product_data in snapshot.values():
        for ns_key in (product_data.get("product_metafields") or {}).keys():
            existing = owners.get(ns_key)
            if existing == "variant":
                owners[ns_key] = "both"
            elif existing is None:
                owners[ns_key] = "product"

        for variant_entry in (product_data.get("variants") or []):
            for ns_key in (variant_entry.get("metafields") or {}).keys():
                existing = owners.get(ns_key)
                if existing == "product":
                    owners[ns_key] = "both"
                elif existing is None:
                    owners[ns_key] = "variant"

    return owners


def parse_jsonl(file_path):

    print("[PARSER] Reading bulk JSONL file:", file_path)

    rows = []
    snapshot = {}

    products = {}
    variants = []

    product_metafields = {}
    variant_metafields = {}

    product_images = {}

    fetch_time = datetime.now(timezone.utc).isoformat()

    with open(file_path, "r", encoding="utf-8") as f:

        for line in f:

            obj = json.loads(line)

            obj_id = obj.get("id")

            if not obj_id:
                continue

            # -------------------------
            # PRODUCT
            # -------------------------

            if obj_id.startswith("gid://shopify/Product/"):

                products[obj_id] = obj

                snapshot[obj_id] = {
                    "product": obj,
                    "product_metafields": {},
                    "variants": [],
                    "images": []
                }

            # -------------------------
            # VARIANT
            # -------------------------

            elif obj_id.startswith("gid://shopify/ProductVariant/"):

                variants.append(obj)

            # -------------------------
            # METAFIELD
            # -------------------------

            elif obj_id.startswith("gid://shopify/Metafield/"):

                parent_id = obj.get("__parentId")

                ns_key = f"{obj.get('namespace')}.{obj.get('key')}"

                # Store BOTH value and type
                # This is the critical fix — type is dynamic per store,
                # never hardcoded. updater.py reads this to send
                # the correct type to Shopify for every metafield.
                metafield_entry = {
                    "value": obj.get("value"),
                    "type":  obj.get("type")
                }

                if parent_id.startswith("gid://shopify/Product/"):
                    product_metafields.setdefault(parent_id, {})[ns_key] = metafield_entry

                elif parent_id.startswith("gid://shopify/ProductVariant/"):
                    variant_metafields.setdefault(parent_id, {})[ns_key] = metafield_entry

            # -------------------------
            # IMAGE
            # -------------------------

            elif obj_id.startswith("gid://shopify/MediaImage/"):

                parent_id = obj.get("__parentId")

                url = (obj.get("image") or {}).get("url")
                alt = (obj.get("image") or {}).get("altText")

                product_images.setdefault(parent_id, []).append({
                    "id":  obj_id,
                    "url": url,
                    "alt": alt
                })

    print("[PARSER] Products detected:", len(products))
    print("[PARSER] Variants detected:", len(variants))

    # -------------------------
    # Link variants to products
    # -------------------------

    for variant in variants:

        parent_id = variant.get("__parentId")

        if parent_id in snapshot:

            snapshot[parent_id]["variants"].append({
                "variant": variant,
                "metafields": variant_metafields.get(variant.get("id"), {})
            })

    # -------------------------
    # Attach metafields + images to snapshot
    # -------------------------

    for product_id in snapshot:

        snapshot[product_id]["product_metafields"] = product_metafields.get(product_id, {})
        snapshot[product_id]["images"] = [
            img for img in product_images.get(product_id, [])
            if img.get("url")
        ]

    # -------------------------
    # Flatten to CSV rows
    # -------------------------

    for product_id, data in snapshot.items():

        product = data["product"]

        for variant_data in data["variants"]:

            variant = variant_data["variant"]

            inventory = variant.get("inventoryItem") or {}
            measurement = inventory.get("measurement") or {}
            weight = measurement.get("weight") or {}

            unit_cost = inventory.get("unitCost") or {}

            category = product.get("productCategory") or {}
            taxonomy = category.get("productTaxonomyNode") or {}

            images = data["images"]

            row = {

                "Product ID": product_id,

                "Image URLs": ", ".join([i["url"] for i in images if i.get("url")]),
                "Image Alt Text": ", ".join([(i.get("alt") or "") for i in images if i.get("url")]),

                "Handle": product.get("handle"),
                "Title": product.get("title"),
                "Body (HTML)": product.get("descriptionHtml"),

                "Vendor": product.get("vendor"),
                "Type": product.get("productType"),

                "Product Category ID": taxonomy.get("id"),
                "Product Category Name": taxonomy.get("name"),
                "Product Category Full Path": taxonomy.get("fullName"),

                "Tags": ", ".join(product.get("tags", [])),

                "Status": product.get("status"),

                "Created At": product.get("createdAt"),
                "Updated At": product.get("updatedAt"),

                "SEO Title": product.get("seo", {}).get("title"),
                "SEO Description": product.get("seo", {}).get("description"),

                "Variant ID": variant.get("id"),

                # Options — dynamic, up to 3 option levels
                # selectedOptions is a list of {name, value} dicts
                "Option1 Name":  (variant.get("selectedOptions") or [{}])[0].get("name"),
                "Option1 Value": (variant.get("selectedOptions") or [{}])[0].get("value"),
                "Option2 Name":  (variant.get("selectedOptions") or [{}, {}])[1].get("name") if len(variant.get("selectedOptions") or []) > 1 else None,
                "Option2 Value": (variant.get("selectedOptions") or [{}, {}])[1].get("value") if len(variant.get("selectedOptions") or []) > 1 else None,
                "Option3 Name":  (variant.get("selectedOptions") or [{}, {}, {}])[2].get("name") if len(variant.get("selectedOptions") or []) > 2 else None,
                "Option3 Value": (variant.get("selectedOptions") or [{}, {}, {}])[2].get("value") if len(variant.get("selectedOptions") or []) > 2 else None,

                "Variant SKU": variant.get("sku"),
                "Variant Price": variant.get("price"),
                "Variant Compare At Price": variant.get("compareAtPrice"),
                "Variant Barcode": variant.get("barcode"),
                "Variant Tax Code": variant.get("taxCode"),
                "Variant Inventory Policy": variant.get("inventoryPolicy"),

                "Inventory Item ID": inventory.get("id"),

                "Cost per item": unit_cost.get("amount"),

                "Variant Grams": weight.get("value"),
                "Variant Weight Unit": weight.get("unit"),

                "Last Synced": fetch_time,
                "Sync Status": ""
            }

            # -------------------------
            # Attach metafields to CSV row
            # CSV only needs the VALUE — type stays in snapshot only
            # -------------------------

            for ns_key, entry in data["product_metafields"].items():
                row[ns_key] = entry["value"]

            for ns_key, entry in variant_data["metafields"].items():
                row[ns_key] = entry["value"]

            rows.append(row)

    print("[PARSER] Rows generated:", len(rows))

    inventory_ids = list({
        r["Inventory Item ID"]
        for r in rows
        if r["Inventory Item ID"]
    })

    print("[PARSER] Inventory items:", len(inventory_ids))

    return rows, snapshot, inventory_ids