import math


def clean_value(value):
    """
    Sanitize a value before sending to Shopify GraphQL.

    - None → None
    - NaN → None
    - "" → None
    - 2.0 → "2"   (whole number floats stripped of .0)
    - 2.5 → 2.5   (real decimals kept as-is)
    """

    if value is None:
        return None

    if isinstance(value, float):

        # NaN → None
        if math.isnan(value):
            return None

        # Whole number float → strip .0
        # e.g. 2.0 → 2, so metafields get "2" not "2.0"
        if value == int(value):
            return int(value)

    if value == "":
        return None

    return value


def clean_string(value):
    """
    Like clean_value but always returns a string or None.
    Use for fields that Shopify expects as strings.

    - 2.0 → "2"
    - 2.5 → "2.5"
    - None/NaN/"" → None
    """

    cleaned = clean_value(value)

    if cleaned is None:
        return None

    # Float whole number already converted to int by clean_value
    return str(cleaned)


def clean_dict(data):
    """
    Recursively clean a dict — remove None/NaN/"" values.
    Used to strip empty fields from GraphQL mutation payloads.
    """

    cleaned = {}

    for k, v in data.items():

        if isinstance(v, dict):
            v = clean_dict(v)
            # Keep empty dicts — caller decides if needed
            cleaned[k] = v
            continue

        v = clean_value(v)

        if v is not None:
            cleaned[k] = v

    return cleaned