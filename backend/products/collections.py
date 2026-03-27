from products.client import graphql_request

# Shopify API page size limits (250 is the maximum allowed per request)
SHOPIFY_PAGE_SIZE = 250


def fetch_collections():

    print("[COLLECTIONS] Fetching collections...")

    query = """
    query getCollections($cursor: String) {
      collections(first: %(page_size)s, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            id
            handle
            title
            products(first: %(page_size)s) {
              edges {
                node {
                  id
                }
              }
            }
          }
        }
      }
    }
    """ % {"page_size": SHOPIFY_PAGE_SIZE}

    collection_map = {}
    cursor = None

    while True:

        variables = {"cursor": cursor} if cursor else {}
        result = graphql_request(query, variables)
        data = result.get("data", {}).get("collections", {})

        for edge in data.get("edges", []):
            node = edge["node"]
            collection_map[node["id"]] = {
                "title": node["title"],
                "handle": node["handle"],
                "products": [p["node"]["id"] for p in node["products"]["edges"]],
            }

        page_info = data.get("pageInfo", {})
        if page_info.get("hasNextPage"):
            cursor = page_info["endCursor"]
        else:
            break

    product_collections = {}

    for collection in collection_map.values():

        for product_id in collection["products"]:

            if product_id not in product_collections:
                product_collections[product_id] = {
                    "names": [],
                    "handles": []
                }

            product_collections[product_id]["names"].append(collection["title"])
            product_collections[product_id]["handles"].append(collection["handle"])

    print("[COLLECTIONS] Collections parsed:", len(collection_map))
    print("[COLLECTIONS] Products with collections:", len(product_collections))

    return product_collections