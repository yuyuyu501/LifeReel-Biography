"""Bounded public-history search; no names or interview text leave this adapter."""

import re
import time
from datetime import UTC, datetime
from functools import lru_cache
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

EVENTS = {
    "college_exam": ("恢复高考", ("高考",)),
    "rural_reform": ("家庭联产承包责任制", ("田地", "承包", "分田", "责任制")),
    "reform_opening": ("改革开放", ("改革", "开放")),
    "migration": ("农民工进城务工", ("打工", "务工", "进城")),
    "education": ("义务教育", ("上学", "学校", "教育")),
    "industry": ("国有企业改革", ("下岗", "国企", "工厂")),
    "flood": ("洪涝灾害", ("洪水", "洪灾", "水灾")),
    "earthquake": ("地震", ("地震",)),
    "railway": ("铁路建设", ("铁路", "火车")),
}
REGIONS = (
    "全国",
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "内蒙古",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "广西",
    "海南",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
    "台湾",
)


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal[
        "college_exam",
        "rural_reform",
        "reform_opening",
        "migration",
        "education",
        "industry",
        "flood",
        "earthquake",
        "railway",
    ]
    region: str = Field(max_length=10)
    year_start: int = Field(ge=1900, le=2030, strict=True)
    year_end: int = Field(ge=1900, le=2030, strict=True)

    @model_validator(mode="after")
    def valid_range(self):
        if self.region not in REGIONS or not 0 <= self.year_end - self.year_start <= 15:
            raise ValueError("invalid_public_history_scope")
        return self


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ignored = 0
        self.parts = []
        self.encoding = None

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            attributes = dict(attrs)
            encoding = attributes.get("charset")
            if not encoding:
                match = re.search(r"charset\s*=\s*([\w-]+)", attributes.get("content", ""), re.I)
                encoding = match[1] if match else None
            if encoding:
                self.encoding = encoding
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored and data.strip():
            self.parts.append(data.strip())


def trusted_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return bool(
        parsed.scheme == "https"
        and parsed.port in {None, 443}
        and not parsed.username
        and not parsed.password
        and (
            host.endswith(".gov.cn") or host.endswith(".edu.cn")
            or host.endswith(".people.com.cn") or host.endswith(".news.cn")
        )
    )


def _fetch(url, *, params=None, remaining=6):
    timeout = httpx.Timeout(min(3, remaining), connect=min(2, remaining))
    with httpx.stream(
        "GET",
        url,
        params=params,
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": "LifeReel-History/1.0"},
    ) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("history_redirect_not_followed")
        chunks, size = [], 0
        deadline = time.monotonic() + remaining
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > 600_000 or time.monotonic() > deadline:
                raise ValueError("history_page_limit")
            chunks.append(chunk)
        body = b"".join(chunks)
        metadata = PageText()
        metadata.feed(body[:8192].decode("ascii", "ignore"))
        encoding = response.charset_encoding or metadata.encoding or "utf-8"
        try:
            return body.decode(encoding, "replace")
        except LookupError:
            return body.decode("utf-8", "replace")


@lru_cache(maxsize=128)
def _lookup(event, region, year_start, year_end, hour):
    started = time.monotonic()
    year = str(year_start) if year_start == year_end else f"{year_start}至{year_end}"
    query = f'"{EVENTS[event][0]}" {year}年 {region if region != "全国" else ""}'.strip()
    result = {
        "status": "no_results",
        "query": query,
        "region": region,
        "year_start": year_start,
        "year_end": year_end,
        "sources": [],
        "accessed_at": datetime.now(UTC).isoformat(),
        "limits": "公开页面摘录可能不完整；公共历史不能证明个人亲历，查无结果不能否定回忆。",
    }
    try:
        seen = set()
        for search_query in (query, f'"{EVENTS[event][0]}"'):
            remaining = 8 - (time.monotonic() - started)
            if remaining <= 0.5:
                break
            rss = ElementTree.fromstring(_fetch(
                "https://cn.bing.com/search",
                params={"q": search_query, "format": "rss", "setlang": "zh-hans"},
                remaining=remaining,
            ))
            for item in rss.findall("./channel/item")[:10]:
                url = item.findtext("link", "")
                if not trusted_url(url) or url in seen:
                    continue
                seen.add(url)
                remaining = 8 - (time.monotonic() - started)
                if remaining <= 0.5:
                    break
                try:
                    parser = PageText()
                    parser.feed(_fetch(url, remaining=remaining))
                    full_text = " ".join(parser.parts)
                    excerpts = [
                        full_text[max(0, hit.start() - 300):hit.start() + 1500]
                        for keyword in EVENTS[event][1]
                        for hit in re.finditer(re.escape(keyword), full_text)
                    ]
                    # Only the fetched page and the requested period support evidence.
                    excerpt = next((part for part in excerpts if any(
                        str(y) in part for y in range(year_start, year_end + 1)
                    )), None)
                    if not excerpt:
                        continue
                    result["sources"].append({
                        "id": f"history:{len(result['sources']) + 1}",
                        "title": item.findtext("title", "公开历史资料")[:200],
                        "url": url, "excerpt": excerpt, "region": region,
                        "year_start": year_start, "year_end": year_end,
                    })
                except (httpx.HTTPError, ValueError):
                    continue
                if len(result["sources"]) == 2:
                    break
            if result["sources"]:
                break
        if result["sources"]:
            result["status"] = "found"
    except (httpx.HTTPError, ValueError, ElementTree.ParseError):
        result["status"] = "unavailable"
    return result


def lookup(request: HistoryRequest, text: str):
    # Fixed event and province vocabulary prevents private narrative in search queries.
    if not any(term in text for term in EVENTS[request.event][1]):
        return {"status": "insufficient_context", "sources": []}
    if request.region != "全国" and request.region not in text:
        return {"status": "insufficient_context", "sources": []}
    return _lookup(
        request.event,
        request.region,
        request.year_start,
        request.year_end,
        int(time.time() // 3600),
    )
