# Shopify API configuration
API_VERSION = "2026-01"

# These will be set at runtime
STORE = None
STORE_NAME = None
ACCESS_TOKEN = None


def configure_shopify(store_domain, access_token):
    """
    Configure Shopify credentials dynamically.
    """
    global STORE
    global STORE_NAME
    global ACCESS_TOKEN

    STORE = store_domain
    ACCESS_TOKEN = access_token

    # Derive store name automatically
    STORE_NAME = store_domain.split(".")[0]

    print("[CONFIG] Shopify configured")
    print("[CONFIG] Store:", STORE)
    print("[CONFIG] Store name:", STORE_NAME)