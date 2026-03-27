import requests
import time

import products.config as config


session = requests.Session()


def get_graphql_url():
    """
    Build Shopify GraphQL endpoint dynamically.
    """
    if not config.STORE:
        raise Exception("[CONFIG] Shopify store not configured")

    return f"https://{config.STORE}/admin/api/{config.API_VERSION}/graphql.json"


def graphql_request(query, variables=None, retries=3):

    url = get_graphql_url()

    headers = {
        "X-Shopify-Access-Token": config.ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "query": query,
        "variables": variables
    }

    for attempt in range(retries):

        try:

            print("[SHOPIFY] Sending GraphQL request...")

            r = session.post(
                url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code == 429:
                print("[SHOPIFY] Rate limited. Sleeping...")
                time.sleep(2)
                continue

            r.raise_for_status()

            data = r.json()

            errors = data.get("errors") or []
            if errors:
                # Shopify cost-based throttle returns 200 OK with errors body
                throttled = any(
                    "THROTTLED" in str((e.get("extensions") or {}).get("code", "")).upper()
                    for e in errors
                )
                if throttled:
                    wait = 2 * (attempt + 1)
                    print(f"[SHOPIFY] Throttled (cost limit) — retrying in {wait}s...")
                    time.sleep(wait)
                    continue

                # Real error (bad token, invalid query, etc.)
                raise Exception(f"[SHOPIFY] GraphQL error: {errors}")

            return data

        except requests.exceptions.RequestException as e:

            print("[SHOPIFY] Request failed:", str(e))

            if attempt < retries - 1:

                print("[SHOPIFY] Retrying...")
                time.sleep(2)

            else:

                raise Exception("[SHOPIFY] Request failed after retries")

    raise Exception("[SHOPIFY] All retries exhausted")