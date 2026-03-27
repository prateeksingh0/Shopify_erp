from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from products.client import graphql_request


# ── Tuning constants ────────────────────────────────────────────────────────
BATCH_SIZE  = 50    # IDs per GraphQL request  (50 → safe under query-string limits)
MAX_WORKERS = 10    # concurrent batch requests (stays well under Shopify throttle)
MAX_RETRIES = 3     # retries per batch on transient / throttle errors
RETRY_DELAY = 2.0   # base seconds between retries (multiplied by attempt number)
# ────────────────────────────────────────────────────────────────────────────


def fetch_inventory_levels(inventory_item_ids, locations):
    """
    Fetch inventory levels for all inventory item IDs.

    Batches IDs into groups of BATCH_SIZE and runs batches concurrently.
    Handles Shopify throttle errors with automatic retry + backoff.

    Args:
        inventory_item_ids : list/set of GID strings
        locations          : dict  location_gid → location_name

    Returns:
        dict  inventory_item_gid → { location_name: quantity }
        (same format as before — nothing downstream changes)
    """

    print("[INVENTORY] Fetching inventory levels...")
    print("[INVENTORY] Items requested:", len(inventory_item_ids))

    if not inventory_item_ids:
        print("[INVENTORY] No items to fetch.")
        return {}

    ids_list = list(inventory_item_ids)

    # ── Split into batches ──────────────────────────────────────────────────
    batches = [
        ids_list[i : i + BATCH_SIZE]
        for i in range(0, len(ids_list), BATCH_SIZE)
    ]

    print(
        f"[INVENTORY] Batching {len(ids_list)} items into "
        f"{len(batches)} requests (batch size: {BATCH_SIZE})"
    )

    # ── GraphQL query ───────────────────────────────────────────────────────
    batch_query = """
    query getInventoryBatch($query: String!) {
      inventoryItems(first: 250, query: $query) {
        edges {
          node {
            id
            inventoryLevels(first: 250) {
              edges {
                node {
                  location {
                    id
                  }
                  quantities(names: ["available"]) {
                    name
                    quantity
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    def _gid_to_numeric(gid):
        return str(gid).split("/")[-1]

    def fetch_batch(batch):
        query_filter = " OR ".join(f"id:{_gid_to_numeric(gid)}" for gid in batch)

        for attempt in range(MAX_RETRIES):
            try:
                result = graphql_request(batch_query, {"query": query_filter})

                # Throttle detection
                errors = result.get("errors") or []
                throttled = any(
                    "THROTTLED" in str((e.get("extensions") or {}).get("code", "")).upper()
                    for e in errors
                )
                if throttled:
                    wait = RETRY_DELAY * (attempt + 1)
                    print(f"[INVENTORY] Throttled — retrying in {wait:.1f}s")
                    time.sleep(wait)
                    continue

                edges = (
                    (result.get("data") or {})
                    .get("inventoryItems", {})
                    .get("edges", [])
                )

                batch_data = {}
                for edge in edges:
                    node   = edge["node"]
                    inv_id = node["id"]
                    levels = node.get("inventoryLevels", {}).get("edges", [])

                    data = {}
                    for level in levels:
                        location_id   = level["node"]["location"]["id"]
                        quantity      = level["node"]["quantities"][0]["quantity"]
                        location_name = locations.get(location_id)
                        if location_name:
                            data[location_name] = quantity

                    batch_data[inv_id] = data

                return batch_data

            except Exception as e:
                print(f"[INVENTORY] Batch error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        print(f"[INVENTORY] Batch failed after {MAX_RETRIES} attempts — returning empty for {len(batch)} items")
        return {gid: {} for gid in batch}

    # ── Run all batches concurrently ────────────────────────────────────────
    inventory_data = {}
    workers = min(MAX_WORKERS, len(batches))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_batch, batch): batch
            for batch in batches
        }
        for future in as_completed(futures):
            try:
                batch_data = future.result()
                inventory_data.update(batch_data)
            except Exception as e:
                print(f"[INVENTORY] Future error: {e}")

    print("[INVENTORY] Inventory fetch completed.")
    print(f"[INVENTORY] Inventory records received: {len(inventory_data)}")

    return inventory_data