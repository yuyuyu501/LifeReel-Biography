"""Portrait-preserving redraw; no video-provider authorization is inferred."""

import base64
import ipaddress
import socket
from dataclasses import dataclass

import httpx

from lifereel_api.core.config import get_settings
from lifereel_api.core.errors import ApiError, ErrorCode

MODEL = "Qwen/Qwen-Image-Edit-2509"
PROMPT_VERSION = "portrait-redraw-v3"
PROMPT = (
    "对照片进行轻度彩色手绘转描，以保留人物辨识特征为首要目标，人物相似度优先于风格化。"
    "严格依据原照片，保留每个人的头脸比例、脸型、五官的相对位置和大小、眼距、眼形、"
    "鼻形、嘴形、下颌轮廓、发际线和发型；保留原有年龄感、肤色，以及照片中可见的皱纹、"
    "痣、眼镜等辨识细节，不添加原图中不存在的特征。"
    "只将摄影质感轻度转为细腻的手绘笔触和自然柔和的明暗，保留面部结构与必要细节，"
    "轮廓自然细致，避免粗重描边、大片平涂和过度简化五官。"
    "不要卡通化、夸张五官、放大眼睛、缩小鼻子、瘦脸、美颜磨皮或幼态化；"
    "不要改变原有表情、视线方向和眼睛开闭状态。"
    "保留原有服装、姿势、人物关系、背景和构图，保持彩色，不改成黑白素描，不额外添加文字。"
)
MAX_BYTES = 10 * 1024 * 1024
MIMES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def image_mime(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass
class RedrawOutput:
    content: bytes
    mime_type: str
    trace_id: str | None = None


def validate_download_url(value: str) -> httpx.URL:
    url = httpx.URL(value)
    if url.scheme != "https" or not url.host or url.port not in {None, 443} or url.userinfo:
        raise ValueError("Invalid image URL")
    addresses = socket.getaddrinfo(url.host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Non-public image URL")
    return url


def redraw(content: bytes, mime_type: str, *, client: httpx.Client | None = None) -> RedrawOutput:
    settings = get_settings()
    if settings.photo_redraw_provider == "mock" and settings.is_development:
        # A synthetic PNG is only used by explicitly configured development/test runs.
        return RedrawOutput(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8A"
            "AwMCAO+aD1sAAAAASUVORK5CYII="
        ), "image/png", "mock")
    if settings.photo_redraw_provider != "siliconflow" or not settings.siliconflow_api_key:
        raise ApiError(503, ErrorCode.PHOTO_REDRAW_NOT_CONFIGURED)
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(180, connect=20), trust_env=False)
    try:
        response = client.post(
            "https://api.siliconflow.cn/v1/images/generations",
            headers={
                "Authorization": "Bearer " + settings.siliconflow_api_key,
                "X-Enable-Watermark": "1",
            },
            json={
                "model": MODEL, "prompt": PROMPT, "num_inference_steps": 20,
                "seed": 20260916,
                "image": f"data:{mime_type};base64," + base64.b64encode(content).decode(),
            },
        )
        if response.status_code != 200:
            # Do not persist provider messages: they can contain media URLs or request data.
            code = ErrorCode.PHOTO_REDRAW_FAILED
            if response.status_code in {400, 422}:
                code = ErrorCode.PHOTO_REDRAW_REJECTED
            raise ApiError(502, code)
        result = response.json()
        url = validate_download_url(result["images"][0]["url"])
        # Fetch without API credentials; validate each redirect before following it.
        for _ in range(4):
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
                result_mime = image_mime(output)
                if not result_mime:
                    raise ValueError("Invalid image content")
                return RedrawOutput(
                    bytes(output), result_mime, response.headers.get("x-siliconcloud-trace-id"),
                )
        raise ValueError("Too many redirects")
    except httpx.TimeoutException:
        raise ApiError(502, ErrorCode.PHOTO_REDRAW_UNCERTAIN) from None
    except (httpx.HTTPError, OSError):
        raise ApiError(502, ErrorCode.PHOTO_REDRAW_FAILED) from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ApiError(502, ErrorCode.PHOTO_REDRAW_RESULT_INVALID) from None
    finally:
        if own_client:
            client.close()
