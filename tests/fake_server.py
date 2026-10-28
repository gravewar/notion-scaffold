"""Serve FakeNotion over HTTP so the whole app (including Sign in with Notion)
can be clicked through in a browser without a real Notion account.

    python tests/fake_server.py 8765
    NOTION_API_BASE=http://localhost:8765/v1 NOTION_CLIENT_ID=demo NOTION_CLIENT_SECRET=s3cret \
      NOTION_REDIRECT_URI=http://localhost:8501 streamlit run app.py
"""

import base64
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from fake_notion import FakeNotion

from scaffold.notion_api import NotionError

FAKE = FakeNotion(allow_workspace_parent=True)
FAKE.create_page({"parent": {"type": "workspace", "workspace": True},
                  "properties": {"title": {"title": [{"type": "text", "text": {"content": "Shared page"}}]}}})
CLIENT = ("demo", "s3cret")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _authed(self):
        if self.headers.get("Notion-Version") != "2026-03-11":
            self._send(400, {"code": "missing_version", "message": "bad Notion-Version"})
            return False
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            self._send(401, {"code": "unauthorized", "message": "no token"})
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/v1/oauth/authorize":
            q = parse_qs(u.query)
            target = q["redirect_uri"][0] + "?" + urlencode({"code": "fake-code", "state": q["state"][0]})
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        if u.path == "/_calls":
            return self._send(200, [k for k, _ in FAKE.calls])
        if not self._authed():
            return
        try:
            if u.path == "/v1/users/me":
                return self._send(200, FAKE.me())
            m = re.fullmatch(r"/v1/databases/(.+)", u.path)
            if m:
                return self._send(200, FAKE.get_database(m.group(1)))
            m = re.fullmatch(r"/v1/data_sources/(.+)", u.path)
            if m:
                return self._send(200, FAKE.get_data_source(m.group(1)))
        except NotionError as e:
            return self._send(e.status, {"code": e.code, "message": e.message})
        self._send(404, {"code": "not_found", "message": u.path})

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        if u.path == "/v1/oauth/token":
            basic = base64.b64encode(f"{CLIENT[0]}:{CLIENT[1]}".encode()).decode()
            if self.headers.get("Authorization") != f"Basic {basic}" or body.get("code") != "fake-code":
                return self._send(400, {"error": "invalid_grant", "error_description": "bad code"})
            return self._send(200, {"access_token": "fake-token", "refresh_token": "r", "bot_id": "b",
                                    "workspace_id": "w", "workspace_name": "Danielle's Notion",
                                    "owner": {}, "duplicated_template_id": None})
        if not self._authed():
            return
        try:
            if u.path == "/v1/pages":
                return self._send(200, FAKE.create_page(body))
            if u.path == "/v1/databases":
                return self._send(200, FAKE.create_database(body))
            if u.path == "/v1/views":
                return self._send(200, FAKE.create_view(body))
            if u.path == "/v1/search":
                results = [{"object": "page", "id": pid, "url": "",
                            "properties": {"title": {"type": "title", "title": [
                                {"plain_text": (p["body"]["properties"].get("title") or {}).get("title", [{}])[0]
                                 .get("text", {}).get("content", "Untitled")}]}}}
                           for pid, p in FAKE.pages.items() if p["body"]["parent"]["type"] != "data_source_id"]
                return self._send(200, {"results": results})
        except NotionError as e:
            return self._send(e.status, {"code": e.code, "message": e.message})
        self._send(404, {"code": "not_found", "message": u.path})

    def do_PATCH(self):
        u = urlparse(self.path)
        if not self._authed():
            return
        m = re.fullmatch(r"/v1/blocks/(.+)/children", u.path)
        if m:
            try:
                return self._send(200, FAKE.append_children(m.group(1), self._body()["children"]))
            except NotionError as e:
                return self._send(e.status, {"code": e.code, "message": e.message})
        self._send(404, {"code": "not_found", "message": u.path})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), Handler).serve_forever()
