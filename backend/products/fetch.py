import os
import json
from concurrent.futures import ThreadPoolExecutor

from products.bulk import start_bulk_operation, wait_for_bulk, download_jsonl
from products.locations import fetch_locations
from products.inventory import fetch_inventory_levels
from products.collections import fetch_collections
from products.metafield_defs import fetch_and_store_metafield_defs
from products.field_schema import fetch_and_store_field_schema
from products.parser import parse_jsonl, build_metafield_owner_map
from products.csv_writer import save_csv
from products.snapshot_writer import save_snapshot
from products.models import save_products_to_db
import products.store_paths as store_paths
import products.config as config

# -------------------------
# QUERY LIMIT CONSTANTS
# Shopify API maximums — adjust if your store has more images/metafields per product
# -------------------------
PRODUCTS_LIMIT   = 250   # max products per bulk page (Shopify limit)
VARIANTS_LIMIT   = 250   # max variants per product
MEDIA_LIMIT      = 50    # max images per product
METAFIELDS_LIMIT = 50    # max metafields per product/variant


# -------------------------
# PRODUCT BULK QUERY
# -------------------------

PRODUCT_BULK_QUERY = """{{
products (first:{products_limit}){{
edges {{
node {{

id
handle
title
descriptionHtml
vendor
productType

productCategory {{
productTaxonomyNode {{
id
name
fullName
}}
}}

tags
status
createdAt
updatedAt

seo {{
title
description
}}

media(first: {media_limit}) {{
edges {{
node {{
... on MediaImage {{
id
image {{
url
altText
}}
}}
}}
}}
}}

metafields(first: {metafields_limit}) {{
edges {{
node {{
id
namespace
key
value
type
}}
}}
}}

variants (first:{variants_limit}){{
edges {{
node {{

id
sku
price
compareAtPrice
barcode
taxCode
selectedOptions {{
name
value
}}

metafields(first: {metafields_limit}) {{
edges {{
node {{
id
namespace
key
value
type
}}
}}
}}

inventoryPolicy

inventoryItem {{

id
tracked
requiresShipping

unitCost {{
amount
}}

measurement {{
weight {{
value
unit
}}
}}

}}

}}
}}
}}

}}
}}
}}
}}""".format(
    products_limit=PRODUCTS_LIMIT,
    variants_limit=VARIANTS_LIMIT,
    media_limit=MEDIA_LIMIT,
    metafields_limit=METAFIELDS_LIMIT,
)


# -------------------------
# MAIN EXECUTION
# -------------------------

def main():

    print("\n[FETCH] Starting Shopify product bulk export...\n")

    # -------------------------
    # BULK EXPORT
    # -------------------------

    print("[FETCH] Starting bulk operation...")

    start_bulk_operation(PRODUCT_BULK_QUERY)

    bulk_url = wait_for_bulk()

    print("[FETCH] Bulk export completed.")

    file_path = download_jsonl(bulk_url, "products_bulk.jsonl")

    print("[FETCH] Bulk file downloaded:", file_path)

    # -------------------------
    # PARSE BULK FILE
    # -------------------------

    rows, snapshot, inventory_ids = parse_jsonl(file_path)
    metafield_owner_map = build_metafield_owner_map(snapshot)

    print("[PARSER] Rows parsed:", len(rows))
    print("[PARSER] Inventory items detected:", len(inventory_ids))

    # -------------------------
    # Fetch metafield definitions early and inject blank columns
    # so new metafields appear even when no product has a value yet.
    # Fully dynamic: columns come from Shopify definitions, never hardcoded.
    # -------------------------

    metafield_defs = fetch_and_store_metafield_defs(store_paths.STORE_DIR)
    fetch_and_store_field_schema(store_paths.STORE_DIR)

    owner_map_path = os.path.join(store_paths.STORE_DIR, "metafield_owners.json")
    with open(owner_map_path, "w", encoding="utf-8") as f:
        json.dump(metafield_owner_map, f, indent=2, ensure_ascii=False)

    all_metafield_columns = sorted(
        set((metafield_defs.get("product") or {}).keys())
        | set((metafield_defs.get("variant") or {}).keys())
    )

    for row in rows:
        for column in all_metafield_columns:
            row.setdefault(column, "")

    # -------------------------
    # FETCH LOCATIONS (must finish first — inventory needs the location map)
    # -------------------------

    print("[LOCATIONS] Fetching locations...")

    id_to_name, name_to_id = fetch_locations()

    print("[LOCATIONS] Locations detected:", len(id_to_name))

    # -------------------------
    # FETCH INVENTORY + COLLECTIONS in parallel
    # Both are independent after locations is done — run together to save time
    # -------------------------

    print("[INVENTORY] Fetching inventory levels + collections in parallel...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_inventory    = executor.submit(fetch_inventory_levels, inventory_ids, id_to_name)
        future_collections  = executor.submit(fetch_collections)
        inventory_levels    = future_inventory.result()
        product_collections = future_collections.result()

    print("[INVENTORY] Inventory records received:", len(inventory_levels))
    print("[COLLECTIONS] Collections received:", len(product_collections))

    # Attach inventory to rows
    for row in rows:

        inv_id = row.get("Inventory Item ID")

        # Create dynamic inventory columns with default 0
        for loc_name in id_to_name.values():
            row[f"Inventory Qty - {loc_name}"] = 0

        if inv_id in inventory_levels:
            for loc_name, qty in inventory_levels[inv_id].items():
                row[f"Inventory Qty - {loc_name}"] = qty

    print("[INVENTORY] Inventory attached to rows.")

    # -------------------------
    # SAVE INVENTORY INTO SNAPSHOT
    # -------------------------
    # Critical fix: without this, delta detection in updater.py
    # has nothing to compare against and always thinks
    # inventory changed — causing unnecessary mutations every run.

    print("[SNAPSHOT] Attaching inventory levels to snapshot...")

    for product_id, product_data in snapshot.items():

        for variant_entry in product_data["variants"]:

            variant = variant_entry["variant"]
            inventory_item = variant.get("inventoryItem") or {}
            inv_id = inventory_item.get("id")

            if inv_id and inv_id in inventory_levels:
                variant_entry["inventory"] = inventory_levels[inv_id]
            else:
                variant_entry["inventory"] = {}

    print("[SNAPSHOT] Inventory levels saved into snapshot.")

    # -------------------------
    # ATTACH COLLECTIONS
    # (already fetched in parallel with inventory above)
    # -------------------------

    print("[COLLECTIONS] Attaching collections...")
    for row in rows:

        product_id = row["Product ID"]

        if product_id in product_collections:

            names = product_collections[product_id]["names"]
            handles = product_collections[product_id]["handles"]

            row["Collection Names"] = ", ".join(names)
            row["Collection Handles"] = ", ".join(handles)

        else:

            row["Collection Names"] = ""
            row["Collection Handles"] = ""

    # Save collection handles into snapshot
    # So updater.py can detect if collections actually changed
    for product_id, product_data in snapshot.items():

        if product_id in product_collections:
            product_data["collection_handles"] = ", ".join(
                product_collections[product_id]["handles"]
            )
        else:
            product_data["collection_handles"] = ""

    print("[COLLECTIONS] Collections attached.")

    # -------------------------
    # SAVE OUTPUTS
    # -------------------------

    print("[SNAPSHOT] Saving snapshot...")

    save_snapshot(snapshot)

    print("[CSV] Writing CSV file...")

    save_csv(rows)

    print("[DB] Updating metadata...")

    save_products_to_db(rows, config.STORE_NAME)

    print("\n[FETCH] Sync completed successfully.\n")
