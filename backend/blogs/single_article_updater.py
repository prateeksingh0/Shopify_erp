"""
Syncs a single article to Shopify.
Mirrors updater.py logic but for one row only — used by ArticleModal per-article sync.
"""
import os
import json
import glob
import pandas as pd

from blogs.updater import (
    load_snapshot, normalize, _build_article_input, _detect_changes,
    _sync_seo_metafields, _sync_article_metafields,
    ARTICLE_CREATE, ARTICLE_UPDATE, ARTICLE_DELETE,
)
from products.client import graphql_request
import products.store_paths as store_paths
from blogs.article_metafield_defs import load_article_metafield_defs


def sync_single_article(article_id, row, csv_path):
    """
    Sync one article row to Shopify and update the CSV.
    article_id: the Shopify article GID, or '__new__' for creates.
    row: dict of article fields.
    """
    store_dir = os.path.dirname(os.path.dirname(os.path.abspath(csv_path)))
    snapshot  = load_snapshot(store_dir)

    # Load CSV to update it after sync
    df = pd.read_csv(csv_path, dtype=str).fillna('') if os.path.exists(csv_path) else pd.DataFrame()

    delete = normalize(row.get('Delete', '')).upper()
    is_new = not article_id or article_id == '__new__' or not normalize(article_id)

    # ── Delete ────────────────────────────────────────────────────────────
    if delete == 'YES':
        if is_new:
            return {'status': 'SKIPPED', 'message': 'New article — nothing to delete'}
        result = graphql_request(ARTICLE_DELETE, {'id': article_id})
        errs = ((result.get('data') or {}).get('articleDelete') or {}).get('userErrors') or []
        if errs:
            raise Exception(f"Delete failed: {errs}")
        # Remove from CSV
        if not df.empty and 'Article ID' in df.columns:
            df = df[df['Article ID'] != article_id].reset_index(drop=True)
            df.to_csv(csv_path, index=False)
        return {'status': 'DELETED', 'article_id': article_id}

    # ── Create ────────────────────────────────────────────────────────────
    if is_new:
        blog_id = normalize(row.get('Blog ID', ''))
        if not blog_id:
            # Try to resolve from blog title via CSV
            if not df.empty and 'Blog Title' in df.columns and 'Blog ID' in df.columns:
                blog_title = normalize(row.get('Blog Title', ''))
                match = df[df['Blog Title'] == blog_title]['Blog ID']
                blog_id = match.iloc[0] if not match.empty else ''
        if not blog_id:
            raise Exception('Cannot create article — Blog ID could not be resolved')

        input_data = _build_article_input(row, for_create=True)
        result = graphql_request(ARTICLE_CREATE, {'article': {**input_data, 'blogId': blog_id}})
        errs = ((result.get('data') or {}).get('articleCreate') or {}).get('userErrors') or []
        if errs:
            raise Exception(f"Create failed: {errs}")

        new_id = ((result.get('data') or {}).get('articleCreate') or {}).get('article', {}).get('id', '')
        if new_id:
            seo_title = normalize(row.get('SEO Title', ''))
            seo_desc  = normalize(row.get('SEO Description', ''))
            if seo_title or seo_desc:
                _sync_seo_metafields(new_id, row)
            defs = load_article_metafield_defs(store_dir)
            if any(normalize(row.get(k, '')) for k in defs):
                _sync_article_metafields(new_id, row, store_dir)

        # Append to CSV
        updated_row = {**row, 'Article ID': new_id, 'Sync Status': 'CREATED'}
        if not df.empty:
            df = pd.concat([df, pd.DataFrame([updated_row])], ignore_index=True)
        else:
            df = pd.DataFrame([updated_row])
        df.to_csv(csv_path, index=False)
        return {'status': 'CREATED', 'article_id': new_id, 'row': updated_row}

    # ── Update ────────────────────────────────────────────────────────────
    snap = snapshot.get(article_id, {}).get('article', {})

    # Blog move?
    snap_blog_id = normalize(str(snap.get('blog_id', '')))
    row_blog_id  = normalize(str(row.get('Blog ID', '')))
    if snap_blog_id and row_blog_id and snap_blog_id != row_blog_id:
        # Recreate in new blog first, then delete old
        input_data = _build_article_input(row, for_create=True)
        create_result = graphql_request(ARTICLE_CREATE, {'article': {**input_data, 'blogId': row_blog_id}})
        create_errs = ((create_result.get('data') or {}).get('articleCreate') or {}).get('userErrors') or []
        if create_errs:
            raise Exception(f"Move (recreate) failed: {create_errs}")
        new_id = ((create_result.get('data') or {}).get('articleCreate') or {}).get('article', {}).get('id', '')
        graphql_request(ARTICLE_DELETE, {'id': article_id})
        if new_id:
            seo_title = normalize(row.get('SEO Title', ''))
            seo_desc  = normalize(row.get('SEO Description', ''))
            if seo_title or seo_desc:
                _sync_seo_metafields(new_id, row)
            defs = load_article_metafield_defs(store_dir)
            if any(normalize(row.get(k, '')) for k in defs):
                _sync_article_metafields(new_id, row, store_dir)

        updated_row = {**row, 'Article ID': new_id, 'Sync Status': 'UPDATED'}
        _update_csv_row(df, csv_path, article_id, updated_row)
        return {'status': 'UPDATED', 'article_id': new_id, 'row': updated_row}

    # Regular update — check for changes
    changes = _detect_changes(row, snap)
    if not changes:
        return {'status': 'SKIPPED', 'message': 'No changes detected'}

    input_data = _build_article_input(row, for_create=False)
    result = graphql_request(ARTICLE_UPDATE, {'id': article_id, 'article': input_data})
    errs = ((result.get('data') or {}).get('articleUpdate') or {}).get('userErrors') or []
    if errs:
        raise Exception(f"Update failed: {errs}")

    _sync_seo_metafields(article_id, row)
    _sync_article_metafields(article_id, row, store_dir)

    seo_title      = normalize(row.get('SEO Title', ''))
    seo_desc       = normalize(row.get('SEO Description', ''))
    snap_seo_title = normalize(str(snap.get('seo_title', '')))
    snap_seo_desc  = normalize(str(snap.get('seo_desc', '')))
    if seo_title != snap_seo_title or seo_desc != snap_seo_desc:
        _sync_seo_metafields(article_id, row)

    defs = load_article_metafield_defs(store_dir)
    if any(normalize(row.get(k, '')) != normalize(str(snap.get(k, ''))) for k in defs):
        _sync_article_metafields(article_id, row, store_dir)

    updated_row = {**row, 'Sync Status': 'UPDATED'}

    
    _update_csv_row(df, csv_path, article_id, updated_row)
    return {'status': 'UPDATED', 'article_id': article_id, 'row': updated_row}


def _update_csv_row(df, csv_path, article_id, updated_row):
    if df.empty or 'Article ID' not in df.columns:
        return
    idx = df.index[df['Article ID'] == article_id].tolist()
    if idx:
        for k, v in updated_row.items():
            if k in df.columns:
                df.at[idx[0], k] = v
    else:
        df = pd.concat([df, pd.DataFrame([updated_row])], ignore_index=True)
    df.to_csv(csv_path, index=False)