"""A small Notion API client: just the endpoints Scaffold needs, with polite rate limiting."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

API = os.environ.get("NOTION_API_BASE", "https://api.notion.com/v1")  # overridable for local testing
NOTION_VERSION = "2026-03-11"


class NotionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"Notion API {status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class NotionClient:
    """Notion allows about 3 requests a second per integration, so calls are spaced out
    and 429/5xx responses are retried with backoff."""

    def __init__(self, token: str, session: requests.Session | None = None, min_interval: float = 0.34,
                 max_retries: int = 5):
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                        "Content-Type": "application/json"}
        self.min_interval, self.max_retries = min_interval, max_retries
        self._last = 0.0
        self.calls = 0

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            resp = self.session.request(method, f"{API}{path}", json=body, headers=self.headers, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    break
                retry_after = resp.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else min(2 ** attempt, 16))
                continue
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                raise NotionError(resp.status_code, data.get("code", "error"), data.get("message", resp.text[:300]))
            return data
        raise NotionError(resp.status_code, "unavailable", "Notion is busy right now. Please try again shortly.")

    # -- endpoints ------------------------------------------------------- #
    def create_page(self, body: dict) -> dict:
        return self.request("POST", "/pages", body)

    def append_children(self, block_id: str, children: list[dict]) -> dict:
        return self.request("PATCH", f"/blocks/{block_id}/children", {"children": children})

    def create_database(self, body: dict) -> dict:
        return self.request("POST", "/databases", body)

    def get_database(self, database_id: str) -> dict:
        return self.request("GET", f"/databases/{database_id}")

    def get_data_source(self, data_source_id: str) -> dict:
        return self.request("GET", f"/data_sources/{data_source_id}")

    def create_view(self, body: dict) -> dict:
        return self.request("POST", "/views", body)

    def me(self) -> dict:
        return self.request("GET", "/users/me")

    def search_pages(self, query: str = "", limit: int = 50) -> list[dict]:
        data = self.request("POST", "/search", {
            "query": query, "page_size": limit,
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        })
        return [summarize_page(p) for p in data.get("results", []) if p.get("object") == "page"]


def summarize_page(page: dict) -> dict[str, Any]:
    title = ""
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
            break
    icon = page.get("icon") or {}
    return {"id": page["id"], "title": title or "Untitled", "url": page.get("url", ""),
            "icon": icon.get("emoji", "") if icon.get("type") == "emoji" else "",
            "parent_type": (page.get("parent") or {}).get("type", "")}
