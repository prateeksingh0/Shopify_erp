import time
import requests
import os

from products.client import graphql_request
import products.store_paths as store_paths

# Polling intervals for bulk operation status checks
BULK_POLL_INTERVAL_CREATED = 5   # seconds — Shopify queuing phase (slow, no point polling fast)
BULK_POLL_INTERVAL_RUNNING = 2   # seconds — Shopify processing phase
BULK_MAX_RETRIES = 1800          # max status-check iterations (~1 hour at 2s)


# -------------------------
# Start Bulk Operation
# -------------------------

def start_bulk_operation(query):

    print("[BULK] Starting bulk operation...")

    mutation = """
    mutation bulkOperationRunQuery($query:String!){
      bulkOperationRunQuery(query:$query){
        bulkOperation{
          id
          status
        }
        userErrors{
          field
          message
        }
      }
    }
    """

    result = graphql_request(mutation, {"query": query})

    if "errors" in result:
        raise Exception(f"[BULK] GraphQL error: {result['errors']}")

    errors = result["data"]["bulkOperationRunQuery"]["userErrors"]

    if errors:
        raise Exception(f"[BULK] Bulk operation error: {errors}")

    operation = result["data"]["bulkOperationRunQuery"]["bulkOperation"]

    print("[BULK] Operation started:", operation["id"])

    return operation


# -------------------------
# Check Bulk Status
# -------------------------

def get_bulk_status():

    query = """
    {
      currentBulkOperation{
        id
        status
        url
      }
    }
    """

    return graphql_request(query)


# -------------------------
# Wait For Bulk Completion
# -------------------------

def wait_for_bulk():

    print("[BULK] Waiting for bulk operation...")

    retries = 0
    max_retries = BULK_MAX_RETRIES

    while True:

        retries += 1

        if retries > max_retries:
            raise Exception("[BULK] Bulk operation timeout")

        status = get_bulk_status()

        op = status.get("data", {}).get("currentBulkOperation")

        if not op:
            raise Exception("[BULK] No bulk operation running")

        state = op["status"]

        print("[BULK] Status:", state)

        if state == "COMPLETED":
            print("[BULK] Bulk export completed.")
            return op["url"]

        if state in ["FAILED", "CANCELED"]:
            raise Exception(f"[BULK] Bulk operation failed: {state}")

        # CREATED = Shopify is queueing the job (takes 30-90s) — no need to hammer every 1.5s
        # RUNNING = actively processing — poll a bit more often
        if state == "CREATED":
            time.sleep(BULK_POLL_INTERVAL_CREATED)
        else:
            time.sleep(BULK_POLL_INTERVAL_RUNNING)


# -------------------------
# Download JSONL
# -------------------------

def download_jsonl(url, filename):

    print("[BULK] Downloading JSONL file...")

    path = os.path.join(store_paths.BULK_DIR, filename)

    with requests.get(url, stream=True) as r:

        if r.status_code != 200:
            raise Exception(f"[BULK] Download failed: {r.status_code}")

        with open(path, "wb") as f:

            for chunk in r.iter_content(chunk_size=8192):

                if chunk:
                    f.write(chunk)

    print("[BULK] JSONL downloaded:", path)

    return path