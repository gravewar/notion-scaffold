"""An in-memory stand-in for the Notion API.

It records every request body and enforces the rules the real API would reject
on (100 children per request, nesting depth, property types, view config), so
the deployer can be tested end to end without a Notion account.
"""

from __future__ import annotations

import itertools

from scaffold.notion_api import NotionError

PROP_TYPES = {"title", "rich_text", "number", "select", "multi_select", "date", "checkbox", "people", "url",
              "email", "phone_number", "created_time", "last_edited_time"}
VIEW_TYPES = {"table", "board", "list", "calendar", "timeline", "gallery"}


class FakeNotion:
    def __init__(self, allow_workspace_parent: bool = True, fail_views: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.pages: dict[str, dict] = {}
        self.databases: dict[str, dict] = {}
        self.sources: dict[str, dict] = {}
        self.allow_workspace_parent = allow_workspace_parent
        self.fail_views = fail_views
        self._ids = itertools.count(1)

    def _id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids):04d}"

    # ------------------------------------------------------------------ #
    def _check_blocks(self, children, depth=1):
        if len(children) > 100:
            raise NotionError(400, "validation_error", "children length should be ≤ 100")
        for b in children:
            body = b[b["type"]]
            kids = body.get("children", []) if isinstance(body, dict) else []
            if kids and depth >= 2:
                raise NotionError(400, "validation_error", "children nested too deeply")
            for rt in body.get("rich_text", []) if isinstance(body, dict) else []:
                if len(rt["text"]["content"]) > 2000:
                    raise NotionError(400, "validation_error", "text too long")
            self._check_blocks(kids, depth + 1)

    def _parent_exists(self, parent):
        t = parent["type"]
        if t == "workspace":
            if not self.allow_workspace_parent:
                raise NotionError(400, "validation_error", "Can't create pages at the workspace level")
            return
        if t == "page_id" and parent["page_id"] not in self.pages:
            raise NotionError(404, "object_not_found", "parent page not found")
        if t == "data_source_id" and parent["data_source_id"] not in self.sources:
            raise NotionError(404, "object_not_found", "data source not found")

    def create_page(self, body):
        self.calls.append(("create_page", body))
        self._parent_exists(body["parent"])
        self._check_blocks(body.get("children", []))
        if body["parent"]["type"] == "data_source_id":
            schema = self.sources[body["parent"]["data_source_id"]]["properties"]
            for name, value in body["properties"].items():
                if name not in schema:
                    raise NotionError(400, "validation_error", f"{name} is not a property")
                (ptype,) = value.keys()
                if ptype != schema[name]["type"]:
                    raise NotionError(400, "validation_error", f"{name} expected {schema[name]['type']}")
                if ptype in ("select",):
                    opts = {o["name"] for o in schema[name]["select"]["options"]}
                    if value["select"]["name"] not in opts:
                        raise NotionError(400, "validation_error", f"unknown option {value['select']['name']}")
        pid = self._id("page")
        self.pages[pid] = {"body": body, "children": list(body.get("children", []))}
        return {"object": "page", "id": pid, "url": f"https://www.notion.so/{pid}"}

    def append_children(self, block_id, children):
        self.calls.append(("append_children", {"children": children}))
        self._check_blocks(children)
        self.pages[block_id]["children"] += children
        return {"results": children}

    def create_database(self, body):
        self.calls.append(("create_database", body))
        self._parent_exists(body["parent"])
        props = body["initial_data_source"]["properties"]
        if sum(1 for p in props.values() if "title" in p) != 1:
            raise NotionError(400, "validation_error", "exactly one title property required")
        schema = {}
        for i, (name, cfg) in enumerate(props.items()):
            (ptype,) = cfg.keys()
            if ptype not in PROP_TYPES:
                raise NotionError(400, "validation_error", f"bad property type {ptype}")
            for opt in cfg.get(ptype, {}).get("options", []) if isinstance(cfg[ptype], dict) else []:
                if "," in opt["name"]:
                    raise NotionError(400, "validation_error", "commas not allowed in option names")
            schema[name] = {"id": "title" if ptype == "title" else f"p{i}", "type": ptype, ptype: cfg[ptype]}
        did, sid = self._id("db"), self._id("ds")
        self.databases[did] = {"body": body, "ds": sid, "views": []}
        self.sources[sid] = {"database": did, "properties": schema}
        return {"object": "database", "id": did, "data_sources": [{"id": sid, "name": "x"}]}

    def get_database(self, database_id):
        return {"id": database_id, "data_sources": [{"id": self.databases[database_id]["ds"]}]}

    def get_data_source(self, data_source_id):
        self.calls.append(("get_data_source", {"id": data_source_id}))
        return {"id": data_source_id, "properties": self.sources[data_source_id]["properties"]}

    def create_view(self, body):
        self.calls.append(("create_view", body))
        if self.fail_views:
            raise NotionError(400, "validation_error", "views unavailable")
        ds = self.sources.get(body["data_source_id"])
        if not ds:
            raise NotionError(404, "object_not_found", "data source not found")
        targets = [k for k in ("database_id", "view_id", "create_database") if k in body]
        if len(targets) != 1:
            raise NotionError(400, "validation_error", "exactly one of database_id, view_id, create_database")
        if body["type"] not in VIEW_TYPES or body.get("configuration", {}).get("type", body["type"]) != body["type"]:
            raise NotionError(400, "validation_error", "configuration.type must match type")
        ids = {p["id"] for p in ds["properties"].values()} | set(ds["properties"])
        cfg = body.get("configuration", {})
        if body["type"] == "board" and cfg.get("group_by", {}).get("property_id") not in ids:
            raise NotionError(400, "validation_error", "board needs group_by property")
        if body["type"] in ("calendar", "timeline") and cfg.get("date_property_id") not in ids:
            raise NotionError(400, "validation_error", "date_property_id required")
        flt = body.get("filter")
        if flt and flt["property"] not in ds["properties"]:
            raise NotionError(400, "validation_error", "filter on unknown property")
        if "create_database" in body:
            parent = body["create_database"]["parent"]["page_id"]
            if parent not in self.pages:
                raise NotionError(404, "object_not_found", "page not found")
            self.pages[parent]["children"].append({"type": "linked_view", "view": body})
        else:
            self.databases[body["database_id"]]["views"].append(body)
        return {"object": "view", "id": self._id("view")}

    def search_pages(self, query="", limit=50):
        return [{"id": pid, "title": "x", "url": "", "icon": "", "parent_type": "workspace"} for pid in self.pages]

    def me(self):
        return {"bot": {"workspace_name": "Fake workspace"}}
