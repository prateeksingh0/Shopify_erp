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
from products.client import graphql_request
from blogs.article_metafield_defs import fetch_and_store_article_metafield_defs, load_article_metafield_defs
from blogs.blog_metafield_defs import fetch_and_store_blog_metafield_defs, load_blog_metafield_defs
from blogs.blog_validator import validate_metafield_value
from blogs.fetch_blogs import fetch_blogs, fetch_and_store_blogs_list


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
            fetch_and_store_article_metafield_defs(get_store_base(request.user.id, store_name))
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
    """Returns all blogs from blogs_list.json — includes blogs with zero articles."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        path = os.path.join(get_store_base(request.user.id, store_name), 'blogs_list.json')
        if not os.path.exists(path):
            return Response({'blogs': []})

        with open(path, 'r', encoding='utf-8') as f:
            blogs = json.load(f)
        return Response({'blogs': blogs})



BLOG_CREATE_MUTATION = """
mutation blogCreate($blog: BlogCreateInput!) {
  blogCreate(blog: $blog) {
    blog {
      id
      title
      handle
    }
    userErrors { field message }
  }
}
"""

METAFIELDS_SET_MUTATION = """
mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { namespace key value }
    userErrors { field message }
  }
}
"""


class BlogMetafieldDefsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        store_dir = get_store_base(request.user.id, store_name)
        defs = load_blog_metafield_defs(store_dir)
        return Response(defs)

    def post(self, request, store_name):
        """Re-fetch blog metafield definitions from Shopify."""
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        store_dir = get_store_base(request.user.id, store_name)
        try:
            configure_shopify(store.domain, store.access_token, user_id=request.user.id)
            initialize_store_paths()
            defs = fetch_and_store_blog_metafield_defs(store_dir)
            return Response(defs)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class CreateBlogView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        data = request.data

        # Required field
        title = str(data.get('title', '')).strip()
        if not title:
            return Response({'error': 'Title is required'}, status=400)

        # Optional fields
        handle           = str(data.get('handle', '')).strip() or None
        comment_policy   = str(data.get('comment_policy', 'DISABLED')).strip().upper()
        seo_title        = str(data.get('seo_title', '')).strip()
        seo_description  = str(data.get('seo_description', '')).strip()
        metafields_input = data.get('metafields', {})  # {ns_key: value}

        # Validate comment policy
        # Map frontend values → Shopify API values
        policy_map = {
            'CLOSED':         'CLOSED',
            'MODERATED':      'MODERATED',
            'AUTO_PUBLISHED': 'AUTO_PUBLISHED',
            # legacy aliases in case old values come in
            'DISABLED':       'CLOSED',
            'MODERATE':       'MODERATED',
            'ALLOWED':        'AUTO_PUBLISHED',
        }
        if comment_policy not in policy_map:
            return Response({'error': f'Invalid comment policy. Must be one of: {", ".join(policy_map.keys())}'}, status=400)
        comment_policy = policy_map[comment_policy]

        # Validate metafield values against definitions
        store_dir = get_store_base(request.user.id, store_name)
        defs = load_blog_metafield_defs(store_dir)
        metafield_errors = {}
        for ns_key, value in (metafields_input or {}).items():
            defn = defs.get(ns_key)
            err = validate_metafield_value(ns_key, value, defn)
            if err:
                metafield_errors[ns_key] = err
        if metafield_errors:
            return Response({'error': 'Metafield validation failed', 'metafield_errors': metafield_errors}, status=400)

        try:
            configure_shopify(store.domain, store.access_token, user_id=request.user.id)
            initialize_store_paths()

            # Build blog input
            blog_input = {'title': title, 'commentPolicy': comment_policy}
            if handle:
                blog_input['handle'] = handle

            # Create the blog
            result = graphql_request(BLOG_CREATE_MUTATION, {'blog': blog_input})
            errs = ((result.get('data') or {}).get('blogCreate') or {}).get('userErrors') or []
            if errs:
                return Response({'error': str(errs)}, status=400)

            blog = ((result.get('data') or {}).get('blogCreate') or {}).get('blog', {})
            blog_id     = blog.get('id', '')
            blog_handle = blog.get('handle', '')

            # Set SEO metafields
            seo_mf = []
            if seo_title:
                seo_mf.append({'ownerId': blog_id, 'namespace': 'global', 'key': 'title_tag',
                                'value': seo_title, 'type': 'single_line_text_field'})
            if seo_description:
                seo_mf.append({'ownerId': blog_id, 'namespace': 'global', 'key': 'description_tag',
                                'value': seo_description, 'type': 'single_line_text_field'})
            if seo_mf:
                graphql_request(METAFIELDS_SET_MUTATION, {'metafields': seo_mf})

            # Set dynamic metafields
            mf_to_set = []
            for ns_key, value in (metafields_input or {}).items():
                v = str(value or '').strip()
                if not v or v.lower() in ('nan', 'none'):
                    continue
                namespace, key = ns_key.split('.', 1)
                defn    = defs.get(ns_key, {})
                mf_type = defn.get('type', 'single_line_text_field')
                mf_to_set.append({
                    'ownerId':   blog_id,
                    'namespace': namespace,
                    'key':       key,
                    'value':     v,
                    'type':      mf_type,
                })
            if mf_to_set:
                mf_result = graphql_request(METAFIELDS_SET_MUTATION, {'metafields': mf_to_set})
                mf_errs = ((mf_result.get('data') or {}).get('metafieldsSet') or {}).get('userErrors') or []
                if mf_errs:
                    print(f'[BLOG CREATE] Metafield errors: {mf_errs}')

            return Response({
                'blog_id':     blog_id,
                'title':       title,
                'handle':      blog_handle,
                'message':     f'Blog "{title}" created successfully',
            })

        except Exception as e:
            return Response({'error': str(e)}, status=500)
        
class ArticleMetafieldDefsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_name):
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        store_dir = get_store_base(request.user.id, store_name)
        defs = load_article_metafield_defs(store_dir)
        return Response(defs)

    def post(self, request, store_name):
        """Re-fetch article metafield definitions from Shopify."""
        store = get_store_or_404(store_name, request.user)
        if not store:
            return Response({'error': 'Store not found'}, status=404)

        store_dir = get_store_base(request.user.id, store_name)
        try:
            configure_shopify(store.domain, store.access_token, user_id=request.user.id)
            initialize_store_paths()
            defs = fetch_and_store_article_metafield_defs(store_dir)
            return Response(defs)
        except Exception as e:
            return Response({'error': str(e)}, status=500)