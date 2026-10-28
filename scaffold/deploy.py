"""Build a Blueprint in a real Notion workspace."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from . import render as R
from .blueprint import Blueprint, CategoryHub, Database, Page, Section
from .notion_api import NotionClient, NotionError

Progress = Callable[[float, str], None]


@dataclass
class DeployResult:
    root_id: str
    url: str
    created: dict = field(default_factory=lambda: {"pages": 0, "databases": 0, "views": 0, "rows": 0})
    warnings: list[str] = field(default_factory=list)


def count_steps(bp: Blueprint) -> int:
    steps = 1

    def walk(sections):
        nonlocal steps
        for s in sections:
            if isinstance(s, Page):
                steps += 1
                walk(s.children)
            elif isinstance(s, Database):
                steps += 2 + len(s.views) + len(s.rows)
            elif isinstance(s, CategoryHub):
                steps += 1 + len(s.categories) * (1 + len(s.linked))
    walk(bp.sections)
    return steps


class Deployer:
    def __init__(self, client: NotionClient, progress: Progress | None = None, today: dt.date | None = None):
        self.client = client
        self.progress = progress or (lambda frac, msg: None)
        self.today = today or dt.date.today()
        self._done = 0
        self._total = 1
        self.dbs: dict[str, dict] = {}  # key -> {"id", "ds", "types"}

    def _step(self, msg: str) -> None:
        self._done += 1
        self.progress(min(self._done / self._total, 1.0), msg)

    # ------------------------------------------------------------------ #
    def deploy(self, bp: Blueprint, parent_page_id: str | None = None) -> DeployResult:
        self._total = count_steps(bp)
        parent = ({"type": "page_id", "page_id": parent_page_id} if parent_page_id
                  else {"type": "workspace", "workspace": True})
        root = self._page(parent, bp.title, bp.icon, R.blocks(bp.blocks))
        self._step(f"Created {bp.icon} {bp.title}")
        result = DeployResult(root_id=root["id"], url=root.get("url", ""))
        result.created["pages"] += 1

        # Databases must exist before category pages can show filtered copies of them,
        # but hubs should sit at the top of the home page. Notion lists child pages in
        # creation order, so: create the hub shells first, fill them in at the end.
        hubs: list[tuple[CategoryHub, str]] = []
        for s in bp.sections:
            if isinstance(s, CategoryHub):
                hub = self._page({"type": "page_id", "page_id": root["id"]}, s.title, s.icon, R.blocks(s.blocks))
                result.created["pages"] += 1
                self._step(f"Created {s.title}")
                hubs.append((s, hub["id"]))
            else:
                self._section(s, root["id"], result)

        for hub, hub_id in hubs:
            self._fill_hub(hub, hub_id, result)
        self.progress(1.0, "Done!")
        return result

    def _page(self, parent: dict, title: str, icon: str, children: list[dict]) -> dict:
        page = self.client.create_page(R.page_body(parent, title, icon, children))
        for chunk in list(R.chunks(children))[1:]:
            self.client.append_children(page["id"], chunk)
        return page

    def _section(self, s: Section, parent_id: str, result: DeployResult) -> None:
        if isinstance(s, Page):
            page = self._page({"type": "page_id", "page_id": parent_id}, s.title, s.icon, R.blocks(s.blocks))
            result.created["pages"] += 1
            self._step(f"Created page {s.title}")
            for child in s.children:
                self._section(child, page["id"], result)
        elif isinstance(s, Database):
            self._database(s, parent_id, result)

    def _database(self, d: Database, parent_id: str, result: DeployResult) -> None:
        db = self.client.create_database(R.database_body(parent_id, d.title, d.icon, d.description, d.props))
        result.created["databases"] += 1
        self._step(f"Created database {d.title}")

        sources = db.get("data_sources") or self.client.get_database(db["id"]).get("data_sources", [])
        ds_id = sources[0]["id"]
        ds = self.client.get_data_source(ds_id)
        self._step(f"Read {d.title} properties")
        prop_ids = {name: p.get("id", name) for name, p in (ds.get("properties") or {}).items()}
        types = {p.name: p.type for p in d.props}
        self.dbs[d.key] = {"id": db["id"], "ds": ds_id, "title": d.title, "icon": d.icon}

        for v in d.views:
            try:
                self.client.create_view(R.view_body(v, db["id"], ds_id, prop_ids, types))
                result.created["views"] += 1
            except NotionError as e:  # a missing view shouldn't sink the whole build
                result.warnings.append(f"Couldn't add the '{v.name}' view to {d.title}: {e.message}")
            self._step(f"Added {v.name} view to {d.title}")

        for row in d.rows:
            try:
                self.client.create_page(R.row_body(ds_id, row, d.props, self.today))
                result.created["rows"] += 1
            except NotionError as e:
                result.warnings.append(f"Couldn't add a sample entry to {d.title}: {e.message}")
            self._step(f"Added an entry to {d.title}")

    def _fill_hub(self, hub: CategoryHub, hub_id: str, result: DeployResult) -> None:
        for cat in hub.categories:
            page = self._page({"type": "page_id", "page_id": hub_id}, cat, "", [])
            result.created["pages"] += 1
            self._step(f"Created {cat}")
            for key in hub.linked:
                info = self.dbs.get(key)
                if not info:
                    self._step("Skipped a missing database")
                    continue
                name = f"{info['icon']} {info['title']}".strip()
                try:
                    self.client.create_view(R.linked_view_body(page["id"], info["ds"], name, hub.property, cat))
                    result.created["views"] += 1
                except NotionError as e:
                    result.warnings.append(f"Couldn't add {info['title']} to the {cat} page: {e.message}")
                self._step(f"Linked {info['title']} on {cat}")
