"""Turn someone's answers into a Blueprint."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .blueprint import Block, Blueprint, CategoryHub, Database, Page, Section, repair, validate
from .library import CONTEXTS, FEATURES, Ctx, feature_name

# Databases that are most useful filtered per category, in order of preference.
HUB_PRIORITY = ["assignments", "tasks", "notes", "projects", "meetings", "goals", "decisions", "events", "team"]
MAX_HUB_LINKS = 3
# What to suggest filling in first, most useful first.
STARTERS = ["assignments", "tasks", "projects", "courses", "habits", "journal", "budget", "notes", "team",
            "meetings", "goals", "reading", "contacts", "events", "decisions"]


@dataclass
class Request:
    context: str = "work"
    title: str = ""
    icon: str = ""
    categories: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    samples: bool = True
    tips: bool = True
    custom_sections: list[dict] = field(default_factory=list)  # from AI mode, in blueprint format
    description: str = ""  # AI mode: what the person typed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Request":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def clean_categories(raw) -> list[str]:
    items = raw.replace("\n", ",").split(",") if isinstance(raw, str) else list(raw)
    out, seen = [], set()
    for item in items:
        name = " ".join(str(item).split())[:60]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out[:12]


def compose(req: Request) -> Blueprint:
    context = CONTEXTS.get(req.context, CONTEXTS["work"])
    categories = clean_categories(req.categories)
    ctx = Ctx(context, categories, samples=req.samples, tips=req.tips)
    title = req.title.strip() or f"My {context.label} HQ"
    keys = [k for k in req.features if k in FEATURES] or list(context.defaults)

    built: list[Section] = [FEATURES[k].build(ctx) for k in keys]
    databases = [s for s in built if isinstance(s, Database)]
    pages = [s for s in built if isinstance(s, Page)]

    sections: list[Section] = []
    if categories:
        linkable = [k for k in HUB_PRIORITY if k in keys and FEATURES[k].categorized]
        sections.append(CategoryHub(
            title=context.hub_title, icon=context.hub_icon, property=context.category_prop,
            categories=categories, linked=linkable[:MAX_HUB_LINKS],
            blocks=[Block("callout", f"Each page below shows only the entries tagged with that "
                                     f"{context.category_prop.lower()}.", icon="🔎", color="gray_background")]
            * req.tips,
        ))
    sections += databases + pages

    if req.custom_sections:
        extra = Blueprint.from_dict({"sections": req.custom_sections}).sections
        taken = {d.key for d in databases}
        for s in extra:
            if isinstance(s, Database):
                while s.key in taken:
                    s.key += "_2"
                taken.add(s.key)
        sections += extra

    bp = Blueprint(title=title, icon=req.icon or context.icon, blocks=_home_blocks(req, context, keys, categories),
                   sections=sections)
    bp = repair(bp)
    problems = validate(bp)
    if problems:  # library bugs should never reach a user's workspace
        raise ValueError("Blueprint failed validation:\n- " + "\n- ".join(problems))
    return bp


def _home_blocks(req: Request, context, keys, categories) -> list[Block]:
    blocks: list[Block] = []
    if req.tips:
        blocks.append(Block("callout", f"{context.blurb} Everything lives in the pages below.",
                            icon=context.icon, color="blue_background"))
        steps = []
        if categories:
            steps.append(f"Open **{context.hub_title}** to see one page per {context.category_prop.lower()}")
        first = next((k for k in STARTERS if k in keys), None)
        if first:
            steps.append(f"Add something real to **{feature_name(first, context.key)}**"
                         + (" and delete the samples" if req.samples else ""))
        steps.append("Drag the sections below into the order you like")
        steps.append("Star this page so it's always in your sidebar")
        blocks.append(Block("heading_2", "Quick start"))
        blocks += [Block("to_do", s) for s in steps]
        blocks.append(Block("divider"))
    return blocks
