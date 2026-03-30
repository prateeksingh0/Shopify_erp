"""
Fetches and stores ARTICLE metafield definitions from Shopify.
Same pattern as blog_metafield_defs.py but for ARTICLE owner type.
Output: {store_dir}/article_metafield_defs.json
"""

import json
import os

from products.client import graphql_request

_DEFS_QUERY = """
query metafieldDefs($cursor: String) {
  metafieldDefinitions(ownerType: ARTICLE, first: 250, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      namespace
      key
      name
      type { name }
      validations { name value }
    }
  }
}
"""


def _parse_validations(validations):
    choices = min_val = max_val = regex = None
    for v in (validations or []):
        name  = v.get('name', '')
        value = v.get('value', '')
        if name == 'choices':
            try:
                parsed = json.loads(value)
                choices = [str(x).strip() for x in parsed if str(x).strip()] if isinstance(parsed, list) else [str(parsed).strip()]
            except Exception:
                choices = [x.strip() for x in str(value).split(',') if x.strip()]
        elif name == 'min':
            min_val = value
        elif name == 'max':
            max_val = value
        elif name == 'regex':
            regex = value
    return choices, min_val, max_val, regex


def fetch_and_store_article_metafield_defs(store_dir):
    print('[ARTICLE METAFIELD DEFS] Fetching article definitions...')
    all_defs = {}
    cursor = None

    while True:
        variables = {}
        if cursor:
            variables['cursor'] = cursor
        result = graphql_request(_DEFS_QUERY, variables)
        data   = (result.get('data') or {}).get('metafieldDefinitions', {})

        for node in (data.get('nodes') or []):
            ns_key = f"{node['namespace']}.{node['key']}"
            choices, min_val, max_val, regex = _parse_validations(node.get('validations'))
            all_defs[ns_key] = {
                'name':    node.get('name', ''),
                'type':    (node.get('type') or {}).get('name', 'single_line_text_field'),
                'choices': choices,
                'min':     min_val,
                'max':     max_val,
                'regex':   regex,
            }

        page_info = data.get('pageInfo', {})
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')

    path = os.path.join(store_dir, 'article_metafield_defs.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(all_defs, f, indent=2, ensure_ascii=False)

    print(f'[ARTICLE METAFIELD DEFS] {len(all_defs)} definition(s) saved to {path}')
    return all_defs


def load_article_metafield_defs(store_dir):
    path = os.path.join(store_dir, 'article_metafield_defs.json')
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)