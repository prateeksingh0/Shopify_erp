import os
import products.config as config
from django.conf import settings

# Store data root — configure SHOPIFY_DATA_ROOT in settings.py
# Falls back to a 'stores' folder in the Django project root
BASE_DIR = getattr(settings, 'SHOPIFY_DATA_ROOT', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'stores'))

STORE_DIR       = None
DATA_DIR        = None
SNAPSHOT_DIR    = None
BULK_DIR        = None
IMAGE_CACHE_DIR = None


def initialize_store_paths():

    global STORE_DIR, DATA_DIR, SNAPSHOT_DIR, BULK_DIR, IMAGE_CACHE_DIR

    if not config.STORE_NAME:
        raise Exception("[PATHS] STORE_NAME not configured")

    STORE_DIR       = os.path.join(BASE_DIR, config.STORE_NAME)
    DATA_DIR        = os.path.join(STORE_DIR, "data")
    SNAPSHOT_DIR    = os.path.join(STORE_DIR, "snapshots")
    BULK_DIR        = os.path.join(STORE_DIR, "bulk")
    IMAGE_CACHE_DIR = os.path.join(STORE_DIR, "image_cache")

    os.makedirs(DATA_DIR,        exist_ok=True)
    os.makedirs(SNAPSHOT_DIR,    exist_ok=True)
    os.makedirs(BULK_DIR,        exist_ok=True)
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

    print("[PATHS] Store directory initialized")
    print("[PATHS] Store:",        config.STORE_NAME)
    print("[PATHS] Data dir:",     DATA_DIR)
    print("[PATHS] Snapshot dir:", SNAPSHOT_DIR)
    print("[PATHS] Bulk dir:",     BULK_DIR)
    print("[PATHS] Image cache:",  IMAGE_CACHE_DIR)