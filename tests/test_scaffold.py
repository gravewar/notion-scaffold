import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest
from fake_notion import FakeNotion

from scaffold import oauth
from scaffold import render as R
from scaffold.ai import plan_with_ai
from scaffold.blueprint import Block, Blueprint, Database, Prop, View, repair, validate
from scaffold.compose import Request, clean_categories, compose
from scaffold.deploy import Deployer
from scaffold.library import CONTEXTS, FEATURES
from scaffold.preview import render_preview

TODAY = dt.date(2026, 10, 27)


# --------------------------------------------------------------------------- #
# Composing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("context", list(CONTEXTS))
@pytest.mark.parametrize("cats", [[], ["Alpha", "Beta, with comma", "Gamma"]])
@pytest.mark.parametrize("samples", [True, False])
def test_every_feature_in_every_context_is_valid(context, cats, samples):
    bp = compose(Request(context=context, categories=cats, features=list(FEATURES), samples=samples))
    assert validate(bp) == []


def test_defaults_apply_when_nothing_is_picked():
    bp = compose(Request(context="school"))
    titles = [s.title for s in bp.sections]
    assert titles == ["Courses", "Assignments & exams", "Class notes", "Weekly planner"]


def test_categories_become_a_hub_linked_to_the_right_databases():
    bp = compose(Request(context="school", categories=["Bio", "History"]))
    hub = bp.sections[0]
    assert hub.kind == "category_hub" and hub.categories == ["Bio", "History"]
    assert hub.linked == ["assignments", "notes"]
    courses = next(d for d in bp.databases() if d.key == "courses")
    assert [r.values["Course"] for r in courses.rows] == ["Bio", "History"]  # real rows, not samples


def test_clean_categories():
    assert clean_categories(" Bio ,bio, History\nArt,, ") == ["Bio", "History", "Art"]
    assert len(clean_categories([str(i) for i in range(50)])) == 12


def test_blueprint_round_trips_through_json():
    bp = compose(Request(context="group", categories=["Research", "Design"]))
    again = Blueprint.from_dict(json.loads(json.dumps(bp.to_dict())))
    assert again.to_dict() == bp.to_dict()


def test_repair_fixes_what_ai_might_get_wrong():
    bp = Blueprint("x", sections=[Database(
        key="d", title="D",
        props=[Prop("A", "title"), Prop("B", "title"), Prop("a", "select"), Prop("C", "formula")],
        views=[View("v1", "board", group_by="C"), View("v2", "calendar", date="A"), View("ok", "table")],
    )])
    bp.blocks = [Block("toggle", "t", children=[Block("toggle", "deep", children=[Block("paragraph", "x")])]),
                 Block("image", "nope")]
    repair(bp)
    db = bp.sections[0]
    assert [(p.name, p.type) for p in db.props] == [("A", "title"), ("B", "rich_text"), ("C", "rich_text")]
    assert [v.name for v in db.views] == ["ok"]
    assert bp.blocks[0].children[0].children == [] and bp.blocks[1].type == "paragraph"
    assert validate(bp) == []


# --------------------------------------------------------------------------- #
# Rendering payloads
# --------------------------------------------------------------------------- #
def test_rich_text_bold_and_length_limit():
    rt = R.rich_text("Open **Classes** now")
    assert [r["text"]["content"] for r in rt] == ["Open ", "Classes", " now"]
    assert rt[1]["annotations"] == {"bold": True}
    assert len(R.rich_text("x" * 4500)) == 3


def test_relative_dates():
    assert R.resolve_date("today", TODAY) == "2026-10-27"
    assert R.resolve_date("+5d", TODAY) == "2026-11-01"
    assert R.resolve_date("2027-01-01", TODAY) == "2027-01-01"


def test_option_names_lose_commas():
    schema = R.property_schema(Prop("Class", "select", ["Bio, Lab", "Art"]))
    assert [o["name"] for o in schema["select"]["options"]] == ["Bio Lab", "Art"]


# --------------------------------------------------------------------------- #
# Deploying (against an in-memory fake that enforces Notion's rules)
# --------------------------------------------------------------------------- #
def test_full_deploy_creates_everything_in_order():
    fake = FakeNotion()
    bp = compose(Request(context="school", title="Fall 2026", categories=["Bio", "History"]))
    progress = []
    result = Deployer(fake, progress=lambda f, m: progress.append(f), today=TODAY).deploy(bp)
    assert result.warnings == []
    assert result.created == {"pages": 5, "databases": 3, "views": 12, "rows": 6}
    assert progress[-1] == 1.0 and progress == sorted(progress)

    root = fake.pages[result.root_id]
    assert root["body"]["parent"] == {"type": "workspace", "workspace": True}
    # hub is the first child page created under the root
    first_child = next(b for k, b in fake.calls if k == "create_page" and b["parent"].get("page_id") == result.root_id)
    assert first_child["properties"]["title"]["title"][0]["text"]["content"] == "Classes"
    # each class page got filtered linked views
    linked = [b for k, b in fake.calls if k == "create_view" and "create_database" in b]
    assert {b["filter"]["select"]["equals"] for b in linked} == {"Bio", "History"}


def test_deploy_under_a_chosen_page():
    fake = FakeNotion()
    parent = fake.create_page({"parent": {"type": "workspace", "workspace": True}, "properties": {}})
    fake.allow_workspace_parent = False  # like an internal integration: must build under a shared page
    result = Deployer(fake, today=TODAY).deploy(compose(Request(context="personal")), parent["id"])
    assert fake.pages[result.root_id]["body"]["parent"]["page_id"] == parent["id"]


def test_long_pages_are_appended_in_chunks():
    fake = FakeNotion()
    bp = Blueprint("Big", blocks=[Block("to_do", f"item {i}") for i in range(250)])
    Deployer(fake, today=TODAY).deploy(bp)
    kinds = [k for k, _ in fake.calls]
    assert kinds.count("append_children") == 2


def test_view_failures_become_warnings_not_crashes():
    fake = FakeNotion(fail_views=True)
    result = Deployer(fake, today=TODAY).deploy(compose(Request(context="work")))
    assert result.created["databases"] == 4 and result.created["views"] == 0
    assert result.warnings and all("view" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
# Sign-in state
# --------------------------------------------------------------------------- #
def test_oauth_state_round_trip_and_tamper_checks():
    payload = Request(context="school", title="Fall", categories=["Bio"]).to_dict()
    state = oauth.make_state("secret", payload, now=1000)
    assert oauth.read_state("secret", state, now=1100) == payload
    with pytest.raises(ValueError):
        oauth.read_state("other-secret", state, now=1100)
    with pytest.raises(ValueError):
        oauth.read_state("secret", state, now=1000 + oauth.STATE_MAX_AGE + 1)
    data, ts, sig = state.split(".")
    with pytest.raises(ValueError):
        oauth.read_state("secret", f"{data}.{int(ts) + 5000}.{sig}", now=6000)


def test_authorize_url_has_required_params():
    url = oauth.authorize_url("cid", "https://app.example/", "st")
    for part in ("client_id=cid", "response_type=code", "owner=user", "state=st"):
        assert part in url


# --------------------------------------------------------------------------- #
# AI mode (with a stand-in client, no API key needed)
# --------------------------------------------------------------------------- #
def fake_claude(plan):
    return NS(messages=NS(create=lambda **kw: NS(content=[NS(type="tool_use", input=plan)])))


def test_ai_plan_becomes_a_valid_blueprint():
    plan = {
        "context": "personal", "title": "Kitchen", "icon": "🍳", "categories": ["Weeknight"],
        "features": ["tasks", "budget", "made_up"], "summary": "A cooking hub.",
        "custom_sections": [{"kind": "database", "title": "Recipes", "key": "recipes",
                             "props": [{"name": "Recipe", "type": "title"},
                                       {"name": "Cuisine", "type": "select", "options": ["Thai", "Italian"]},
                                       {"name": "Cost", "type": "formula"}],
                             "views": [{"name": "By cuisine", "type": "board", "group_by": "Cuisine"},
                                       {"name": "Broken", "type": "calendar", "date": "Cuisine"}],
                             "rows": [{"values": {"Recipe": "Pad thai", "Cuisine": "Thai", "Ghost": 1}}]}],
    }
    req, summary = plan_with_ai("I cook a lot", "key", client=fake_claude(plan))
    assert summary == "A cooking hub." and req.features == ["tasks", "budget"]
    bp = compose(req)
    assert validate(bp) == []
    recipes = next(d for d in bp.databases() if d.title == "Recipes")
    assert [v.name for v in recipes.views] == ["By cuisine"]
    fake = FakeNotion()
    assert Deployer(fake, today=TODAY).deploy(bp).warnings == []


def test_ai_requires_a_description():
    with pytest.raises(ValueError):
        plan_with_ai("   ", "key", client=fake_claude({}))


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #
def test_preview_escapes_user_text():
    bp = compose(Request(context="work", title="<script>alert(1)</script>", categories=["<b>x</b>"]))
    html = render_preview(bp, today=TODAY)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
