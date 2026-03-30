import glob
import os
import json
import pandas as pd

from products.client import graphql_request
import products.store_paths as store_paths

# ── Mutations ────────────────────────────────────────────────────────────────

ARTICLE_UPDATE = """
mutation articleUpdate($article: ArticleUpdateInput!, $id: ID!) {
  articleUpdate(article: $article, id: $id) {
    article {
      id
      title
      updatedAt
    }
    userErrors { field message }
  }
}
"""

ARTICLE_CREATE = """
mutation articleCreate($article: ArticleCreateInput!) {
  articleCreate(article: $article) {
    article {
      id
      title
    }
    userErrors { field message }
  }
}
"""

ARTICLE_SET_METAFIELD = """
mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { key namespace value }
    userErrors { field message }
  }
}
"""

ARTICLE_DELETE = """
mutation articleDelete($id: ID!) {
  articleDelete(id: $id) {
    deletedArticleId
    userErrors { field message }
  }
}
"""


def normalize(value):
    if value is None:
        return ''
    s = str(value).strip()
    return '' if s.lower() in ('nan', 'none') else s


def load_snapshot(store_dir):
    snapshots_dir = os.path.join(store_dir, 'snapshots')

    # Try latest first
    latest_path = os.path.join(snapshots_dir, 'articles_latest_snapshot.json')
    if os.path.exists(latest_path):
        with open(latest_path, 'r', encoding='utf-8') as f:
            return json.load(f).get('data', {})

    # Fall back to most recent timestamped snapshot
    files = sorted(glob.glob(os.path.join(snapshots_dir, 'articles_snapshot_*.json')), reverse=True)
    if not files:
        return {}
    with open(files[0], 'r', encoding='utf-8') as f:
        return json.load(f).get('data', {})


def _sync_seo_metafields(article_id, row):
    seo_title = normalize(row.get('SEO Title', ''))
    seo_desc  = normalize(row.get('SEO Description', ''))

    if not seo_title and not seo_desc:
        return

    metafields = []
    if seo_title:
        metafields.append({
            'ownerId':   article_id,
            'namespace': 'global',
            'key':       'title_tag',
            'value':     seo_title,
            'type':      'single_line_text_field',
        })
    if seo_desc:
        metafields.append({
            'ownerId':   article_id,
            'namespace': 'global',
            'key':       'description_tag',
            'value':     seo_desc,
            'type':      'single_line_text_field',
        })

    result = graphql_request(ARTICLE_SET_METAFIELD, {'metafields': metafields})
    errs = ((result.get('data') or {}).get('metafieldsSet') or {}).get('userErrors') or []
    if errs:
        print(f"[BLOGS SYNC] SEO metafield errors: {errs}")


def run_article_updates(csv_path):
    print("\n[BLOGS SYNC] Starting article sync...\n")

    df = pd.read_csv(csv_path, dtype=str).fillna('')

    if 'Sync Status' not in df.columns:
        df['Sync Status'] = ''

    store_dir = os.path.dirname(os.path.dirname(os.path.abspath(csv_path)))
    snapshot  = load_snapshot(store_dir)
    print(f"[BLOGS SYNC] Snapshot loaded: {len(snapshot)} articles from {store_dir}")

    # Build Blog Title → Blog ID map from CSV (for new rows with no Blog ID)
    blog_title_to_id = {}
    for _, r in df.iterrows():
        bt = normalize(r.get('Blog Title', ''))
        bi = normalize(r.get('Blog ID', ''))
        if bt and bi:
            blog_title_to_id[bt] = bi

    total = updated = created = skipped = deleted = errors = 0

    for idx, row in df.iterrows():
        total += 1
        art_id  = normalize(row.get('Article ID', ''))
        blog_id = normalize(row.get('Blog ID', ''))
        delete  = normalize(row.get('Delete', '')).upper()

        try:
            # ── Delete ────────────────────────────────────────────────────
            if delete == 'YES':
                if not art_id:
                    df.at[idx, 'Sync Status'] = 'SKIPPED'
                    skipped += 1
                    continue
                result = graphql_request(ARTICLE_DELETE, {'id': art_id})
                errs   = ((result.get('data') or {}).get('articleDelete') or {}).get('userErrors') or []
                if errs:
                    raise Exception(f"userErrors: {errs}")
                df.at[idx, 'Sync Status'] = 'DELETED'
                deleted += 1
                continue

            # ── Create ────────────────────────────────────────────────────
            if not art_id:
                # Resolve Blog ID from Blog Title if missing
                if not blog_id:
                    blog_title = normalize(row.get('Blog Title', ''))
                    blog_id = blog_title_to_id.get(blog_title, '')

                if not blog_id:
                    print(f"[BLOGS SYNC] Row {idx}: no Blog ID or Blog Title — skipping")
                    df.at[idx, 'Sync Status'] = 'SKIPPED'
                    skipped += 1
                    continue

                input_data = _build_article_input(row, for_create=True)
                result = graphql_request(ARTICLE_CREATE, {
                    'article': {**input_data, 'blogId': blog_id}
                })
                errs = ((result.get('data') or {}).get('articleCreate') or {}).get('userErrors') or []
                if errs:
                    raise Exception(f"userErrors: {errs}")
                new_id = ((result.get('data') or {}).get('articleCreate') or {}).get('article', {}).get('id', '')
                df.at[idx, 'Article ID'] = new_id
                if new_id:
                    _sync_seo_metafields(new_id, row)
                df.at[idx, 'Sync Status'] = 'CREATED'
                created += 1
                continue

            # ── Update — delta detection ──────────────────────────────────
            snap = snapshot.get(art_id, {}).get('article', {})
            changes = _detect_changes(row, snap)

            if not changes:
                df.at[idx, 'Sync Status'] = 'SKIPPED'
                skipped += 1
                continue

            input_data = _build_article_input(row, for_create=False)
            result = graphql_request(ARTICLE_UPDATE, {
                'id':      art_id,
                'article': input_data,
            })
            errs = ((result.get('data') or {}).get('articleUpdate') or {}).get('userErrors') or []
            if errs:
                raise Exception(f"userErrors: {errs}")

            _sync_seo_metafields(art_id, row)

            df.at[idx, 'Sync Status'] = 'UPDATED'
            updated += 1

        except Exception as e:
            print(f"[BLOGS SYNC] Error row {idx}: {e}")
            df.at[idx, 'Sync Status'] = 'ERROR'
            errors += 1

    df.to_csv(csv_path, index=False)

    # Remove deleted rows from CSV
    df = df[df['Sync Status'] != 'DELETED'].reset_index(drop=True)
    df.to_csv(csv_path, index=False)

    print(f"[BLOGS SYNC] Done — updated={updated} created={created} skipped={skipped} deleted={deleted} errors={errors}")

    return {
        'total':    total,
        'updated':  updated,
        'created':  created,
        'skipped':  skipped,
        'deleted':  deleted,
        'errors':   errors,
        'conflicts': 0,
    }


def _build_article_input(row, for_create=False):
    from datetime import datetime, timezone
    input_data = {}

    title = normalize(row.get('Title', ''))
    if title: input_data['title'] = title

    body = normalize(row.get('Body (HTML)', ''))
    if body: input_data['body'] = body

    summary = normalize(row.get('Summary (HTML)', ''))
    if summary: input_data['summary'] = summary

    # author is required on create
    author = normalize(row.get('Author', ''))
    if not author and for_create:
        author = 'Shopify Admin'
    if author:
        input_data['author'] = {'name': author}

    tags_raw = normalize(row.get('Tags', ''))
    if tags_raw:
        input_data['tags'] = [t.strip() for t in tags_raw.split(',') if t.strip()]

    handle = normalize(row.get('Handle', ''))
    if handle: input_data['handle'] = handle

    image_url = normalize(row.get('Image URL', ''))
    image_alt = normalize(row.get('Image Alt', ''))
    if image_url:
        input_data['image'] = {'url': image_url, 'altText': image_alt}

    if for_create:
        status = normalize(row.get('Status', '')).lower()
        if status == 'published':
            input_data['publishedAt'] = datetime.now(timezone.utc).isoformat()
        elif status == 'draft':
            input_data['publishedAt'] = None

    return input_data


def _detect_changes(row, snap):
    changes = []

    fields = {
        'title':     ('Title',           lambda v: v),
        'body':      ('Body (HTML)',      lambda v: v),
        'summary':   ('Summary (HTML)',   lambda v: v),
        'author':    ('Author',          lambda v: v),
        'tags':      ('Tags',            lambda v: ', '.join(sorted(t.strip() for t in v.split(',') if t.strip()))),
        'seo_title': ('SEO Title',       lambda v: v),
        'seo_desc':  ('SEO Description', lambda v: v),
        'image_url': ('Image URL',       lambda v: v),
        'image_alt': ('Image Alt',       lambda v: v),
        'handle':    ('Handle',          lambda v: v),
    }

    for snap_key, (row_key, normalizer) in fields.items():
        snap_val = normalizer(normalize(str(snap.get(snap_key, ''))))
        row_val  = normalizer(normalize(str(row.get(row_key, ''))))
        if snap_val != row_val:
            changes.append(row_key)

    return changes