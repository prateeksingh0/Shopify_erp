import os
import json
import time
import pandas as pd

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from stores.models import Store
from products.config import configure_shopify
from products.store_paths import initialize_store_paths
from blogs.fetch_blogs import fetch_blogs
from blogs.csv_writer import save_articles_csv
from blogs.snapshot_writer import save_articles_snapshot
from blogs.updater import run_article_updates
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


class FetchArticlesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        start = time.time()
        try:
            configure_shopify(store.domain, store.access_token, user_id=request.user.id)
            initialize_store_paths()
            rows, snapshot = with_auto_refresh(
                store,
                lambda token: configure_shopify(store.domain, token, user_id=request.user.id),
                lambda: fetch_blogs()
            )
            save_articles_csv(rows)
            save_articles_snapshot(snapshot)
        except Exception as e:
            duration = int(time.time() - start)
            SyncLog.objects.create(
                store=store, log_type='fetch',
                duration_seconds=duration, status='error'
            )
            return Response({'error': str(e)}, status=500)

        duration = int(time.time() - start)
        SyncLog.objects.create(
            store=store, log_type='fetch',
            duration_seconds=duration,
            total=len(rows), status='success'
        )
        return Response({'message': f'Fetched {len(rows)} articles'})


class ArticlesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        csv_path = os.path.join(get_store_base(request.user.id, store_name), 'data', 'articles_master.csv')

        if not os.path.exists(csv_path):
            return Response({'error': 'No data found. Run fetch first.'}, status=404)

        df = pd.read_csv(csv_path, dtype=str).fillna('')
        return Response(df.to_dict(orient='records'))


class SaveArticlesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        csv_path = os.path.join(get_store_base(request.user.id, store_name), 'data', 'articles_master.csv')

        if not os.path.exists(csv_path):
            return Response({'error': 'No data found. Run fetch first.'}, status=404)

        rows = request.data.get('rows')
        if not rows:
            return Response({'error': 'No rows provided'}, status=400)

        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)
        return Response({'message': f'{len(rows)} rows saved'})


class SyncArticlesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        csv_path = os.path.join(get_store_base(request.user.id, store_name), 'data', 'articles_master.csv')

        if not os.path.exists(csv_path):
            return Response({'error': 'No data found. Run fetch first.'}, status=404)

        start = time.time()
        try:
            configure_shopify(store.domain, store.access_token, user_id=request.user.id)
            initialize_store_paths()
            result = with_auto_refresh(
                store,
                lambda token: configure_shopify(store.domain, token, user_id=request.user.id),
                lambda: run_article_updates(csv_path)
            )
        except Exception as e:
            duration = int(time.time() - start)
            SyncLog.objects.create(
                store=store, log_type='sync',
                duration_seconds=duration, status='error'
            )
            return Response({'error': str(e)}, status=500)

        duration = int(time.time() - start)
        SyncLog.objects.create(
            store=store, log_type='sync',
            duration_seconds=duration,
            total=result.get('total', 0),
            updated=result.get('updated', 0),
            created=result.get('created', 0),
            skipped=result.get('skipped', 0),
            deleted=result.get('deleted', 0),
            errors=result.get('errors', 0),
            status='success',
        )
        return Response(result)


class BlogListView(APIView):
    """Returns distinct blogs from the articles CSV — dynamic, no hardcoding."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        csv_path = os.path.join(get_store_base(request.user.id, store_name), 'data', 'articles_master.csv')

        if not os.path.exists(csv_path):
            return Response({'blogs': []})

        df = pd.read_csv(csv_path, dtype=str).fillna('')
        blogs = (
            df[['Blog ID', 'Blog Title', 'Blog Handle']]
            .drop_duplicates()
            .to_dict(orient='records')
        )
        return Response({'blogs': blogs})