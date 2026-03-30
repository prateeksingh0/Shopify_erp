import os
import json

from products.client import graphql_request
import products.store_paths as store_paths

ARTICLES_LIMIT = 250
BLOGS_LIMIT    = 50

BLOGS_QUERY = """
query fetchBlogs($cursor: String) {
  blogs(first: %d, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        articles(first: %d) {
          edges {
            node {
              id
              title
              handle
              body
              summary
              author { name }
              tags
              publishedAt
              createdAt
              updatedAt
              image { url altText }
              metafields(first: 10) {
                edges {
                  node {
                    namespace
                    key
                    value
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
""" % (BLOGS_LIMIT, ARTICLES_LIMIT)


def fetch_blogs():
    """
    Fetch all blogs and their articles from Shopify.
    Returns (rows, snapshot) — rows is a flat list of article dicts,
    snapshot is a dict keyed by article ID for delta detection.
    """
    print("[BLOGS] Fetching blogs and articles...")

    rows     = []
    snapshot = {}
    cursor   = None

    while True:
        variables = {'cursor': cursor} if cursor else {}
        result    = graphql_request(BLOGS_QUERY, variables)
        blogs_data = (result.get('data') or {}).get('blogs', {})
        edges      = blogs_data.get('edges') or []
        page_info  = blogs_data.get('pageInfo', {})

        for blog_edge in edges:
            blog = blog_edge['node']
            blog_id    = blog['id']
            blog_title = blog['title']
            blog_handle = blog['handle']

            for art_edge in (blog.get('articles') or {}).get('edges') or []:
                article = art_edge['node']
                art_id  = article['id']

                author     = (article.get('author') or {}).get('name', '')
                tags_raw   = article.get('tags') or []
                tags       = ', '.join(tags_raw) if isinstance(tags_raw, list) else str(tags_raw)
                image_url  = (article.get('image') or {}).get('url', '')
                image_alt  = (article.get('image') or {}).get('altText', '')
                seo_title  = (article.get('seo') or {}).get('title', '')
                seo_desc   = (article.get('seo') or {}).get('description', '')

                # Determine status dynamically from publishedAt
                status = 'published' if article.get('publishedAt') else 'draft'
                # Extract metafields dynamically
                metafields = {}
                for mf_edge in (article.get('metafields') or {}).get('edges') or []:
                    mf = mf_edge['node']
                    key = f"{mf['namespace']}.{mf['key']}"
                    metafields[key] = mf['value']

                # SEO lives in global namespace
                seo_title = metafields.get('global.title_tag', '')
                seo_desc  = metafields.get('global.description_tag', '')

                row = {
                    'Article ID':        art_id,
                    'Blog ID':           blog_id,
                    'Blog Title':        blog_title,
                    'Blog Handle':       blog_handle,
                    'Title':             article.get('title', ''),
                    'Handle':            article.get('handle', ''),
                    'Body (HTML)':       article.get('body', ''),
                    'Summary (HTML)':    article.get('summary', ''),
                    'Author':            author,
                    'Tags':              tags,
                    'SEO Title':         seo_title,
                    'SEO Description':   seo_desc,
                    'Status':            status,
                    'Published At':      article.get('publishedAt', ''),
                    'Created At':        article.get('createdAt', ''),
                    'Updated At':        article.get('updatedAt', ''),
                    'Image URL':         image_url,
                    'Image Alt':         image_alt,
                    'Delete':            '',
                    'Sync Status':       '',
                }

                rows.append(row)

                # Snapshot for delta detection
                snapshot[art_id] = {
                    'article': {
                        'id':          art_id,
                        'blog_id':     blog_id,
                        'title':       row['Title'],
                        'handle':      row['Handle'],
                        'body':        row['Body (HTML)'],
                        'summary':     row['Summary (HTML)'],
                        'author':      author,
                        'tags':        tags,
                        'status':      status,
                        'publishedAt': article.get('publishedAt', ''),
                        'seo_title':   seo_title,
                        'seo_desc':    seo_desc,
                        'image_url':   image_url,
                        'image_alt':   image_alt,
                    }
                }

        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')

    print(f"[BLOGS] Fetched {len(rows)} articles across blogs")
    return rows, snapshot