from products.client import graphql_request
from syncing.payload_cleaner import clean_value
import math


def _is_empty(val):
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    return str(val).strip().lower() in ('', 'nan', 'none')


def update_inventory_item(row):

    inventory_item_id = row.get("Inventory Item ID")

    if _is_empty(inventory_item_id):
        print("[INVENTORY ITEM] No Inventory Item ID — skipping")
        return

    print(f"[INVENTORY ITEM] Updating item {inventory_item_id}")

    # Build input — only include fields that have values
    item_input = {}

    sku  = clean_value(row.get("Variant SKU"))
    cost = clean_value(row.get("Cost per item"))

    if not _is_empty(sku):
        item_input["sku"] = str(sku)
    if not _is_empty(cost):
        item_input["cost"] = str(cost)

    # Nothing to update
    if not item_input:
        print("[INVENTORY ITEM] No fields to update — skipping")
        return

    print("[INVENTORY ITEM] Payload:", item_input)

    mutation = """
    mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
      inventoryItemUpdate(id: $id, input: $input) {
        inventoryItem { id }
        userErrors { field message }
      }
    }
    """

    result = graphql_request(mutation, {
        "id":    inventory_item_id,
        "input": item_input
    })

    if "data" not in result or result["data"] is None:
        print("[INVENTORY ITEM] Unexpected response:", result)
        return

    errors = result["data"]["inventoryItemUpdate"]["userErrors"]

    if errors:
        print("[INVENTORY ITEM] ERROR:", errors)
    else:
        print("[INVENTORY ITEM] SUCCESS")

def enable_inventory_tracking(inventory_item_id):
    """
    Enable inventory tracking on an inventory item.
    Must be called before setting quantities — if tracked=false,
    Shopify silently ignores all quantity updates.
    Returns True if already tracked or successfully enabled.
    """
    import math

    if not inventory_item_id or (isinstance(inventory_item_id, float) and math.isnan(inventory_item_id)):
        return False

    # First check if already tracked
    query = """
    query($id: ID!) {
      inventoryItem(id: $id) {
        id
        tracked
      }
    }
    """
    r = graphql_request(query, {"id": inventory_item_id})

    if not r.get("data") or not r["data"].get("inventoryItem"):
        print(f"[INVENTORY ITEM] Could not fetch tracked status for {inventory_item_id}")
        return False

    tracked = r["data"]["inventoryItem"]["tracked"]

    if tracked:
        return True  # already tracked — nothing to do

    print(f"[INVENTORY ITEM] Tracking disabled — enabling for {inventory_item_id}")

    mutation = """
    mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
      inventoryItemUpdate(id: $id, input: $input) {
        inventoryItem { id tracked }
        userErrors { field message }
      }
    }
    """

    result = graphql_request(mutation, {
        "id":    inventory_item_id,
        "input": {"tracked": True}
    })

    if not result.get("data"):
        print("[INVENTORY ITEM] Empty response enabling tracking:", result)
        return False

    errors = result["data"]["inventoryItemUpdate"]["userErrors"]
    if errors:
        print("[INVENTORY ITEM] Error enabling tracking:", errors)
        return False

    print("[INVENTORY ITEM] Tracking enabled")
    return True