import products.config as config
from django.db import connection


def insert_metadata(rows):
    store_name = config.STORE_NAME

    if not store_name:
        print("[DB] No store name configured — skipping insert")
        return

    try:
        with connection.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO products (store_name, product_gid, handle, updated_at_shopify)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (store_name, product_gid)
                    DO UPDATE SET
                        handle             = EXCLUDED.handle,
                        updated_at_shopify = EXCLUDED.updated_at_shopify
                    """,
                    (
                        store_name,
                        row["Product ID"],
                        row["Handle"],
                        row["Updated At"]
                    )
                )

                cur.execute(
                    """
                    INSERT INTO variants (store_name, variant_gid, product_gid, inventory_item_gid, updated_at_shopify)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (store_name, variant_gid)
                    DO UPDATE SET
                        product_gid        = EXCLUDED.product_gid,
                        inventory_item_gid = EXCLUDED.inventory_item_gid,
                        updated_at_shopify = EXCLUDED.updated_at_shopify
                    """,
                    (
                        store_name,
                        row["Variant ID"],
                        row["Product ID"],
                        row["Inventory Item ID"],
                        row["Updated At"]
                    )
                )

        print(f"[DB] Metadata inserted for store: {store_name} ({len(rows)} rows)")

    except Exception as e:
        print(f"[DB] Postgres insert failed: {e} — continuing without DB")