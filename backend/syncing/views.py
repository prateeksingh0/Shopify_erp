import os

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from stores.models import Store
from products.config import configure_shopify
from products.store_paths import initialize_store_paths
from products.locations import fetch_locations
from syncing.updater import run_updates


def get_store_or_404(store_name):
    try:
        return Store.objects.get(store_name=store_name)
    except Store.DoesNotExist:
        return None


class SyncView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, store_name):
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

        try:
            configure_shopify(store.domain, store.access_token)
            initialize_store_paths()
            _, location_map = fetch_locations()
            result = run_updates(csv_path, location_map)
            return Response(result)
        except Exception as e:
            return Response({'error': str(e)}, status=500)