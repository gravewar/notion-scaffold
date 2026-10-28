"""The blueprint: a plain description of a Notion workspace, independent of the API.

Everything in Scaffold flows through this format:

    form answers / AI  ->  Blueprint  ->  preview (no Notion needed)
                                      ->  deploy (Notion API calls)

Keeping the plan separate from the API calls means it can be previewed,
tested, saved as JSON and repaired before anything touches a real workspace.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Union

PROPERTY_TYPES = {
    "title", "rich_text", "number", "select", "multi_select", "date", "checkbox",
    "people", "url", "email", "phone_number", "created_time", "last_edited_time",
}
VIEW_TYPES = {"table", "board", "calendar", "timeline", "gallery", "list"}
BLOCK_TYPES = {
    "heading_1", "heading_2", "heading_3", "paragraph", "bulleted_list_item",
    "numbered_list_item", "to_do", "toggle", "callout", "quote", "divider",
    "table_of_contents",
}
GROUPABLE = {"select", "multi_select", "checkbox", "people"}
NUMBER_FORMATS = {"number", "percent", "dollar", "canadian_dollar", "euro", "pound"}
DATE_FILTERS = {"past_week", "next_week", "this_week", "past_month", "next_month"}
OPTION_COLORS = ["gray", "brown", "orange", "yellow", "green", "blue", "purple", "pink", "red"]
MAX_DEPTH = 2  # Notion accepts two levels of nested blocks per request


@dataclass
class Block:
    type: str
    text: str = ""
    checked: bool = False
    icon: str = ""
    color: str = ""
    children: list["Block"] = field(default_factory=list)


@dataclass
class Prop:
    name: str
    type: str
    options: list[str] = field(default_factory=list)
    number_format: str = ""


@dataclass
class View:
    name: str
    type: str
    group_by: str = ""         # board: property to group cards by
    date: str = ""             # calendar/timeline: date property
    end_date: str = ""         # timeline: optional end-date property
    filter: dict | None = None  # {"property": P, "equals": V} or {"property": P, "date": "next_week"}
    sort: str = ""             # property to sort by
    sort_desc: bool = False


@dataclass
class Row:
    values: dict[str, Any]
    icon: str = ""
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Database:
    key: str                   # internal handle so category pages can point at it
    title: str
    icon: str = ""
    description: str = ""
    props: list[Prop] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    kind: str = "database"


@dataclass
class Page:
    title: str
    icon: str = ""
    blocks: list[Block] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)
    kind: str = "page"


@dataclass
class CategoryHub:
    """One sub-page per category, each showing only its own entries from chosen databases."""
    title: str
    property: str               # select property shared by the linked databases
    categories: list[str]
    icon: str = ""
    linked: list[str] = field(default_factory=list)  # database keys
    blocks: list[Block] = field(default_factory=list)
    kind: str = "category_hub"


Section = Union[Page, Database, CategoryHub]


@dataclass
class Blueprint:
    title: str
    icon: str = ""
    blocks: list[Block] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Blueprint":
        return cls(
            title=d.get("title", "Untitled"), icon=d.get("icon", ""),
            blocks=[_block(b) for b in d.get("blocks", [])],
            sections=[_section(s) for s in d.get("sections", [])],
        )

    def databases(self) -> list[Database]:
        out: list[Database] = []

        def walk(sections):
            for s in sections:
                if isinstance(s, Database):
                    out.append(s)
                elif isinstance(s, Page):
                    walk(s.children)
        walk(self.sections)
        return out

    def stats(self) -> dict:
        dbs = self.databases()
        pages = sum(1 for s in _walk(self.sections) if isinstance(s, Page))
        hubs = [s for s in _walk(self.sections) if isinstance(s, CategoryHub)]
        return {
            "pages": 1 + pages + sum(len(h.categories) + 1 for h in hubs),
            "databases": len(dbs),
            "views": sum(len(d.views) for d in dbs) + sum(len(h.categories) * len(h.linked) for h in hubs),
            "sample_rows": sum(len(d.rows) for d in dbs),
        }


def _walk(sections):
    for s in sections:
        yield s
        if isinstance(s, Page):
            yield from _walk(s.children)


def _block(d: dict) -> Block:
    return Block(type=d.get("type", "paragraph"), text=d.get("text", ""), checked=bool(d.get("checked")),
                 icon=d.get("icon", ""), color=d.get("color", ""),
                 children=[_block(c) for c in d.get("children", [])])


def _section(d: dict) -> Section:
    kind = d.get("kind", "page")
    if kind == "database":
        return Database(
            key=d.get("key") or d.get("title", "db"), title=d.get("title", "Database"), icon=d.get("icon", ""),
            description=d.get("description", ""),
            props=[Prop(p["name"], p.get("type", "rich_text"), list(p.get("options", [])), p.get("number_format", ""))
                   for p in d.get("props", [])],
            views=[View(**{k: v for k, v in v.items() if k in View.__dataclass_fields__}) for v in d.get("views", [])],
            rows=[Row(dict(r.get("values", {})), r.get("icon", ""), [_block(b) for b in r.get("blocks", [])])
                  for r in d.get("rows", [])],
        )
    if kind == "category_hub":
        return CategoryHub(title=d.get("title", "Categories"), property=d.get("property", "Category"),
                           categories=list(d.get("categories", [])), icon=d.get("icon", ""),
                           linked=list(d.get("linked", [])), blocks=[_block(b) for b in d.get("blocks", [])])
    return Page(title=d.get("title", "Page"), icon=d.get("icon", ""),
                blocks=[_block(b) for b in d.get("blocks", [])],
                children=[_section(c) for c in d.get("children", [])])


# --------------------------------------------------------------------------- #
# Validation and repair
# --------------------------------------------------------------------------- #


def validate(bp: Blueprint) -> list[str]:
    """Every problem that would make the Notion API reject the plan."""
    errors: list[str] = []
    keys = {d.key for d in bp.databases()}
    db_by_key = {d.key: d for d in bp.databases()}

    def check_blocks(blocks, where, depth=1):
        for b in blocks:
            if b.type not in BLOCK_TYPES:
                errors.append(f"{where}: unknown block type '{b.type}'")
            if b.children and depth >= MAX_DEPTH:
                errors.append(f"{where}: blocks are nested more than {MAX_DEPTH} levels deep")
            check_blocks(b.children, where, depth + 1)

    check_blocks(bp.blocks, "Home page")
    for s in _walk(bp.sections):
        if isinstance(s, Page):
            check_blocks(s.blocks, f"Page '{s.title}'")
        elif isinstance(s, CategoryHub):
            check_blocks(s.blocks, f"'{s.title}'")
            for k in s.linked:
                if k not in keys:
                    errors.append(f"'{s.title}' links to unknown database '{k}'")
                elif s.property not in {p.name for p in db_by_key[k].props}:
                    errors.append(f"'{s.title}': database '{db_by_key[k].title}' has no '{s.property}' property")
        elif isinstance(s, Database):
            where = f"Database '{s.title}'"
            names = [p.name for p in s.props]
            types = {p.name: p.type for p in s.props}
            if len(names) != len(set(n.lower() for n in names)):
                errors.append(f"{where}: duplicate property names")
            if sum(1 for p in s.props if p.type == "title") != 1:
                errors.append(f"{where}: needs exactly one title property")
            for p in s.props:
                if p.type not in PROPERTY_TYPES:
                    errors.append(f"{where}: property '{p.name}' has unknown type '{p.type}'")
                if p.type == "number" and p.number_format and p.number_format not in NUMBER_FORMATS:
                    errors.append(f"{where}: '{p.name}' has unknown number format")
            for v in s.views:
                if v.type not in VIEW_TYPES:
                    errors.append(f"{where}: view '{v.name}' has unknown type '{v.type}'")
                if v.type == "board" and types.get(v.group_by) not in GROUPABLE:
                    errors.append(f"{where}: board '{v.name}' must group by a select, checkbox or person property")
                if v.type in ("calendar", "timeline") and types.get(v.date) != "date":
                    errors.append(f"{where}: {v.type} '{v.name}' needs a date property")
                if v.end_date and types.get(v.end_date) != "date":
                    errors.append(f"{where}: timeline '{v.name}' end date must be a date property")
                if v.sort and v.sort not in types:
                    errors.append(f"{where}: view '{v.name}' sorts by missing property '{v.sort}'")
                if v.filter:
                    fp = v.filter.get("property")
                    if fp not in types:
                        errors.append(f"{where}: view '{v.name}' filters on missing property '{fp}'")
                    elif "date" in v.filter and (types[fp] != "date" or v.filter["date"] not in DATE_FILTERS):
                        errors.append(f"{where}: view '{v.name}' has an invalid date filter")
            for i, r in enumerate(s.rows):
                for name in r.values:
                    if name not in types:
                        errors.append(f"{where}: sample row {i + 1} sets missing property '{name}'")
                check_blocks(r.blocks, f"{where} row {i + 1}")
    return errors


def repair(bp: Blueprint) -> Blueprint:
    """Fix what can be fixed automatically (used on AI output), drop the rest."""
    def fix_blocks(blocks, depth=1):
        out = []
        for b in blocks:
            if b.type not in BLOCK_TYPES:
                b.type = "paragraph"
            b.children = fix_blocks(b.children, depth + 1) if depth < MAX_DEPTH else []
            out.append(b)
        return out

    bp.blocks = fix_blocks(bp.blocks)
    for s in list(_walk(bp.sections)):
        if isinstance(s, (Page, CategoryHub)):
            s.blocks = fix_blocks(s.blocks)
        if not isinstance(s, Database):
            continue
        seen, props = set(), []
        for p in s.props:
            name = p.name.strip()[:100] or "Untitled"
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            p.name = name
            if p.type not in PROPERTY_TYPES:
                p.type = "rich_text"
            if p.type == "number" and p.number_format not in NUMBER_FORMATS:
                p.number_format = ""
            props.append(p)
        titles = [p for p in props if p.type == "title"]
        for extra in titles[1:]:
            extra.type = "rich_text"
        if not titles:
            props.insert(0, Prop("Name", "title"))
        s.props = props
        types = {p.name: p.type for p in s.props}
        good = []
        for v in s.views:
            if v.type not in VIEW_TYPES:
                continue
            if v.type == "board" and types.get(v.group_by) not in GROUPABLE:
                continue
            if v.type in ("calendar", "timeline") and types.get(v.date) != "date":
                continue
            if v.end_date and types.get(v.end_date) != "date":
                v.end_date = ""
            if v.sort and v.sort not in types:
                v.sort = ""
            if v.filter and (v.filter.get("property") not in types or
                             ("date" in v.filter and v.filter.get("date") not in DATE_FILTERS)):
                v.filter = None
            good.append(v)
        s.views = good
        for r in s.rows:
            r.values = {k: v for k, v in r.values.items() if k in types}
            r.blocks = fix_blocks(r.blocks)
    keys = {d.key: d for d in bp.databases()}
    for s in _walk(bp.sections):
        if isinstance(s, CategoryHub):
            s.linked = [k for k in s.linked if k in keys and s.property in {p.name for p in keys[k].props}]
    return bp
