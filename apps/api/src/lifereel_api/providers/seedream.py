"""Single-image Seedream restoration with an aspect-preserving 1080p pixel budget."""

import base64
import math
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.providers.siliconflow import (
    MAX_BYTES,
    RedrawOutput,
    image_mime,
    validate_download_url,
)

MODEL = "doubao-seedream-5-0-pro-260628"
PIXELS = 1920 * 1080


def output_size(content: bytes) -> str:
    try:
        with Image.open(BytesIO(content)) as source:
            width, height = source.size
            if (
                min(width, height) <= 14 or width * height > 36_000_000
                or not 1 / 16 <= width / height <= 16
            ):
                raise ValueError("Unsupported source dimensions")
            source.verify()
        with Image.open(BytesIO(content)) as source:
            if source.getexif().get(274) in {5, 6, 7, 8}:
                width, height = height, width
        scale = math.sqrt(PIXELS / (width * height))
        return f"{round(width * scale / 2) * 2}x{round(height * scale / 2) * 2}"
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID) from None


def edit(
    content: bytes, mime_type: str, *, prompt: str, size: str,
    client: httpx.Client | None = None,
) -> RedrawOutput:
    settings = get_settings()
    if not settings.volcengine_api_key:
        raise ApiError(503, ErrorCode.PHOTO_RESTORATION_NOT_CONFIGURED)
    if size != output_size(content):
        raise ApiError(422, ErrorCode.PHOTO_RESTORATION_SOURCE_INVALID)
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(180, connect=20), trust_env=False)
    try:
        response = client.post(
            settings.volcengine_api_base_url.rstrip("/") + "/images/generations",
            headers={"Authorization": "Bearer " + settings.volcengine_api_key},
            # Pro returns one image; omit unsupported count/grouping and all optional defaults.
            json={
                "model": MODEL, "prompt": prompt, "size": size,
                "image": f"data:{mime_type};base64," + base64.b64encode(content).decode(),
            },
        )
        if response.status_code != 200:
            code = ErrorCode.PHOTO_RESTORATION_FAILED
            if response.status_code in {400, 422}:
                code = ErrorCode.PHOTO_RESTORATION_REJECTED
            raise ApiError(502, code)
        data = response.json()["data"]
        if not isinstance(data, list) or len(data) != 1:
            raise ValueError("Expected one output")
        if data[0].get("error"):
            raise ApiError(502, ErrorCode.PHOTO_RESTORATION_REJECTED)
        url = validate_download_url(data[0]["url"])
        for _ in range(4):
            # Authorization is attached only to the generation request, never the image fetch.
            with client.stream("GET", url, follow_redirects=False) as download:
                if download.is_redirect:
                    url = validate_download_url(str(url.join(download.headers["location"])))
                    continue
                download.raise_for_status()
                output = bytearray()
                for chunk in download.iter_bytes():
                    output.extend(chunk)
                    if len(output) > MAX_BYTES:
                        raise ValueError("Image too large")
                mime = image_mime(output)
                if not mime:
                    raise ValueError("Invalid image")
                return RedrawOutput(bytes(output), mime, response.headers.get("x-request-id"))
        raise ValueError("Too many redirects")
    except httpx.TimeoutException:
        raise ApiError(502, ErrorCode.PHOTO_RESTORATION_UNCERTAIN) from None
    except (httpx.HTTPError, OSError):
        raise ApiError(502, ErrorCode.PHOTO_RESTORATION_FAILED) from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ApiError(502, ErrorCode.PHOTO_RESTORATION_RESULT_INVALID) from None
    finally:
        if own_client:
            client.close()
