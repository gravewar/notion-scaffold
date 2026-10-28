"""Render a Blueprint as an HTML mock of the Notion page it will become.

The preview is the product's "plan view": a sheet of drafting paper with the
future Notion page laid on top, so people can see exactly what they'll get
before connecting anything.
"""

from __future__ import annotations

import datetime as dt
from html import escape

from .blueprint import Block, Blueprint, CategoryHub, Database, Page
from .render import resolve_date

CSS = """
<style>
.sc-sheet{--ink:#1d2b4f;--grid:#dde5f0;--paper:#f5f8fc;--pencil:#5b6474;--mark:#ffe066;
  background-color:var(--paper);
  background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:24px 24px;border:1px solid var(--grid);border-radius:6px;padding:28px 20px;
  font-family:ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#37352f}
.sc-page{background:#fff;max-width:720px;margin:0 auto;padding:36px 44px 40px;border-radius:3px;
  box-shadow:0 1px 0 var(--grid),0 12px 28px -18px rgba(29,43,79,.45)}
.sc-icon{font-size:52px;line-height:1;margin-bottom:10px}
.sc-title{font-size:34px;font-weight:700;letter-spacing:-.01em;margin:0 0 14px;color:#2f2e2a;line-height:1.15}
.sc-p{margin:4px 0;line-height:1.55;font-size:15px}
.sc-h2{font-size:21px;font-weight:650;margin:22px 0 6px}.sc-h3{font-size:17px;font-weight:650;margin:16px 0 4px}
.sc-callout{display:flex;gap:10px;padding:12px 14px;border-radius:4px;margin:8px 0;font-size:15px;line-height:1.5}
.sc-bg-blue{background:#e7f0f8}.sc-bg-gray{background:#f1f1ef}.sc-bg-default{background:#f7f6f3}
.sc-todo{display:flex;gap:8px;align-items:center;margin:3px 0;font-size:15px}
.sc-box{width:14px;height:14px;border:1.5px solid #9b9a97;border-radius:2px;flex:none}
.sc-box.on{background:#2383e2;border-color:#2383e2}
.sc-hr{border:none;border-top:1px solid #e9e9e7;margin:14px 0}
.sc-ph{color:#b4b2ad}
.sc-li{margin:2px 0 2px 20px;font-size:15px}
.sc-toggle{margin:3px 0;font-size:15px}.sc-toggle summary{cursor:pointer}
.sc-kids{margin-left:22px}
details.sc-child{margin:2px -8px;border-radius:4px}
details.sc-child>summary{list-style:none;cursor:pointer;padding:5px 8px;border-radius:4px;display:flex;gap:8px;
  align-items:center;font-size:15px}
details.sc-child>summary::-webkit-details-marker{display:none}
details.sc-child>summary:hover{background:#f1f1ef}
details.sc-child>summary:focus-visible{outline:2px solid #2383e2}
.sc-name{border-bottom:1px solid #d3d1cb;font-weight:500}
.sc-kind{margin-left:auto;font-size:12px;color:var(--pencil)}
.sc-inner{border-left:2px solid var(--mark);margin:6px 0 12px 14px;padding:4px 0 6px 16px}
.sc-desc{color:#787774;font-size:14px;margin:2px 0 8px}
.sc-tabs{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;color:#787774;border-bottom:1px solid #e9e9e7;
  padding-bottom:6px;margin-bottom:6px}
.sc-tabs span:first-child{color:#37352f;font-weight:600}
.sc-table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
.sc-table th{text-align:left;font-weight:500;color:#787774;padding:5px 6px;border-bottom:1px solid #e9e9e7;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc-table td{padding:5px 6px;border-bottom:1px solid #f1f1ef;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc-tag{display:inline-block;padding:0 6px;border-radius:3px;background:#e3e2e0;font-size:12px}
.sc-cats{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.sc-cat{padding:6px 10px;border:1px solid #e9e9e7;border-radius:4px;font-size:14px;background:#fff}
.sc-scroll{overflow-x:auto}
@media (max-width:640px){.sc-page{padding:24px 18px}.sc-title{font-size:27px}}
</style>
"""

PROP_ICONS = {"title": "Aa", "rich_text": "≡", "number": "#", "select": "⌄", "multi_select": "☰", "date": "📅",
              "checkbox": "☑", "people": "👤", "url": "🔗", "email": "@", "phone_number": "☎",
              "created_time": "🕒", "last_edited_time": "🕒"}
VIEW_ICONS = {"table": "▦", "board": "▥", "calendar": "📅", "timeline": "⟿", "gallery": "▣", "list": "☰"}
TAG_COLORS = ["#e3e2e0", "#eee0da", "#fadec9", "#fdecc8", "#dbeddb", "#d3e5ef", "#e8deee", "#f5e0e9", "#ffe2dd"]


def _text(t: str) -> str:
    """Escape, then render **bold**."""
    out, bold = [], False
    for i, part in enumerate(escape(t or "").split("**")):
        if i:
            bold = not bold
        out.append(f"<b>{part}</b>" if bold and part else part)
    return "".join(out)


def _blocks(blocks: list[Block]) -> str:
    html = []
    for b in blocks:
        txt = _text(b.text) or '<span class="sc-ph">Empty</span>'
        kids = f'<div class="sc-kids">{_blocks(b.children)}</div>' if b.children else ""
        if b.type == "heading_1":
            html.append(f'<div class="sc-title" style="font-size:26px">{txt}</div>')
        elif b.type == "heading_2":
            html.append(f'<div class="sc-h2">{txt}</div>')
        elif b.type == "heading_3":
            html.append(f'<div class="sc-h3">{txt}</div>')
        elif b.type == "callout":
            color = (b.color or "default").replace("_background", "")
            cls = f"sc-bg-{color}" if color in ("blue", "gray") else "sc-bg-default"
            html.append(f'<div class="sc-callout {cls}"><span>{escape(b.icon or "💡")}</span><div>{txt}{kids}</div></div>')
        elif b.type == "to_do":
            box = "sc-box on" if b.checked else "sc-box"
            html.append(f'<div class="sc-todo"><span class="{box}"></span><span>'
                        f'{_text(b.text) or "<span class=sc-ph>To-do</span>"}</span></div>{kids}')
        elif b.type == "divider":
            html.append('<hr class="sc-hr">')
        elif b.type == "bulleted_list_item":
            html.append(f'<div class="sc-li">• {_text(b.text) or "<span class=sc-ph>List</span>"}</div>{kids}')
        elif b.type == "numbered_list_item":
            html.append(f'<div class="sc-li">{_text(b.text) or "<span class=sc-ph>List</span>"}</div>{kids}')
        elif b.type == "toggle":
            html.append(f'<details class="sc-toggle"><summary>{txt}</summary>{kids}</details>')
        elif b.type == "quote":
            html.append(f'<div class="sc-p" style="border-left:3px solid #37352f;padding-left:12px">{txt}</div>')
        elif b.type == "table_of_contents":
            html.append('<div class="sc-p sc-ph">Table of contents</div>')
        else:
            html.append(f'<div class="sc-p">{_text(b.text) or "&nbsp;"}</div>{kids}')
    return "".join(html)


def _tag(value: str, options: list[str]) -> str:
    i = options.index(value) if value in options else 0
    return f'<span class="sc-tag" style="background:{TAG_COLORS[i % len(TAG_COLORS)]}">{escape(value)}</span>'


def _cell(value, prop, today) -> str:
    if value is None or value == "":
        return ""
    if prop.type == "select":
        return _tag(str(value), prop.options)
    if prop.type == "multi_select":
        vals = value if isinstance(value, list) else [value]
        return " ".join(_tag(str(v), prop.options) for v in vals)
    if prop.type == "checkbox":
        return '<span class="sc-box on" style="display:inline-block"></span>' if value else '<span class="sc-box" style="display:inline-block"></span>'
    if prop.type == "date":
        d = dt.date.fromisoformat(resolve_date(value, today))
        return f"{d:%b} {d.day}, {d.year}"
    if prop.type == "number" and prop.number_format == "percent":
        return f"{float(value) * 100:.0f}%"
    if prop.type == "number" and "dollar" in prop.number_format:
        return f"${float(value):,.2f}"
    return _text(str(value))


def _database(d: Database, today: dt.date) -> str:
    props = d.props[:5]
    tabs = "".join(f"<span>{VIEW_ICONS.get(v.type, '▦')} {escape(v.name)}</span>" for v in d.views) or "<span>▦ Table</span>"
    head = "".join(f"<th{' style=width:34%' if i == 0 else ''}>{PROP_ICONS.get(p.type, '')} {escape(p.name)}</th>"
                   for i, p in enumerate(props))
    rows = "".join("<tr>" + "".join(f"<td>{_cell(r.values.get(p.name), p, today)}</td>" for p in props) + "</tr>"
                   for r in d.rows[:4])
    if not rows:
        rows = f'<tr><td colspan="{len(props)}" class="sc-ph">Empty, ready for your first entry</td></tr>'
    more = f'<div class="sc-desc">+ {len(d.props) - 5} more properties</div>' if len(d.props) > 5 else ""
    desc = f'<div class="sc-desc">{escape(d.description)}</div>' if d.description else ""
    return (f'{desc}<div class="sc-tabs">{tabs}</div>'
            f'<div class="sc-scroll"><table class="sc-table"><tr>{head}</tr>{rows}</table></div>{more}')


def _child(icon: str, title: str, kind: str, inner: str, open_: bool = False) -> str:
    return (f'<details class="sc-child"{" open" if open_ else ""}><summary><span>{escape(icon or "📄")}</span>'
            f'<span class="sc-name">{escape(title)}</span><span class="sc-kind">{kind}</span></summary>'
            f'<div class="sc-inner">{inner}</div></details>')


def _section(s, today, open_=False, titles=None) -> str:
    if isinstance(s, Database):
        return _child(s.icon, s.title, f"Database with {len(s.views)} views", _database(s, today), open_)
    if isinstance(s, CategoryHub):
        cats = "".join(f'<div class="sc-cat">📄 {escape(c)}</div>' for c in s.categories)
        note = (f'<div class="sc-desc">Each page shows its own filtered '
                f'{", ".join(escape((titles or {}).get(k, k).lower()) for k in s.linked)}.</div>' if s.linked else "")
        return _child(s.icon, s.title, f"{len(s.categories)} pages", _blocks(s.blocks) + note +
                      f'<div class="sc-cats">{cats}</div>', open_)
    if isinstance(s, Page):
        inner = _blocks(s.blocks) + "".join(_section(c, today) for c in s.children)
        return _child(s.icon, s.title, "Page", inner, open_)
    return ""


def render_preview(bp: Blueprint, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    titles = {d.key: d.title for d in bp.databases()}
    children = "".join(_section(s, today, open_=(i == 0), titles=titles) for i, s in enumerate(bp.sections))
    return (CSS + '<div class="sc-sheet"><div class="sc-page">'
            f'<div class="sc-icon">{escape(bp.icon)}</div><div class="sc-title">{escape(bp.title)}</div>'
            f'{_blocks(bp.blocks)}{children}</div></div>')
