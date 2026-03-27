import io
import os

import requests
from PIL import Image

from products.client import graphql_request
import products.store_paths as store_paths


MAX_FILE_SIZE   = 20 * 1024 * 1024  # 20 MB
MAX_MEGAPIXELS  = 24_000_000        # just under Shopify's 25 MP hard limit


# ── Mutations ─────────────────────────────────────────────────────────────────

STAGED_UPLOADS_CREATE = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets {
      url
      resourceUrl
      parameters { name value }
    }
    userErrors { field message }
  }
}
"""

PRODUCT_CREATE_MEDIA = """
mutation productCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media {
      ... on MediaImage {
        id
        image { url }
      }
    }
    userErrors { field message }
  }
}
"""

PRODUCT_UPDATE_MEDIA = """
mutation productUpdateMedia($productId: ID!, $media: [UpdateMediaInput!]!) {
  productUpdateMedia(productId: $productId, media: $media) {
    media {
      ... on MediaImage {
        id
        alt
      }
    }
    userErrors { field message }
  }
}
"""

PRODUCT_DELETE_MEDIA = """
mutation productDeleteMedia($productId: ID!, $mediaIds: [ID!]!) {
  productDeleteMedia(productId: $productId, mediaIds: $mediaIds) {
    deletedMediaIds
    userErrors { field message }
  }
}
"""


# ── Internal helpers ──────────────────────────────────────────────────────────

# Supported image MIME types — defined once, used in _download_image
_MIME_MAP = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "gif":  "image/gif",
    "webp": "image/webp",
}


def _cache_image_locally(url):
    """
    Save image to image_cache/ just before it is deleted from Shopify.
    This ensures rollback can restore it even after the CDN file is gone.
    Skips silently if already cached or cache dir is not set.
    """
    cache_dir = store_paths.IMAGE_CACHE_DIR
    if not cache_dir:
        return
    clean_url  = url.split("?")[0]
    filename   = clean_url.split("/")[-1] or "image.jpg"
    local_path = os.path.join(cache_dir, filename)
    if os.path.exists(local_path):
        return   # already cached
    try:
        r = requests.get(clean_url, timeout=30)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(r.content)
        print(f"[IMAGE] Cached before delete: {filename}")
    except Exception as e:
        print(f"[IMAGE] Could not cache {filename}: {e}")


def _download_image(url):
    clean_url = url.split("?")[0]
    filename  = clean_url.split("/")[-1] or "image"

    print(f"[IMAGE] Downloading: {url}")

    def _fetch(verify_ssl):
        return requests.get(url, timeout=30, verify=verify_ssl)

    try:
        try:
            r = _fetch(verify_ssl=True)
        except requests.exceptions.SSLError:
            print(f"[IMAGE] SSL error — retrying without SSL verification")
            r = _fetch(verify_ssl=False)

        r.raise_for_status()

        content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        mime_map_reverse = {v: k for k, v in _MIME_MAP.items()}
        ext = mime_map_reverse.get(content_type, "jpg")

        if "." not in filename:
            filename = f"{filename}.{ext}"

        mime_type = content_type if content_type in _MIME_MAP.values() else "image/jpeg"

        size = len(r.content)
        if size > MAX_FILE_SIZE:
            raise Exception(f"[IMAGE] File too large: {size} bytes (max 20 MB)")

        return r.content, filename, mime_type

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            cache_dir  = store_paths.IMAGE_CACHE_DIR
            local_path = os.path.join(cache_dir, filename) if cache_dir else None
            if local_path and os.path.exists(local_path):
                print(f"[IMAGE] CDN 404 — restoring from local cache: {filename}")
                with open(local_path, "rb") as f:
                    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
                    mime_type = _MIME_MAP.get(ext, "image/jpeg")
                    return f.read(), filename, mime_type
        raise


def _resize_if_needed(image_bytes, filename, mime_type):
    """
    Proportionally scale down any image that exceeds 24 MP before upload.
    Shopify hard-rejects anything over 25 MP with a media processing error.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        pixels = w * h

        if pixels <= MAX_MEGAPIXELS:
            return image_bytes, filename, mime_type

        scale = (MAX_MEGAPIXELS / pixels) ** 0.5
        new_w, new_h = int(w * scale), int(h * scale)
        print(f"[IMAGE] Resizing {w}x{h} ({pixels // 1_000_000}MP) → {new_w}x{new_h}")

        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Convert RGBA/P to RGB for JPEG output
        fmt = "JPEG" if mime_type in ("image/jpeg", "image/jpg") else mime_type.split("/")[1].upper()
        if fmt == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format=fmt, quality=90)
        resized = buf.getvalue()
        print(f"[IMAGE] Resize complete. New size: {len(resized)} bytes")
        return resized, filename, mime_type

    except Exception as e:
        print(f"[IMAGE] Resize check failed ({e}) — uploading original")
        return image_bytes, filename, mime_type


def _staged_upload(image_bytes, filename, mime_type):
    """
    Execute Shopify staged upload:
      1. stagedUploadsCreate  → get signed URL + resourceUrl
      2. HTTP POST to signed URL → send file bytes (NOT GraphQL)
    Returns resourceUrl to pass to productCreateMedia.
    """
    file_size = str(len(image_bytes))

    variables = {
        "input": [{
            "resource":   "IMAGE",
            "filename":   filename,
            "mimeType":   mime_type,
            "fileSize":   file_size,
            "httpMethod": "POST",
        }]
    }

    result = graphql_request(STAGED_UPLOADS_CREATE, variables)
    errors = (
        (result.get("data") or {})
        .get("stagedUploadsCreate", {})
        .get("userErrors", [])
    )
    if errors:
        raise Exception(f"[IMAGE] stagedUploadsCreate errors: {errors}")

    targets = result["data"]["stagedUploadsCreate"]["stagedTargets"]
    if not targets:
        raise Exception("[IMAGE] stagedUploadsCreate returned no targets")

    target       = targets[0]
    upload_url   = target["url"]
    resource_url = target["resourceUrl"]
    params       = {p["name"]: p["value"] for p in target["parameters"]}

    # Upload file to the signed S3/GCS URL
    print(f"[IMAGE] Uploading to staged URL...")
    files = {"file": (filename, image_bytes, mime_type)}
    r = requests.post(upload_url, data=params, files=files, timeout=60)

    if r.status_code not in (200, 201, 204):
        raise Exception(f"[IMAGE] Staged upload HTTP error: {r.status_code} — {r.text[:200]}")

    print(f"[IMAGE] Staged upload OK. resourceUrl: {resource_url}")
    return resource_url


# ── Public API ────────────────────────────────────────────────────────────────

def upload_image(product_id, image_url, alt_text=""):
    """
    Download image_url → staged upload → productCreateMedia.
    Attaches a new image to the product.
    """
    print(f"[IMAGE] upload_image — product={product_id}")

    image_bytes, filename, mime_type = _download_image(image_url)
    image_bytes, filename, mime_type = _resize_if_needed(image_bytes, filename, mime_type)
    resource_url = _staged_upload(image_bytes, filename, mime_type)

    variables = {
        "productId": product_id,
        "media": [{
            "mediaContentType": "IMAGE",
            "originalSource":   resource_url,
            "alt":              alt_text or "",
        }],
    }

    result = graphql_request(PRODUCT_CREATE_MEDIA, variables)
    errors = (
        (result.get("data") or {})
        .get("productCreateMedia", {})
        .get("userErrors", [])
    )
    if errors:
        raise Exception(f"[IMAGE] productCreateMedia errors: {errors}")

    print(f"[IMAGE] upload_image SUCCESS")


def update_image_alt(product_id, media_id, alt_text):
    """
    Update the alt text of an existing media image — no re-upload needed.
    """
    print(f"[IMAGE] update_image_alt — product={product_id}, media={media_id}")

    variables = {
        "productId": product_id,
        "media": [{
            "id":  media_id,
            "alt": alt_text or "",
        }],
    }

    result = graphql_request(PRODUCT_UPDATE_MEDIA, variables)
    errors = (
        (result.get("data") or {})
        .get("productUpdateMedia", {})
        .get("userErrors", [])
    )
    if errors:
        raise Exception(f"[IMAGE] productUpdateMedia errors: {errors}")

    print(f"[IMAGE] update_image_alt SUCCESS")


def delete_image(product_id, media_id):
    """
    Delete a media image from a product.
    """
    print(f"[IMAGE] delete_image — product={product_id}, media={media_id}")

    variables = {
        "productId": product_id,
        "mediaIds":  [media_id],
    }

    result = graphql_request(PRODUCT_DELETE_MEDIA, variables)
    errors = (
        (result.get("data") or {})
        .get("productDeleteMedia", {})
        .get("userErrors", [])
    )
    if errors:
        raise Exception(f"[IMAGE] productDeleteMedia errors: {errors}")

    print(f"[IMAGE] delete_image SUCCESS")


def replace_image(product_id, old_media_id, new_url, alt_text=""):
    """
    Upload new image then delete old one.
    Upload first so the product is never left without any image.
    """
    print(f"[IMAGE] replace_image — product={product_id}, old={old_media_id}")

    upload_image(product_id, new_url, alt_text)

    if old_media_id:
        delete_image(product_id, old_media_id)

    print(f"[IMAGE] replace_image SUCCESS")
