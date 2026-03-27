from products.client import graphql_request


def _parse_csv_tokens(raw_value):
  if raw_value is None:
    return []

  text = str(raw_value).strip()
  if text.lower() in ("", "nan", "none", "null"):
    return []

  return [
    x.strip() for x in text.split(",")
    if x.strip() and x.strip().lower() not in ("nan", "none", "null")
  ]


def _effective_handles_from_row(row):
  """
  Collection Handles is the real editable input.
  Collection Names is display-only and ignored by sync logic.

  Improvements:
  - trims whitespace
  - ignores blank/nan/none/null values
  - de-duplicates repeated handles
  - normalizes handle case
  - sorts final list so order changes do not cause false deltas
  """
  seen = set()
  desired = []

  for handle in _parse_csv_tokens(row.get("Collection Handles")):
    normalized_handle = handle.lower()
    if normalized_handle in seen:
      continue

    seen.add(normalized_handle)
    desired.append(normalized_handle)

  desired.sort()
  return desired


def _get_product_collections(product_id):
    """Return product collections with id, handle, title, and smart/manual metadata."""
    query = """
    query getProductCollections($id: ID!) {
      product(id: $id) {
        id
        collections(first: 250) {
          edges {
            node {
              id
              handle
              title
              ruleSet {
                rules {
                  column
                }
              }
            }
          }
        }
      }
    }
    """

    result = graphql_request(query, {"id": product_id})
    edges = (((result.get("data") or {}).get("product") or {}).get("collections") or {}).get("edges") or []
    return [e.get("node") for e in edges if e.get("node")]


def _resolve_collection_by_handle(handle):
    """Resolve a collection by handle, returning None if not found."""
    query = """
    query getCollectionByHandle($handle: String!) {
      collectionByHandle(handle: $handle) {
        id
        handle
        title
        ruleSet {
          rules {
            column
          }
        }
      }
    }
    """

    result = graphql_request(query, {"handle": handle})
    return (result.get("data") or {}).get("collectionByHandle")


def validate_collection_handles(row):
    """
    Validate Collection Handles from the row.
    Returns (ok, message).

    Rules:
    - every handle must exist
    - smart collections are rejected for manual add/remove flow
    """
    desired_handles = _effective_handles_from_row(row)
    if not desired_handles:
        return True, ""

    invalid = []
    smart = []

    for handle in desired_handles:
        collection = _resolve_collection_by_handle(handle)
        if not collection:
            invalid.append(handle)
            continue

        rule_set = collection.get("ruleSet")
        if rule_set and rule_set.get("rules"):
            smart.append(handle)

    if invalid:
        return False, f"Invalid Collection Handles: {', '.join(invalid)}"

    if smart:
        return False, f"Smart collections not allowed for manual add: {', '.join(smart)}"

    return True, ""


def _remove_product_from_collection(collection_id, product_id, title):
    mutation = """
    mutation collectionRemoveProducts($id: ID!, $productIds: [ID!]!) {
      collectionRemoveProducts(id: $id, productIds: $productIds) {
        userErrors {
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, {"id": collection_id, "productIds": [product_id]})
    errors = result["data"]["collectionRemoveProducts"]["userErrors"]
    if errors:
        print(f"[COLLECTION] Remove errors for {title}:", errors)
    else:
        print(f"[COLLECTION] Removed from {title}")


def _add_product_to_collection(collection_id, product_id, title):
    mutation = """
    mutation collectionAddProducts($id: ID!, $productIds: [ID!]!) {
      collectionAddProducts(id: $id, productIds: $productIds) {
        userErrors {
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, {"id": collection_id, "productIds": [product_id]})
    errors = result["data"]["collectionAddProducts"]["userErrors"]
    if errors:
        print(f"[COLLECTION] Add errors for {title}:", errors)
    else:
        print(f"[COLLECTION] Added to {title}")


# ------------------------------------------------
# Check if collection is smart (has rules)
# ------------------------------------------------

def is_smart_collection(collection_id):
    """
    Query Shopify to check if a collection has ruleSet.
    Smart collections have rules and cannot have products
    manually added — they must be skipped.
    """

    query = """
    query getCollection($id: ID!) {
      collection(id: $id) {
        id
        title
        ruleSet {
          rules {
            column
          }
        }
      }
    }
    """

    result = graphql_request(query, {"id": collection_id})

    collection = result.get("data", {}).get("collection")

    if not collection:
        return False

    rule_set = collection.get("ruleSet")

    # If ruleSet exists and has rules → smart collection
    if rule_set and rule_set.get("rules"):
        print(f"[COLLECTION] Smart collection detected: {collection.get('title')} — skipping")
        return True

    return False


# ------------------------------------------------
# Main collection update
# ------------------------------------------------

def update_collections(row):
    """
    Add product to manual collections only.
    Smart collections are detected and skipped automatically.
    """

    product_id = row.get("Product ID")
    desired_handles = _effective_handles_from_row(row)
    desired_set = {h.lower() for h in desired_handles}

    print(f"[COLLECTION] Desired handles ({len(desired_handles)}): {desired_handles}")

    current_collections = _get_product_collections(product_id)
    current_manual = []
    current_manual_handles = set()

    for c in current_collections:
      rule_set = c.get("ruleSet")
      if rule_set and rule_set.get("rules"):
        continue
      handle = (c.get("handle") or "").strip().lower()
      if handle:
        current_manual_handles.add(handle)
      current_manual.append(c)

    print(f"[COLLECTION] Current manual collections: {len(current_manual)}")

    # Remove manual collections that are no longer desired.
    for c in current_manual:
      handle = (c.get("handle") or "").strip().lower()
      if handle and handle not in desired_set:
        title = c.get("title") or handle
        print(f"[COLLECTION] Removing {product_id} from: {title}")
        _remove_product_from_collection(c["id"], product_id, title)

    # Add desired manual collections not currently attached.
    for handle in desired_handles:
      low = handle.lower()
      if low in current_manual_handles:
        continue

      print(f"[COLLECTION] Looking up handle: {handle}")
      collection = _resolve_collection_by_handle(handle)

      if not collection:
        print(f"[COLLECTION] Collection not found: {handle} — skipping")
        continue

      rule_set = collection.get("ruleSet")
      title = collection.get("title") or handle
      if rule_set and rule_set.get("rules"):
        print(f"[COLLECTION] '{title}' is a smart collection — skipping")
        continue

      print(f"[COLLECTION] Adding {product_id} to manual collection: {title}")
      _add_product_to_collection(collection["id"], product_id, title)