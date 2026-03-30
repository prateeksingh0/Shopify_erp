"""
Validates blog metafield values against their definitions.
Mirrors the same type rules used in ProductGrid.jsx frontend validation.
"""

import re
from datetime import datetime


def validate_metafield_value(ns_key, value, defn):
    """
    Validate a metafield value against its definition.
    Returns error string or None if valid.
    """
    if defn is None:
        return None

    v = str(value or '').strip()
    empty = not v or v.lower() in ('nan', 'none', '')
    mf_type = defn.get('type', 'single_line_text_field')
    choices  = defn.get('choices')
    min_val  = defn.get('min')
    max_val  = defn.get('max')

    if empty:
        return None  # optional unless required — Shopify enforces required at API level

    if choices:
        # list.single_line_text_field allows multiple choices
        if mf_type.startswith('list.'):
            try:
                import json
                items = json.loads(v) if v.startswith('[') else [x.strip() for x in v.split(',') if x.strip()]
            except Exception:
                items = [x.strip() for x in v.split(',') if x.strip()]
            invalid = [i for i in items if i not in choices]
            if invalid:
                return f"Invalid choice(s): {', '.join(invalid)}. Must be from: {', '.join(choices)}"
        else:
            if v not in choices:
                return f"Must be one of: {', '.join(choices)}"

    if mf_type in ('number_integer',):
        try:
            n = int(v)
            if min_val is not None and n < int(min_val):
                return f'Must be ≥ {min_val}'
            if max_val is not None and n > int(max_val):
                return f'Must be ≤ {max_val}'
        except ValueError:
            return 'Must be a whole number'

    elif mf_type in ('number_decimal', 'rating'):
        try:
            n = float(v)
            if min_val is not None and n < float(min_val):
                return f'Must be ≥ {min_val}'
            if max_val is not None and n > float(max_val):
                return f'Must be ≤ {max_val}'
        except ValueError:
            return 'Must be a valid number'

    elif mf_type == 'boolean':
        if v.lower() not in ('true', 'false'):
            return 'Must be true or false'

    elif mf_type in ('single_line_text_field', 'multi_line_text_field'):
        if max_val and len(v) > int(max_val):
            return f'Too long ({len(v)}/{max_val} chars)'
        if min_val and len(v) < int(min_val):
            return f'Too short (min {min_val} chars)'

    elif mf_type == 'url':
        if not re.match(r'^https?://', v, re.IGNORECASE):
            return 'Must be a valid URL (https://...)'

    elif mf_type == 'color':
        if not re.match(r'^#[0-9a-fA-F]{6}$', v):
            return 'Must be a valid hex color (e.g. #ff0000)'

    elif mf_type == 'date':
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            return 'Must be a valid date (YYYY-MM-DD)'

    elif mf_type == 'date_time':
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            return 'Must be a valid datetime (ISO 8601)'

    return None