import os
import time
import pandas as pd

from urllib.parse import unquote
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from stores.models import Store
from products.config import configure_shopify
from products.store_paths import initialize_store_paths
from products.locations import fetch_locations
from syncing.updater import run_updates
from syncing.models import SyncLog
from stores.token_manager import with_auto_refresh

def get_store_or_404(store_name, user):
    try:
        return Store.objects.get(store_name=store_name, user=user)
    except Store.DoesNotExist:
        return None


def get_store_base(user_id, store_name):
    base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
    return os.path.join(base, str(user_id), store_name)

class SyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        csv_path = os.path.join(get_store_base(request.user.id, store_name), 'data', 'products_master.csv')

        if not os.path.exists(csv_path):
            return Response(
                {'error': f'No data found for store {store_name}. Run fetch first.'},
                status=404
            )

        start = time.time()
        try:
            configure_shopify(store.domain, store.access_token, user_id=request.user.id)
            initialize_store_paths()
            _, location_map = fetch_locations()
            result = with_auto_refresh(
                store,
                lambda token: configure_shopify(store.domain, token, user_id=request.user.id),
                lambda: run_updates(csv_path, location_map)
            )
        except Exception as e:
            duration = int(time.time() - start)
            SyncLog.objects.create(store=store, duration_seconds=duration, status='error')
            return Response({'error': str(e)}, status=500)

        duration = int(time.time() - start)
        SyncLog.objects.create(
            store=store,
            duration_seconds=duration,
            total=result.get('total', 0),
            updated=result.get('updated', 0),
            created=result.get('created', 0),
            skipped=result.get('skipped', 0),
            deleted=result.get('deleted', 0),
            errors=result.get('errors', 0),
            conflicts=result.get('conflicts', 0),
            status='success',
        )
        return Response(result)


class SyncProductView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name, product_id):
        product_id = unquote(product_id)
        is_new = product_id == '__new__'
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        csv_path = os.path.join(get_store_base(request.user.id, store_name), 'data', 'products_master.csv')

        if not os.path.exists(csv_path):
            return Response({'error': f'No data found for store {store_name}. Run fetch first.'}, status=404)

        # ── Step 1: Patch only this product's rows in CSV ──────────────────
        product_row = request.data.get('productRow')
        variant_rows = request.data.get('variantRows')

        if product_row and variant_rows:
            df = pd.read_csv(csv_path, dtype=str).fillna('')
            new_rows = []

            for vr in variant_rows:
                vid = str(vr.get('Variant ID', '')).strip()

                if vid and vid.lower() not in ('nan', 'none', ''):
                    mask = df['Variant ID'].astype(str).str.strip() == vid
                    if mask.any():
                        idx = df[mask].index[0]
                        for col in df.columns:
                            if col in product_row:
                                df.at[idx, col] = str(product_row[col])
                            if col in vr:
                                df.at[idx, col] = str(vr[col])
                    else:
                        print(f'[SYNC PRODUCT] Variant ID {vid} not found in CSV')
                else:
                    new_row = {col: '' for col in df.columns}
                    for col in df.columns:
                        if col in product_row:
                            new_row[col] = str(product_row[col])
                        if col in vr:
                            new_row[col] = str(vr[col])
                    new_rows.append(new_row)
                    print(f'[SYNC PRODUCT] New variant detected — appending row')

            if new_rows:
                new_df = pd.DataFrame(new_rows, columns=df.columns)
                df = pd.concat([df, new_df], ignore_index=True)

            df.to_csv(csv_path, index=False)
            print(f'[SYNC PRODUCT] Patched {len(variant_rows)} variant row(s), {len(new_rows)} new row(s) for {product_id}')

        # ── Step 2: Run sync filtered to this product only ─────────────────
        try:
            configure_shopify(store.domain, store.access_token,user_id=request.user.id)
            initialize_store_paths()
            _, location_map = fetch_locations()

            if is_new:
                new_title = str(product_row.get('Title', '')).strip()
                df_full = pd.read_csv(csv_path, dtype=str).fillna('')
                mask = (
                    (df_full['Title'].astype(str).str.strip() == new_title) &
                    (df_full['Product ID'].astype(str).str.strip() == '')
                )
                df_new = df_full[mask].reset_index(drop=True)

                dummy = {col: 'DUMMY' for col in df_new.columns}
                df_with_dummy = pd.concat([df_new, pd.DataFrame([dummy])], ignore_index=True)
                tmp_path = csv_path.replace('products_master.csv', '_tmp_new_product.csv')
                df_with_dummy.to_csv(tmp_path, index=False)

                df_reload = pd.read_csv(tmp_path, dtype=str).fillna('')
                df_reload = df_reload[df_reload['Title'] != 'DUMMY'].reset_index(drop=True)
                df_reload.to_csv(tmp_path, index=False)

                try:
                    result = with_auto_refresh(
                        store,
                        lambda token: configure_shopify(store.domain, token, user_id=request.user.id),
                        lambda: run_updates(tmp_path, location_map, product_id_filter=None)
                    )
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            else:
                result = with_auto_refresh(
                    store,
                    lambda token: configure_shopify(store.domain, token, user_id=request.user.id),
                    lambda: run_updates(csv_path, location_map, product_id_filter=product_id)
                )

            return Response(result)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class SyncLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        logs = SyncLog.objects.filter(store=store)[:50]
        data = [
            {
                'id':               log.id,
                'log_type':         log.log_type,
                'started_at':       log.started_at,
                'duration_seconds': log.duration_seconds,
                'total':            log.total,
                'updated':          log.updated,
                'created':          log.created,
                'skipped':          log.skipped,
                'deleted':          log.deleted,
                'errors':           log.errors,
                'conflicts':        log.conflicts,
                'status':           log.status,
            }
            for log in logs
        ]
        return Response({'logs': data})