"""Scaffold: answer a few questions, get a ready-to-use Notion workspace.

    streamlit run app.py
"""

from __future__ import annotations

import json
import os

import streamlit as st

from scaffold import oauth
from scaffold.ai import plan_with_ai
from scaffold.compose import Request, clean_categories, compose
from scaffold.deploy import Deployer
from scaffold.library import CONTEXTS, FEATURES, feature_name
from scaffold.notion_api import NotionClient, NotionError
from scaffold.preview import render_preview

st.set_page_config(page_title="Scaffold: Notion workspace builder", page_icon="🏗️", layout="wide")


def secret(name: str) -> str:
    try:
        return str(st.secrets[name])
    except Exception:
        return os.environ.get(name, "")


CLIENT_ID, CLIENT_SECRET = secret("NOTION_CLIENT_ID"), secret("NOTION_CLIENT_SECRET")
REDIRECT_URI = secret("NOTION_REDIRECT_URI")
OAUTH_READY = bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI)
ANTHROPIC_KEY = secret("ANTHROPIC_API_KEY")

AI = "ai"
MODES = list(CONTEXTS) + [AI]
MODE_LABELS = {**{k: f"{c.icon} {c.label}" for k, c in CONTEXTS.items()}, AI: "✨ Describe it"}
ss = st.session_state


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def set_feature_defaults(context: str) -> None:
    for k in FEATURES:
        ss[f"feat_{k}"] = k in CONTEXTS[context].defaults


def apply_request(req: Request) -> None:
    ss.mode = ss.form_context = req.context if req.context in CONTEXTS else "personal"
    ss.title, ss.icon, ss.cats = req.title, req.icon, ", ".join(req.categories)
    for k in FEATURES:
        ss[f"feat_{k}"] = k in req.features
    ss.samples, ss.tips = req.samples, req.tips
    ss.custom, ss.ai_text = req.custom_sections, req.description


def current_request() -> Request:
    return Request(
        context=ss.form_context, title=ss.title, icon=ss.icon.strip(), categories=clean_categories(ss.cats),
        features=[k for k in FEATURES if ss.get(f"feat_{k}")], samples=ss.samples, tips=ss.tips,
        custom_sections=ss.custom, description=ss.ai_text,
    )


def on_mode_change() -> None:
    if ss.mode is None:          # clicking the selected option again deselects it; undo that
        ss.mode = ss.form_context
    elif ss.mode != AI and ss.mode != ss.form_context:
        ss.form_context = ss.mode
        set_feature_defaults(ss.mode)
        ss.custom = []


def run_ai() -> None:
    ss.ai_error = ""
    try:
        req, summary = plan_with_ai(ss.ai_text, ANTHROPIC_KEY, samples=ss.samples, tips=ss.tips)
        apply_request(req)
        ss.ai_summary = summary or "Here's a plan based on what you described."
    except Exception as e:  # shown to the person, so keep it readable
        ss.ai_error = str(e)


def disconnect() -> None:
    for k in ("token", "workspace", "auth", "pages", "result"):
        ss.pop(k, None)


if "mode" not in ss:
    ss.update(mode="school", form_context="school", title="", icon="", cats="", samples=True, tips=True,
              custom=[], ai_text="", ai_summary="", ai_error="")
    set_feature_defaults("school")

# --------------------------------------------------------------------------- #
# Coming back from "Sign in with Notion"
# --------------------------------------------------------------------------- #
params = st.query_params
if OAUTH_READY and "code" in params:
    try:
        payload = oauth.read_state(CLIENT_SECRET, params.get("state", ""))
        token = oauth.exchange_code(CLIENT_ID, CLIENT_SECRET, params["code"], REDIRECT_URI)
        ss.token, ss.auth = token["access_token"], "oauth"
        ss.workspace = token.get("workspace_name") or "your workspace"
        apply_request(Request.from_dict(payload))
    except Exception as e:
        ss.auth_error = f"Notion sign-in didn't finish: {e}"
    st.query_params.clear()
elif "error" in params:
    ss.auth_error = "Notion sign-in was cancelled, so nothing was connected."
    st.query_params.clear()

# --------------------------------------------------------------------------- #
# Sidebar: connection
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.subheader("Your Notion")
    if ss.get("token"):
        st.success(f"Connected to **{ss.workspace}**")
        st.button("Disconnect", on_click=disconnect)
    else:
        if ss.get("auth_error"):
            st.error(ss.pop("auth_error"))
        if OAUTH_READY:
            req_for_state = current_request().to_dict()
            state = oauth.make_state(CLIENT_SECRET, req_for_state)
            if len(state) > 1800:  # keep the URL a sane length; AI extras get re-planned
                req_for_state["custom_sections"] = []
                state = oauth.make_state(CLIENT_SECRET, req_for_state)
            st.link_button("Sign in with Notion", oauth.authorize_url(CLIENT_ID, REDIRECT_URI, state),
                           type="primary", width="stretch")
            st.caption("Notion will ask which pages Scaffold can use. Pick the page your new "
                       "workspace should live under.")
        with st.expander("Use an integration token instead", expanded=not OAUTH_READY):
            st.markdown(
                "1. Create an integration at [notion.so/profile/integrations]"
                "(https://www.notion.so/profile/integrations)\n"
                "2. Copy its **Internal Integration Secret**\n"
                "3. In Notion, open the page to build under, then **••• → Connections** and add it")
            tok = st.text_input("Integration secret", type="password", key="paste_token")
            if st.button("Connect", disabled=not tok):
                try:
                    me = NotionClient(tok).me()
                    ss.token, ss.auth = tok, "token"
                    ss.workspace = (me.get("bot") or {}).get("workspace_name") or "your workspace"
                    st.rerun()
                except NotionError as e:
                    st.error(f"That token didn't work: {e.message}")
    st.caption("Your token stays in this browser session only and is never stored.")

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
st.markdown("## 🏗️ Scaffold")
st.markdown("Answer a few questions and get a ready-to-use Notion workspace, built for you in about a minute.")

st.pills("What's it for?", MODES, format_func=MODE_LABELS.get, key="mode", on_change=on_mode_change)
left, right = st.columns([5, 7], gap="large")

with left:

    if ss.mode == AI:
        st.text_area("Describe what you need", key="ai_text", height=160, max_chars=2000,
                     placeholder="I'm a nursing student with four classes and a part-time job. I want to "
                                 "track assignments and exams, my shifts, and a simple budget.")
        if ANTHROPIC_KEY:
            st.button("Plan my workspace", type="primary", on_click=run_ai, disabled=not ss.ai_text.strip())
            st.caption("Claude picks from the same building blocks as the form and designs extra pages "
                       "only when nothing fits. You can tweak the plan afterwards.")
        else:
            st.info("Planning from a description needs an Anthropic API key. Add `ANTHROPIC_API_KEY` to this "
                    "app's secrets, or pick one of the other options to build from the form.")
        if ss.ai_error:
            st.error(ss.ai_error)
    else:
        ctx = CONTEXTS[ss.form_context]
        if ss.ai_summary:
            st.success(f"✨ {ss.ai_summary} Change anything you like below.")
        name_col, icon_col = st.columns([5, 1])
        name_col.text_input("Name", key="title", placeholder=f"My {ctx.label} HQ", max_chars=100)
        icon_col.text_input("Icon", key="icon", placeholder=ctx.icon, max_chars=4)
        st.text_input(ctx.category_label, key="cats", placeholder=", ".join(ctx.example_categories),
                      help="Separate them with commas. Each one gets its own page showing only its entries.")

        st.markdown("**What should it do?**")
        col_a, col_b = st.columns(2)
        for i, f in enumerate(FEATURES.values()):
            (col_a if i % 2 == 0 else col_b).checkbox(
                f"{f.icon} {feature_name(f.key, ctx.key)}", key=f"feat_{f.key}", help=f.summary)

        if ss.custom:
            names = ", ".join(f"{s.get('icon', '')} {s.get('title', '')}".strip() for s in ss.custom)
            st.markdown(f"**Designed for you:** {names}")
            if st.button("Remove these"):
                ss.custom = []
                st.rerun()

        st.toggle("Add example entries", key="samples", help="So nothing starts out empty. Delete them anytime.")
        st.toggle("Include how-to tips", key="tips")

request = current_request()
try:
    blueprint = compose(request)
    compose_error = ""
except ValueError as e:
    blueprint, compose_error = None, str(e)

with right:
    if compose_error:
        st.error(compose_error)
    elif blueprint:
        s = blueprint.stats()
        st.markdown(f"**Preview:** {s['pages']} pages, {s['databases']} databases, {s['views']} views")
        st.html(render_preview(blueprint))
        st.download_button("Download this plan (JSON)", json.dumps(blueprint.to_dict(), indent=2, ensure_ascii=False),
                           file_name="scaffold-plan.json", mime="application/json")

        st.markdown("#### Build it in Notion")
        if not ss.get("token"):
            st.info("Connect your Notion in the sidebar, then build this with one click.")
        else:
            client = NotionClient(ss.token)
            if "pages" not in ss:
                try:
                    ss.pages = client.search_pages()
                except NotionError as e:
                    ss.pages = []
                    st.error(f"Couldn't list your pages: {e.message}")
            choices = ([("", "Top level of my workspace")] if ss.auth == "oauth" else []) + \
                      [(p["id"], f"{p['icon']} {p['title']}".strip()) for p in ss.pages]
            if not choices:
                st.warning("Scaffold can't see any pages yet. In Notion, open a page, choose "
                           "**••• → Connections**, add your integration, then refresh.")
            else:
                dest = st.selectbox("Put it under", choices, format_func=lambda c: c[1])
                if st.button(f"Build “{blueprint.title}”", type="primary"):
                    bar = st.progress(0.0, text="Starting…")
                    try:
                        result = Deployer(client, progress=lambda f, m: bar.progress(f, text=m)).deploy(
                            blueprint, dest[0] or None)
                        ss.result = result
                    except NotionError as e:
                        hint = (" Try picking a page to build under instead." if not dest[0] else "")
                        st.error(f"Notion stopped the build: {e.message}.{hint}")
            if st.button("Refresh page list"):
                ss.pop("pages", None)
                st.rerun()

        if ss.get("result"):
            r = ss.result
            c = r.created
            st.success(f"Built! {c['pages']} pages, {c['databases']} databases, {c['views']} views "
                       f"and {c['rows']} example entries.")
            if r.url:
                st.link_button("Open in Notion", r.url, type="primary")
            if r.warnings:
                with st.expander(f"{len(r.warnings)} things didn't go quite to plan"):
                    for w in r.warnings:
                        st.write("•", w)
