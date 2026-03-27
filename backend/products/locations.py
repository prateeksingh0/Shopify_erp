from products.client import graphql_request


def sanitize_location_name(name):
    """
    Make location name safe for CSV column usage.
    """
    return name.replace(",", "").replace("\n", " ").strip()


def fetch_locations():

    print("[LOCATIONS] Fetching store locations...")

    query = """
    {
      locations(first:250){
        edges{
          node{
            id
            name
          }
        }
      }
    }
    """

    result = graphql_request(query)

    if "errors" in result:
        raise Exception(f"[LOCATIONS] GraphQL error: {result['errors']}")

    data = result.get("data")

    if not data or "locations" not in data:
        raise Exception("[LOCATIONS] Invalid response from Shopify")

    edges = data["locations"]["edges"]

    id_to_name = {}
    name_to_id = {}

    for edge in edges:

        loc = edge["node"]

        loc_id = loc["id"]
        loc_name = sanitize_location_name(loc["name"])

        id_to_name[loc_id] = loc_name
        name_to_id[loc_name] = loc_id

    print("[LOCATIONS] Locations detected:", len(id_to_name))

    for name in name_to_id:
        print("[LOCATIONS] Location:", name)

    return id_to_name, name_to_id