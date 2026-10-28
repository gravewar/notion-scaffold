"""Pure functions that turn blueprint pieces into Notion API request bodies.

Nothing here talks to the network, which makes every payload easy to test
(and to type-check against Notion's official SDK; see tests/typecheck).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .blueprint import Block, Prop, Row, View, OPTION_COLORS

TEXT_LIMIT = 2000         # characters per rich-text object
CHILDREN_LIMIT = 100      # blocks per request
CAN_HAVE_CHILDREN = {"paragraph", "bulleted_list_item", "numbered_list_item", "to_do", "toggle", "callout", "quote"}
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def rich_text(text: str) -> list[dict]:
    """Plain text with **bold** support, split to respect Notion's 2,000-character limit."""
    out: list[dict] = []
    pos = 0
    pieces: list[tuple[str, bool]] = []
    for m in _BOLD.finditer(text or ""):
        if m.start() > pos:
            pieces.append((text[pos:m.start()], False))
        pieces.append((m.group(1), True))
        pos = m.end()
    if pos < len(text or ""):
        pieces.append((text[pos:], False))
    for chunk, bold in pieces:
        for i in range(0, len(chunk), TEXT_LIMIT):
            item: dict[str, Any] = {"type": "text", "text": {"content": chunk[i:i + TEXT_LIMIT]}}
            if bold:
                item["annotations"] = {"bold": True}
            out.append(item)
    return out


def emoji(icon: str) -> dict | None:
    return {"type": "emoji", "emoji": icon} if icon else None


def block(b: Block) -> dict:
    t = b.type
    if t == "divider":
        return {"type": "divider", "divider": {}}
    if t == "table_of_contents":
        return {"type": "table_of_contents", "table_of_contents": {"color": "default"}}
    body: dict[str, Any] = {"rich_text": rich_text(b.text)}
    if t == "to_do":
        body["checked"] = b.checked
    if t == "callout":
        if b.icon:
            body["icon"] = emoji(b.icon)
        body["color"] = b.color or "default"
    if b.children and t in CAN_HAVE_CHILDREN:
        body["children"] = [block(c) for c in b.children]
    return {"type": t, t: body}


def blocks(items: list[Block]) -> list[dict]:
    return [block(b) for b in items]


def chunks(items: list, size: int = CHILDREN_LIMIT):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def option_name(name: str) -> str:
    return " ".join(str(name).replace(",", " ").split())[:100]  # commas aren't allowed in option names


def property_schema(p: Prop) -> dict:
    if p.type in ("select", "multi_select"):
        opts = [{"name": option_name(o), "color": OPTION_COLORS[i % len(OPTION_COLORS)]}
                for i, o in enumerate(p.options) if option_name(o)]
        return {p.type: {"options": opts}}
    if p.type == "number":
        return {"number": {"format": p.number_format or "number"}}
    return {p.type: {}}


def properties_schema(props: list[Prop]) -> dict:
    return {p.name: property_schema(p) for p in props}


def resolve_date(value: str, today: dt.date) -> str:
    """'today', '+3d', '-2d' or an ISO date -> ISO date."""
    v = str(value).strip().lower()
    if v == "today":
        return today.isoformat()
    m = re.fullmatch(r"([+-]\d+)d", v)
    if m:
        return (today + dt.timedelta(days=int(m.group(1)))).isoformat()
    return str(value)


def row_properties(row: Row, props: list[Prop], today: dt.date) -> dict:
    types = {p.name: p.type for p in props}
    out: dict[str, Any] = {}
    for name, value in row.values.items():
        t = types.get(name)
        if t in ("title", "rich_text"):
            out[name] = {t: rich_text(str(value))}
        elif t == "number":
            try:
                out[name] = {"number": float(value)}
            except (TypeError, ValueError):
                continue
        elif t == "select":
            if option_name(value):
                out[name] = {"select": {"name": option_name(value)}}
        elif t == "multi_select":
            vals = value if isinstance(value, list) else [value]
            out[name] = {"multi_select": [{"name": option_name(v)} for v in vals if option_name(v)]}
        elif t == "date":
            out[name] = {"date": {"start": resolve_date(value, today)}}
        elif t == "checkbox":
            out[name] = {"checkbox": bool(value)}
        elif t in ("url", "email", "phone_number"):
            out[name] = {t: str(value)}
        # people, created_time and last_edited_time can't be set from a blueprint
    return out


def _filter(f: dict | None, types: dict[str, str]) -> dict | None:
    if not f:
        return None
    prop = f["property"]
    if "date" in f:
        return {"property": prop, "date": {f["date"]: {}}}
    t = types.get(prop, "select")
    if t == "checkbox":
        return {"property": prop, "checkbox": {"equals": bool(f.get("equals"))}}
    if t == "multi_select":
        return {"property": prop, "multi_select": {"contains": str(f.get("equals"))}}
    return {"property": prop, t: {"equals": str(f.get("equals"))}}


def view_body(v: View, database_id: str, data_source_id: str, prop_ids: dict[str, str],
              types: dict[str, str]) -> dict:
    body: dict[str, Any] = {"database_id": database_id, "data_source_id": data_source_id,
                            "name": v.name[:100], "type": v.type}
    config: dict[str, Any] = {"type": v.type}
    if v.type == "board":
        gtype = types[v.group_by]
        config["group_by"] = {"type": gtype, "property_id": prop_ids.get(v.group_by, v.group_by),
                              "sort": {"type": "manual"}, "hide_empty_groups": False}
    elif v.type == "calendar":
        config["date_property_id"] = prop_ids.get(v.date, v.date)
        config["view_range"] = "month"
    elif v.type == "timeline":
        config["date_property_id"] = prop_ids.get(v.date, v.date)
        if v.end_date:
            config["end_date_property_id"] = prop_ids.get(v.end_date, v.end_date)
    body["configuration"] = config
    flt = _filter(v.filter, types)
    if flt:
        body["filter"] = flt
    if v.sort:
        body["sorts"] = [{"property": v.sort, "direction": "descending" if v.sort_desc else "ascending"}]
    return body


def linked_view_body(page_id: str, data_source_id: str, name: str, prop: str, category: str,
                     view_type: str = "table") -> dict:
    """A linked copy of a database on a category page, filtered to that category."""
    return {
        "data_source_id": data_source_id,
        "name": name[:100],
        "type": view_type,
        "create_database": {"parent": {"type": "page_id", "page_id": page_id}},
        "filter": {"property": prop, "select": {"equals": option_name(category)}},
        "configuration": {"type": view_type},
    }


def page_body(parent: dict, title: str, icon: str, children: list[dict]) -> dict:
    body: dict[str, Any] = {"parent": parent, "properties": {"title": {"title": rich_text(title)}}}
    if icon:
        body["icon"] = emoji(icon)
    if children:
        body["children"] = children[:CHILDREN_LIMIT]
    return body


def database_body(parent_page_id: str, title: str, icon: str, description: str, props: list[Prop]) -> dict:
    body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": rich_text(title),
        "is_inline": False,
        "initial_data_source": {"properties": properties_schema(props)},
    }
    if description:
        body["description"] = rich_text(description)
    if icon:
        body["icon"] = emoji(icon)
    return body


def row_body(data_source_id: str, row: Row, props: list[Prop], today: dt.date) -> dict:
    body: dict[str, Any] = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": row_properties(row, props, today),
    }
    if row.icon:
        body["icon"] = emoji(row.icon)
    if row.blocks:
        body["children"] = blocks(row.blocks)[:CHILDREN_LIMIT]
    return body
