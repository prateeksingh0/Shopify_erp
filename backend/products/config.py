# Shopify API configuration
API_VERSION = "2026-01"

# These will be set at runtime
STORE = None
STORE_NAME = None
ACCESS_TOKEN = None
USER_ID    = None


def configure_shopify(store_domain, access_token, user_id=None):
    """
    Configure Shopify credentials dynamically.
    """
    global STORE, STORE_NAME, ACCESS_TOKEN, USER_ID

    STORE = store_domain
    ACCESS_TOKEN = access_token
    USER_ID      = user_id

    # Derive store name automatically
    STORE_NAME = store_domain.split(".")[0]

    print("[CONFIG] Shopify configured")
    print("[CONFIG] Store:", STORE)
    print("[CONFIG] Store name:", STORE_NAME)
    print("[CONFIG] User ID:", USER_ID)