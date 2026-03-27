from products.client import graphql_request
from syncing.payload_cleaner import clean_value


# ------------------------------------------------
# Activate inventory item at location
# ------------------------------------------------

def activate_inventory_at_location(inventory_item_id, location_id):
    """
    Activate an inventory item at a location.
    Required before setting quantities if item
    has never been stocked at that location before.
    """

    print(f"[INVENTORY] Activating {inventory_item_id} at {location_id}")

    mutation = """
    mutation inventoryActivate($inventoryItemId: ID!, $locationId: ID!) {
      inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId) {
        inventoryLevel {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, {
        "inventoryItemId": inventory_item_id,
        "locationId": location_id
    })

    errors = result["data"]["inventoryActivate"]["userErrors"]

    if errors:
        print("[INVENTORY] Activation errors:", errors)
        return False

    print("[INVENTORY] Activation SUCCESS")
    return True


# ------------------------------------------------
# Main inventory update
# ------------------------------------------------

def update_inventory(row, location_map, all_columns, snapshot_products=None):
    """
    Update inventory levels across all changed locations.

    Collects ALL location quantities first, activates any new locations,
    then fires ONE inventorySetOnHandQuantities mutation with all locations
    in a single setQuantities array — regardless of how many locations.

    Was: 1 mutation per location (2 locations = 2 mutations)
    Now: 1 mutation total for all locations combined

    Args:
        row:               pandas Series or dict — the CSV row
        location_map:      dict — location name → location GID
        all_columns:       list — all CSV column names
        snapshot_products: snapshot dict — to check stocked locations
    """

    inventory_item_id = row.get("Inventory Item ID")
    product_id        = row.get("Product ID")
    variant_id        = row.get("Variant ID")

    print(f"[INVENTORY] Updating inventory for item {inventory_item_id}")

    # ── Build stocked locations from snapshot ─────────────────────────────
    # No API call needed — snapshot already has this info
    stocked_locations = set()

    if snapshot_products and product_id:
        product_snap = snapshot_products.get(product_id, {})
        for v_entry in product_snap.get("variants", []):
            if v_entry["variant"].get("id") == variant_id:
                stocked_locations = set(v_entry.get("inventory", {}).keys())
                break

    print(f"[INVENTORY] Stocked locations: {stocked_locations or 'none'}")

    # ── Collect all valid locations and quantities ─────────────────────────
    set_quantities = []   # final batch payload — built after activations

    for column in all_columns:

        if not column.startswith("Inventory Qty -"):
            continue

        location_name = column.replace("Inventory Qty - ", "")
        location_id   = location_map.get(location_name)

        if not location_id:
            print(f"[INVENTORY] Location not in map: {location_name} — skipping")
            continue

        qty_raw = row.get(column)
        qty     = clean_value(qty_raw)

        if qty is None:
            print(f"[INVENTORY] Qty is None for {location_name} — skipping")
            continue

        try:
            qty = int(float(str(qty)))
        except (ValueError, TypeError):
            print(f"[INVENTORY] Invalid qty: {qty_raw} — skipping")
            continue

        print(f"[INVENTORY] Location: {location_name} | Qty: {qty}")

        # ── Activate if not stocked at this location ──────────────────────
        if location_name not in stocked_locations:
            print(f"[INVENTORY] Not stocked at {location_name} — activating first")
            activated = activate_inventory_at_location(inventory_item_id, location_id)
            if not activated:
                print(f"[INVENTORY] Could not activate at {location_name} — skipping")
                continue

        set_quantities.append({
            "inventoryItemId": inventory_item_id,
            "locationId":      location_id,
            "quantity":        qty
        })

    if not set_quantities:
        print("[INVENTORY] No valid locations to update — skipping")
        return

    # ── Single batched mutation for ALL locations ─────────────────────────
    # Was: one mutation per location
    # Now: one mutation with all locations in setQuantities array
    payload = {
        "input": {
            "reason": "correction",
            "setQuantities": set_quantities
        }
    }

    mutation = """
    mutation inventorySetOnHandQuantities($input: InventorySetOnHandQuantitiesInput!) {
      inventorySetOnHandQuantities(input: $input) {
        inventoryAdjustmentGroup {
          reason
        }
        userErrors {
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, payload)
    errors = result["data"]["inventorySetOnHandQuantities"]["userErrors"]

    if errors:
        msg = "; ".join(f"{e.get('field','?')}: {e.get('message','?')}" for e in errors)
        print(f"[INVENTORY] Errors:", errors)
        raise Exception(f"[INVENTORY] {msg}")
    else:
        locations_updated = [q["locationId"] for q in set_quantities]
        print(f"[INVENTORY] SUCCESS — {len(set_quantities)} location(s) updated in 1 call")