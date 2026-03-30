import glob
import json
import os
import time
import products.store_paths as store_paths

MAX_SNAPSHOTS = 5


def save_articles_snapshot(snapshot):
    timestamp     = int(time.time())
    snapshot_dir  = store_paths.SNAPSHOT_DIR

    snapshot_file = os.path.join(snapshot_dir, f'articles_snapshot_{timestamp}.json')
    latest_file   = os.path.join(snapshot_dir, 'articles_latest_snapshot.json')

    payload = {
        'timestamp':      timestamp,
        'articles_count': len(snapshot),
        'data':           snapshot,
    }

    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)

    with open(latest_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)

    print(f"[BLOGS SNAPSHOT] Saved {len(snapshot)} articles → {snapshot_file}")

    _prune_snapshots(snapshot_dir, MAX_SNAPSHOTS)


def _prune_snapshots(snapshot_dir, max_keep):
    pattern = os.path.join(snapshot_dir, 'articles_snapshot_*.json')
    files   = sorted(glob.glob(pattern))
    to_delete = files[:-max_keep] if len(files) > max_keep else []
    for f in to_delete:
        try:
            os.remove(f)
            print(f"[BLOGS SNAPSHOT] Pruned: {os.path.basename(f)}")
        except Exception as e:
            print(f"[BLOGS SNAPSHOT] Could not prune {f}: {e}")