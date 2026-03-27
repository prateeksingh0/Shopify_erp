import json
import os

import pandas as pd
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from stores.models import Store
from products.config import configure_shopify
from products.store_paths import initialize_store_paths
from products.fetch import main as run_fetch
import products.store_paths as store_paths


def get_store_or_404(store_name):
    try:
        return Store.objects.get(store_name=store_name)
    except Store.DoesNotExist:
        return None


class FetchProductsView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        try:
            configure_shopify(store.domain, store.access_token)
            initialize_store_paths()
            run_fetch()
            return Response({'message': 'Fetch completed successfully'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class ProductsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        csv_path = os.path.join(base, store_name, 'data', 'products_master.csv')

        if not os.path.exists(csv_path):
            return Response(
                {'error': f'No data found for store {store_name}. Run fetch first.'},
                status=404
            )

        df = pd.read_csv(csv_path, dtype=str).fillna('')
        rows = df.to_dict(orient='records')
        return Response(rows)


class LocationsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        try:
            configure_shopify(store.domain, store.access_token)
            initialize_store_paths()
            from products.locations import fetch_locations
            id_to_name, name_to_id = fetch_locations()
            return Response({'locations': name_to_id})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class CollectionHandlesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        snapshot_path = os.path.join(base, store_name, 'snapshots', 'latest_snapshot.json')

        if not os.path.exists(snapshot_path):
            return Response({'handles': []})

        with open(snapshot_path, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)

        data = snapshot.get('data', snapshot)
        handles = set()
        for product_data in data.values():
            raw = product_data.get('collection_handles', '')
            for h in str(raw).split(','):
                h = h.strip().lower()
                if h and h not in ('nan', 'none', ''):
                    handles.add(h)

        return Response({'handles': sorted(handles)})


class MetafieldDefsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        path = os.path.join(base, store_name, 'metafield_defs.json')

        if not os.path.exists(path):
            return Response({'product': {}, 'variant': {}})

        with open(path, 'r', encoding='utf-8') as f:
            return Response(json.load(f))


class MetafieldOwnersView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        path = os.path.join(base, store_name, 'metafield_owners.json')

        if not os.path.exists(path):
            return Response({})

        with open(path, 'r', encoding='utf-8') as f:
            return Response(json.load(f))


class FieldSchemaView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        path = os.path.join(base, store_name, 'field_schema.json')

        if not os.path.exists(path):
            return Response({'enums': {}, 'validations': {}})

        with open(path, 'r', encoding='utf-8') as f:
            return Response(json.load(f))
        
class SaveProductsView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, store_name):
        store = get_store_or_404(store_name)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        base = getattr(settings, 'SHOPIFY_DATA_ROOT', '')
        csv_path = os.path.join(base, store_name, 'data', 'products_master.csv')

        if not os.path.exists(csv_path):
            return Response({'error': 'No data found. Run fetch first.'}, status=404)

        rows = request.data.get('rows')
        if not rows:
            return Response({'error': 'No rows provided'}, status=400)

        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)
        return Response({'message': f'{len(rows)} rows saved'})