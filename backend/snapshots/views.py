import glob
import json
import os

import pandas as pd
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from stores.models import Store


def get_store_or_404(store_name):
    try:
        return Store.objects.get(store_name=store_name)
    except Store.DoesNotExist:
        return None


def get_snapshots_dir(store_name):
    base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
    return os.path.join(base, store_name, 'snapshots')


class SnapshotListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        snapshots_dir = get_snapshots_dir(store_name)
        pattern = os.path.join(snapshots_dir, 'snapshot_*.json')
        files = sorted(glob.glob(pattern), reverse=True)  # newest first

        snapshots = []
        for f in files:
            filename = os.path.basename(f)
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                snapshots.append({
                    'filename':       filename,
                    'timestamp':      data.get('timestamp'),
                    'products_count': data.get('products_count'),
                })
            except Exception:
                continue

        return Response({'snapshots': snapshots})


class SnapshotDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name, timestamp):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        snapshots_dir = get_snapshots_dir(store_name)

        if timestamp == 'latest':
            filepath = os.path.join(snapshots_dir, 'latest_snapshot.json')
        else:
            filepath = os.path.join(snapshots_dir, f'snapshot_{timestamp}.json')

        if not os.path.exists(filepath):
            return Response({'error': 'Snapshot not found'}, status=404)

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return Response(data)


class SnapshotRollbackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, store_name, timestamp):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        snapshots_dir = get_snapshots_dir(store_name)
        filepath = os.path.join(snapshots_dir, f'snapshot_{timestamp}.json')

        if not os.path.exists(filepath):
            return Response({'error': 'Snapshot not found'}, status=404)

        # Load chosen snapshot
        with open(filepath, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)

        # Load current CSV
        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        csv_path = os.path.join(base, store_name, 'data', 'products_master.csv')

        if not os.path.exists(csv_path):
            return Response({'error': 'No current data. Run fetch first.'}, status=404)

        current_df = pd.read_csv(csv_path, dtype=str).fillna('')
        current_rows = current_df.to_dict(orient='records')

        # Build lookup: variant_id → current row
        current_by_variant = {
            row.get('Variant ID'): row
            for row in current_rows
            if row.get('Variant ID')
        }

        # Build snapshot rows from snapshot data
        snapshot_data = snapshot.get('data', {})
        snapshot_rows = []
        changed_indices = []

        for product_id, product_data in snapshot_data.items():
            product = product_data.get('product', {})
            for variant_entry in product_data.get('variants', []):
                variant = variant_entry.get('variant', {})
                variant_id = variant.get('id')

                # Build a comparable row from snapshot
                snap_row = {
                    'Product ID': product_id,
                    'Variant ID': variant_id,
                    'Title':      product.get('title', ''),
                    'Vendor':     product.get('vendor', ''),
                    'Status':     product.get('status', ''),
                    'Variant Price': variant.get('price', ''),
                    'Variant SKU':   variant.get('sku', ''),
                }

                snapshot_rows.append(snap_row)

                # Mark as changed if different from current
                current = current_by_variant.get(variant_id)
                if not current:
                    changed_indices.append(len(snapshot_rows) - 1)
                elif any(
                    str(snap_row.get(k, '')) != str(current.get(k, ''))
                    for k in snap_row
                ):
                    changed_indices.append(len(snapshot_rows) - 1)

        return Response({
            'snapshot_timestamp': snapshot.get('timestamp'),
            'rows':               snapshot_rows,
            'changed_indices':    changed_indices,
            'total_rows':         len(snapshot_rows),
            'changed_count':      len(changed_indices),
        })