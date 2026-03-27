import requests
from .models import Store


SHOPIFY_SCOPES = ",".join([
    "read_products",
    "write_products",
    "read_inventory",
    "write_inventory",
    "read_locations",
    "read_collections",
    "write_collections",
])


def generate_access_token(domain, client_id, client_secret):
    """
    Exchange client credentials for a Shopify access token.
    Called when connecting a store or refreshing an expired token.
    """
    url = f"https://{domain}/admin/oauth/access_token"
    payload = {
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         SHOPIFY_SCOPES,
    }
    r = requests.post(url, json=payload, timeout=15)

    if r.status_code != 200:
        raise Exception(f"Shopify token error: {r.status_code} — {r.text}")

    data = r.json()
    token = data.get("access_token")

    if not token:
        raise Exception(f"No access_token in response: {data}")

    return token


def refresh_token_if_needed(store: Store):
    """
    Regenerate access token using stored credentials.
    Called automatically when a 401 is detected.
    """
    print(f"[TOKEN] Refreshing token for {store.store_name}...")
    token = generate_access_token(
        store.domain,
        store.client_id,
        store.client_secret,
    )
    store.access_token = token
    store.save(update_fields=['access_token'])
    print(f"[TOKEN] Token refreshed for {store.store_name}")
    return token