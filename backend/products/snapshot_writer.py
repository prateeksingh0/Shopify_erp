import glob
import json
import os
import time
import products.store_paths as store_paths

MAX_SNAPSHOTS = 5


def save_snapshot(snapshot):

    timestamp = int(time.time())

    snapshot_file = os.path.join(
        store_paths.SNAPSHOT_DIR,
        f"snapshot_{timestamp}.json"
    )

    latest_file = os.path.join(
        store_paths.SNAPSHOT_DIR,
        "latest_snapshot.json"
    )

    print("[SNAPSHOT] Saving snapshot...")

    snapshot_payload = {
        "timestamp": timestamp,
        "products_count": len(snapshot),
        "data": snapshot
    }

    # Save historical snapshot
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, indent=2)

    # Update latest snapshot
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, indent=2)

    print("[SNAPSHOT] Snapshot saved:", snapshot_file)
    print("[SNAPSHOT] Latest snapshot updated.")
    print("[SNAPSHOT] Products stored:", len(snapshot))

    # Prune old snapshots — keep only the most recent MAX_SNAPSHOTS
    _prune_snapshots(store_paths.SNAPSHOT_DIR, MAX_SNAPSHOTS)


def _prune_snapshots(snapshot_dir: str, max_keep: int):
    """Delete the oldest snapshot files so only max_keep remain."""
    pattern = os.path.join(snapshot_dir, "snapshot_*.json")
    files = sorted(glob.glob(pattern))   # ascending order → oldest first
    to_delete = files[:-max_keep] if len(files) > max_keep else []
    for f in to_delete:
        try:
            os.remove(f)
            print(f"[SNAPSHOT] Pruned: {os.path.basename(f)}")
        except Exception as e:
            print(f"[SNAPSHOT] Could not prune {f}: {e}")