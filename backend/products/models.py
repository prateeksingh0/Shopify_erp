from django.db import models


class Product(models.Model):
    store_name         = models.CharField(max_length=100)
    product_gid        = models.CharField(max_length=255)
    handle             = models.CharField(max_length=255, blank=True, null=True)
    updated_at_shopify = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'products'
        unique_together = ('store_name', 'product_gid')

    def __str__(self):
        return self.product_gid


class Variant(models.Model):
    store_name          = models.CharField(max_length=100)
    variant_gid         = models.CharField(max_length=255)
    product_gid         = models.CharField(max_length=255)
    inventory_item_gid  = models.CharField(max_length=255, blank=True, null=True)
    updated_at_shopify  = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'variants'
        unique_together = ('store_name', 'variant_gid')

    def __str__(self):
        return self.variant_gid


def save_products_to_db(rows, store_name):
    """
    Upsert product and variant metadata into DB via Django ORM.
    Called after every fetch to keep DB in sync with Shopify.
    """
    if not store_name:
        print("[DB] No store name — skipping DB save")
        return

    try:
        for row in rows:
            Product.objects.update_or_create(
                store_name=store_name,
                product_gid=row["Product ID"],
                defaults={
                    "handle":             row.get("Handle"),
                    "updated_at_shopify": row.get("Updated At"),
                }
            )
            Variant.objects.update_or_create(
                store_name=store_name,
                variant_gid=row["Variant ID"],
                defaults={
                    "product_gid":        row.get("Product ID"),
                    "inventory_item_gid": row.get("Inventory Item ID"),
                    "updated_at_shopify": row.get("Updated At"),
                }
            )
        print(f"[DB] Metadata saved for store: {store_name} ({len(rows)} rows)")
    except Exception as e:
        print(f"[DB] DB save failed: {e} — continuing without DB")