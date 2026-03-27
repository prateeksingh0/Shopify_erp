from products.client import graphql_request
from syncing.payload_cleaner import clean_value


def update_metafields(row, all_columns, snapshot_products=None, owner_id_override=None):
    """
    Update metafields for a product OR a variant.

    KEY DESIGN:
    Shopify metafields are owned by a specific entity via ownerId.
    - Product metafields → ownerId = product GID
    - Variant metafields → ownerId = variant GID

    The caller (updater.py) decides which owner to use:
      update_metafields(..., owner_id_override=product_id)  → product metafields
      update_metafields(..., owner_id_override=variant_id)  → variant metafields

    all_columns is scoped by the caller too — only the relevant
    columns for this owner are passed in (product_meta_cols or
    variant_meta_cols from split_metafield_columns in updater.py).

    Types are resolved from snapshot — fully dynamic, no hardcoding.

    Args:
        row:               pandas Series or dict — the CSV row
        all_columns:       list — metafield column names to process
                           (already scoped to product OR variant by caller)
        snapshot_products: snapshot dict — for type lookup
        owner_id_override: GID to use as ownerId
                           If None, falls back to Product ID
    """

    product_id = row.get("Product ID")
    variant_id = row.get("Variant ID")

    # Determine owner — caller explicitly passes the right ID
    owner_id = owner_id_override or product_id

    owner_type = "variant" if owner_id == variant_id else "product"

    print(f"[METAFIELD] Updating {owner_type} metafields for {owner_id}")

    # -------------------------
    # Build type maps from snapshot
    # product_type_map → {ns.key: type} for product metafields
    # variant_type_map → {ns.key: type} for this specific variant
    # -------------------------

    product_type_map = {}
    variant_type_map = {}

    if snapshot_products and product_id:

        product_snap = snapshot_products.get(product_id, {})

        for ns_key, entry in product_snap.get("product_metafields", {}).items():
            if isinstance(entry, dict):
                product_type_map[ns_key] = entry.get("type", "single_line_text_field")

        if variant_id:
            for v_entry in product_snap.get("variants", []):
                if v_entry["variant"].get("id") == variant_id:
                    for ns_key, entry in v_entry.get("metafields", {}).items():
                        if isinstance(entry, dict):
                            variant_type_map[ns_key] = entry.get("type", "single_line_text_field")
                    break

    # -------------------------
    # Build metafields list
    # all_columns is already scoped to the right owner by caller
    # -------------------------

    metafields = []
    to_delete = []   # (column, namespace, key) tuples where user cleared the value

    # global.title_tag and global.description_tag are Shopify SEO metafields.
    # They are identical to SEO Title / SEO Description and are already
    # sent via product_update. Sending them here as metafields would
    # overwrite the SEO update back to the old value.
    SEO_METAFIELDS = {"global.title_tag", "global.description_tag"}

    for column in all_columns:

        if "." not in column:
            continue

        if column.startswith("Inventory Qty -"):
            continue

        if column in SEO_METAFIELDS:
            continue

        parts = column.split(".", 1)
        if len(parts) != 2:
            continue

        namespace, key = parts

        value = clean_value(row.get(column))

        if value is None:
            # User cleared this metafield — queue for deletion
            to_delete.append((column, namespace, key))
            continue

        # Resolve type — variant map takes priority for variant owner
        if owner_type == "variant":
            mf_type = (
                variant_type_map.get(column)
                or product_type_map.get(column)
                or "single_line_text_field"
            )
        else:
            mf_type = (
                product_type_map.get(column)
                or "single_line_text_field"
            )

        value = str(value)

        print(f"[METAFIELD] {column} = {repr(value)} (type: {mf_type}, owner: {owner_type})")

        metafields.append({
            "ownerId":   owner_id,
            "namespace": namespace,
            "key":       key,
            "type":      mf_type,
            "value":     value
        })

    # ── Delete cleared metafields ─────────────────────────────────────────────
    # Shopify cannot set a metafield to empty — must delete it.
    # metafieldsDelete (plural) is the correct mutation in API 2026-01.
    # No need to fetch the GID first — can identify by ownerId + namespace + key.

    if to_delete:

        DELETE_MF = """
        mutation metafieldsDelete($metafields: [MetafieldIdentifierInput!]!) {
          metafieldsDelete(metafields: $metafields) {
            deletedMetafields { key namespace ownerId }
            userErrors { field message }
          }
        }
        """

        for column, namespace, key in to_delete:
            print(f"[METAFIELD] Clearing {column}...")
            try:
                del_result = graphql_request(DELETE_MF, {
                    "metafields": [{
                        "ownerId":   owner_id,
                        "namespace": namespace,
                        "key":       key
                    }]
                })
                del_errors = (
                    (del_result.get("data") or {})
                    .get("metafieldsDelete", {})
                    .get("userErrors") or []
                )
                if del_errors:
                    print(f"[METAFIELD] Delete errors for {column}: {del_errors}")
                else:
                    print(f"[METAFIELD] DELETED {column}")

            except Exception as e:
                print(f"[METAFIELD] Could not delete {column}: {e}")

    if not metafields:
        print("[METAFIELD] Nothing to update")
        return

    print(f"[METAFIELD] Sending {len(metafields)} metafield(s) to Shopify")

    mutation = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields {
          key
          namespace
          value
          type
        }
        userErrors {
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, {"metafields": metafields})

    if not result.get("data"):
        print("[METAFIELD] Empty response:", result)
        return

    errors = result["data"]["metafieldsSet"]["userErrors"]

    if errors:
        print("[METAFIELD] Errors:", errors)
    else:
        print(f"[METAFIELD] SUCCESS — {len(metafields)} metafield(s) updated")