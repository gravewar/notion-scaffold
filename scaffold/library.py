"""The building blocks people pick from, and the starter kit for each use case."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .blueprint import Block, Database, Page, Prop, Row, View


@dataclass(frozen=True)
class Context:
    key: str
    label: str
    icon: str
    blurb: str
    category_label: str     # what we call sub-categories in the form
    category_prop: str      # property name used in databases
    hub_title: str
    hub_icon: str
    example_categories: tuple[str, ...]
    defaults: tuple[str, ...]


CONTEXTS: dict[str, Context] = {c.key: c for c in [
    Context("work", "Workplace", "💼", "Run projects, meetings and team knowledge in one place.",
            "Teams or departments", "Team", "Teams", "🏢",
            ("Marketing", "Sales", "Operations"), ("tasks", "projects", "meetings", "wiki", "goals")),
    Context("personal", "Personal life", "🌿", "Plan your days, build habits and keep track of money and media.",
            "Areas of your life", "Area", "Life areas", "🧭",
            ("Health", "Home", "Money", "Hobbies"), ("tasks", "habits", "journal", "budget", "reading")),
    Context("school", "School", "🎓", "Every class, deadline and set of notes, organized for you.",
            "Classes", "Class", "Classes", "📚",
            ("Biology 101", "World History", "Statistics"), ("courses", "assignments", "notes", "weekly")),
    Context("group", "Group project", "🤝", "Split up the work, run meetings and keep everyone on the same page.",
            "Workstreams", "Workstream", "Workstreams", "🧩",
            ("Research", "Design", "Presentation"), ("team", "tasks", "meetings", "decisions", "notes")),
]}


@dataclass
class Ctx:
    context: Context
    categories: list[str]
    samples: bool = True
    tips: bool = True

    @property
    def cat(self) -> str:
        return self.context.category_prop

    def cat_prop(self) -> list[Prop]:
        return [Prop(self.cat, "select", list(self.categories))] if self.categories else []

    def pick(self, i: int) -> dict:
        """Spread sample rows across the user's categories."""
        return {self.cat: self.categories[i % len(self.categories)]} if self.categories else {}

    def rows(self, rows: list[Row]) -> list[Row]:
        return rows if self.samples else []

    def desc(self, text: str) -> str:
        return text if self.tips else ""


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    icon: str
    summary: str
    build: Callable[[Ctx], object]
    categorized: bool = True   # gets the category property + appears on category pages
    names: dict = field(default_factory=dict)  # context-specific display names


STATUS = ["To do", "In progress", "Done"]
PRIORITY = ["High", "Medium", "Low"]


def _tasks(c: Ctx) -> Database:
    group_like = c.context.key in ("work", "group")
    props = [Prop("Task", "title"), Prop("Status", "select", STATUS), Prop("Priority", "select", PRIORITY),
             Prop("Due", "date")]
    if group_like:
        props.append(Prop("Assignee", "people"))
    props += c.cat_prop() + [Prop("Notes", "rich_text")]
    samples = [("Set up this workspace", "Done", "Medium", "-1d"),
               ("Plan next week", "In progress", "High", "+2d"),
               ("Follow up on open questions", "To do", "Medium", "+4d"),
               ("Tidy up old notes", "To do", "Low", "+9d")]
    return Database(
        key="tasks", title="Tasks", icon="✅",
        description=c.desc("Drag cards between columns on the Board as work moves along."),
        props=props,
        views=[View("Board", "board", group_by="Status"),
               View("Due this week", "table", filter={"property": "Due", "date": "next_week"}, sort="Due"),
               View("Calendar", "calendar", date="Due"),
               View("All tasks", "table", sort="Due")],
        rows=c.rows([Row({"Task": t, "Status": s, "Priority": p, "Due": d, **c.pick(i)})
                     for i, (t, s, p, d) in enumerate(samples)]),
    )


def _projects(c: Ctx) -> Database:
    return Database(
        key="projects", title="Projects", icon="🚀",
        description=c.desc("Every project with an owner, a status and start/end dates for the timeline."),
        props=[Prop("Project", "title"), Prop("Status", "select", ["Planning", "Active", "On hold", "Complete"]),
               Prop("Owner", "people"), Prop("Start", "date"), Prop("End", "date"),
               Prop("Priority", "select", PRIORITY)] + c.cat_prop() + [Prop("Summary", "rich_text")],
        views=[View("Timeline", "timeline", date="Start", end_date="End"),
               View("By status", "board", group_by="Status"),
               View("All projects", "table", sort="Start")],
        rows=c.rows([
            Row({"Project": "Website refresh", "Status": "Active", "Start": "-7d", "End": "+21d",
                 "Priority": "High", **c.pick(0)}),
            Row({"Project": "Quarterly report", "Status": "Planning", "Start": "+7d", "End": "+30d",
                 "Priority": "Medium", **c.pick(1)}),
        ]),
    )


MEETING_TEMPLATE = [
    Block("heading_3", "Agenda"), Block("bulleted_list_item", ""),
    Block("heading_3", "Notes"), Block("paragraph", ""),
    Block("heading_3", "Action items"), Block("to_do", ""),
]


def _meetings(c: Ctx) -> Database:
    return Database(
        key="meetings", title="Meeting notes", icon="🗓️",
        description=c.desc("Open the sample meeting, then duplicate it for your next one."),
        props=[Prop("Meeting", "title"), Prop("Date", "date"),
               Prop("Type", "select", ["Check-in", "Planning", "Review", "1:1"]),
               Prop("Attendees", "people")] + c.cat_prop(),
        views=[View("Calendar", "calendar", date="Date"),
               View("Recent", "table", sort="Date", sort_desc=True)],
        rows=c.rows([Row({"Meeting": "📝 Meeting template (duplicate me)", "Date": "today", "Type": "Check-in",
                          **c.pick(0)}, blocks=MEETING_TEMPLATE)]),
    )


def _notes(c: Ctx) -> Database:
    school = c.context.key == "school"
    return Database(
        key="notes", title="Class notes" if school else "Notes & docs", icon="📝",
        description=c.desc("One page per lecture." if school else "Docs, ideas and reference material."),
        props=[Prop("Title", "title")] + c.cat_prop() + [
            Prop("Tags", "multi_select", ["Lecture", "Reading", "Review"] if school else ["Idea", "Reference", "How-to"]),
            Prop("Date", "date"), Prop("Created", "created_time")],
        views=[View("By " + c.cat.lower(), "board", group_by=c.cat) if c.categories else View("Gallery", "gallery"),
               View("Recent", "table", sort="Date", sort_desc=True)],
        rows=c.rows([Row({"Title": "Week 1 lecture" if school else "Getting started", "Date": "today",
                          "Tags": ["Lecture" if school else "How-to"], **c.pick(0)},
                         blocks=[Block("heading_3", "Key ideas"), Block("bulleted_list_item", ""),
                                 Block("heading_3", "Questions"), Block("bulleted_list_item", "")])]),
    )


def _wiki(c: Ctx) -> Page:
    return Page(
        title="Wiki", icon="📖",
        blocks=[Block("callout", "The single source of truth. Add pages for anything people ask about twice.",
                      icon="💡", color="gray_background")] * c.tips + [
            Block("heading_2", "Start here"),
            Block("toggle", "Who we are", children=[Block("paragraph", "Mission, team and how we work.")]),
            Block("toggle", "Tools we use", children=[Block("bulleted_list_item", "Notion for docs and planning")]),
            Block("toggle", "How to ask for help", children=[Block("paragraph", "Where to post questions.")]),
            Block("heading_2", "Processes"),
            Block("bulleted_list_item", "Onboarding checklist"),
            Block("bulleted_list_item", "Weekly rhythm"),
        ],
    )


def _goals(c: Ctx) -> Database:
    return Database(
        key="goals", title="Goals", icon="🎯",
        description=c.desc("Update Progress as you go. Board shows what's on track."),
        props=[Prop("Goal", "title"), Prop("Status", "select", ["On track", "At risk", "Achieved"]),
               Prop("Progress", "number", number_format="percent"), Prop("Target date", "date")]
        + c.cat_prop() + [Prop("Why it matters", "rich_text")],
        views=[View("Board", "board", group_by="Status"), View("All goals", "table", sort="Target date")],
        rows=c.rows([Row({"Goal": "Ship one big thing this quarter", "Status": "On track", "Progress": 0.25,
                          "Target date": "+60d", **c.pick(0)})]),
    )


def _contacts(c: Ctx) -> Database:
    return Database(
        key="contacts", title="Contacts", icon="📇",
        props=[Prop("Name", "title"), Prop("Company", "rich_text"), Prop("Role", "rich_text"),
               Prop("Email", "email"), Prop("Phone", "phone_number"), Prop("Last contacted", "date"),
               Prop("Relationship", "select", ["Client", "Partner", "Vendor", "Friend"])] + c.cat_prop(),
        views=[View("All contacts", "table", sort="Last contacted", sort_desc=True),
               View("By relationship", "board", group_by="Relationship")],
        rows=c.rows([Row({"Name": "Alex Example", "Company": "Example Co.", "Role": "Partner lead",
                          "Email": "alex@example.com", "Relationship": "Partner", "Last contacted": "-10d"})]),
        description=c.desc("Log when you last spoke so nobody slips through the cracks."),
    )


def _decisions(c: Ctx) -> Database:
    return Database(
        key="decisions", title="Decision log", icon="⚖️",
        description=c.desc("Write down what was decided and why, so nobody re-argues it next week."),
        props=[Prop("Decision", "title"), Prop("Status", "select", ["Proposed", "Decided", "Revisited"]),
               Prop("Date", "date"), Prop("Decided by", "people")] + c.cat_prop() + [Prop("Why", "rich_text")],
        views=[View("All decisions", "table", sort="Date", sort_desc=True), View("By status", "board", group_by="Status")],
        rows=c.rows([Row({"Decision": "Meet every Tuesday at 4pm", "Status": "Decided", "Date": "-3d",
                          "Why": "Everyone's free and it's before the weekly deadline.", **c.pick(0)})]),
    )


def _team(c: Ctx) -> Database:
    return Database(
        key="team", title="Team", icon="👥",
        description=c.desc("Who's who, what they're responsible for and how to reach them."),
        props=[Prop("Name", "title"), Prop("Role", "select", ["Lead", "Researcher", "Writer", "Designer", "Presenter"]),
               Prop("Email", "email"), Prop("Responsibilities", "rich_text"),
               Prop("Availability", "rich_text")] + c.cat_prop(),
        views=[View("Directory", "gallery"), View("By role", "board", group_by="Role")],
        rows=c.rows([Row({"Name": "Your name here", "Role": "Lead", "Responsibilities": "Keeps everyone on track",
                          **c.pick(0)})]),
    )


def _journal(c: Ctx) -> Database:
    return Database(
        key="journal", title="Journal", icon="📔",
        description=c.desc("A page a day. The Calendar view shows your streak at a glance."),
        props=[Prop("Entry", "title"), Prop("Date", "date"),
               Prop("Mood", "select", ["😄 Great", "🙂 Good", "😐 Okay", "😕 Low"]), Prop("Grateful for", "rich_text")],
        views=[View("Calendar", "calendar", date="Date"), View("All entries", "list", sort="Date", sort_desc=True)],
        rows=c.rows([Row({"Entry": "First entry", "Date": "today", "Mood": "🙂 Good"},
                         blocks=[Block("heading_3", "Today I…"), Block("paragraph", ""),
                                 Block("heading_3", "Tomorrow I want to…"), Block("to_do", "")])]),
    )


HABITS = ["Water", "Move", "Read", "Sleep by 11"]


def _habits(c: Ctx) -> Database:
    return Database(
        key="habits", title="Habit tracker", icon="🔁",
        description=c.desc("Add one row per day and tick what you did. Rename the checkboxes to your own habits."),
        props=[Prop("Day", "title"), Prop("Date", "date")] + [Prop(h, "checkbox") for h in HABITS],
        views=[View("This week", "table", filter={"property": "Date", "date": "this_week"}, sort="Date"),
               View("Calendar", "calendar", date="Date")],
        rows=c.rows([Row({"Day": "Today", "Date": "today", "Water": True, "Read": True})]),
    )


def _budget(c: Ctx) -> Database:
    return Database(
        key="budget", title="Budget", icon="💸",
        description=c.desc("Log money in and out. Group by Category to see where it goes."),
        props=[Prop("Item", "title"), Prop("Amount", "number", number_format="dollar"),
               Prop("Type", "select", ["Income", "Expense"]),
               Prop("Category", "select", ["Rent", "Groceries", "Transport", "Fun", "Savings", "Pay"]),
               Prop("Date", "date")],
        views=[View("This month", "table", filter={"property": "Date", "date": "past_month"}, sort="Date",
                    sort_desc=True),
               View("By category", "board", group_by="Category")],
        rows=c.rows([Row({"Item": "Paycheque", "Amount": 2000, "Type": "Income", "Category": "Pay", "Date": "-5d"}),
                     Row({"Item": "Groceries", "Amount": 84.5, "Type": "Expense", "Category": "Groceries",
                          "Date": "-2d"})]),
    )


def _reading(c: Ctx) -> Database:
    return Database(
        key="reading", title="Reading & watch list", icon="📚",
        props=[Prop("Title", "title"), Prop("Type", "select", ["Book", "Article", "Show", "Movie", "Podcast"]),
               Prop("Status", "select", ["Want to", "In progress", "Finished"]),
               Prop("Rating", "select", ["⭐⭐⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐", "⭐⭐", "⭐"]), Prop("Link", "url")],
        views=[View("Board", "board", group_by="Status"), View("Gallery", "gallery")],
        rows=c.rows([Row({"Title": "Something you've been meaning to read", "Type": "Book", "Status": "Want to"})]),
        description=c.desc("Everything you want to read or watch, and what you thought of it."),
    )


def _courses(c: Ctx) -> Database:
    names = c.categories or ["Your first class"]
    return Database(
        key="courses", title="Courses", icon="🏫",
        description=c.desc("One row per class. Fill in the schedule and instructor details."),
        props=[Prop("Course", "title"), Prop("Instructor", "rich_text"), Prop("Schedule", "rich_text"),
               Prop("Room", "rich_text"), Prop("Term", "select", ["Fall", "Winter", "Spring", "Summer"]),
               Prop("Current grade", "number", number_format="percent"), Prop("Course page", "url")],
        views=[View("Gallery", "gallery"), View("All courses", "table")],
        rows=[Row({"Course": n}) for n in names],  # real data, not samples: always added
    )


def _assignments(c: Ctx) -> Database:
    return Database(
        key="assignments", title="Assignments & exams", icon="📌",
        description=c.desc("Every deadline in one list. Check 'Due this week' each Monday."),
        props=[Prop("Assignment", "title")] + c.cat_prop() + [
            Prop("Type", "select", ["Homework", "Essay", "Lab", "Quiz", "Exam", "Project"]),
            Prop("Due", "date"), Prop("Status", "select", ["Not started", "Working on it", "Submitted"]),
            Prop("Weight", "number", number_format="percent"), Prop("Grade", "number", number_format="percent")],
        views=[View("Due this week", "table", filter={"property": "Due", "date": "next_week"}, sort="Due"),
               View("Calendar", "calendar", date="Due"),
               View("Board", "board", group_by="Status"),
               View("All", "table", sort="Due")],
        rows=c.rows([Row({"Assignment": a, "Type": t, "Due": d, "Status": "Not started", "Weight": w, **c.pick(i)})
                     for i, (a, t, d, w) in enumerate([("Problem set 1", "Homework", "+3d", 0.05),
                                                       ("Midterm", "Exam", "+24d", 0.25),
                                                       ("Research essay", "Essay", "+35d", 0.2)])]),
    )


def _events(c: Ctx) -> Database:
    return Database(
        key="events", title="Events", icon="📅",
        props=[Prop("Event", "title"), Prop("Date", "date"),
               Prop("Type", "select", ["Deadline", "Social", "Appointment", "Trip"]), Prop("Location", "rich_text")]
        + c.cat_prop(),
        views=[View("Calendar", "calendar", date="Date"),
               View("Coming up", "list", filter={"property": "Date", "date": "next_month"}, sort="Date")],
        rows=c.rows([Row({"Event": "Something to look forward to", "Date": "+6d", "Type": "Social", **c.pick(0)})]),
        description=c.desc("Dates that matter, on one calendar."),
    )


def _weekly(c: Ctx) -> Page:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Weekend"]
    return Page(
        title="Weekly planner", icon="🗒️",
        blocks=[Block("callout", "Reset this page every Sunday: uncheck everything and plan the week ahead.",
                      icon="🔄", color="blue_background")] * c.tips + [
            Block("heading_2", "This week's top 3"),
            Block("numbered_list_item", ""), Block("numbered_list_item", ""), Block("numbered_list_item", ""),
            Block("divider"),
        ] + [b for d in days for b in (Block("heading_3", d), Block("to_do", ""))],
    )


FEATURES: dict[str, Feature] = {f.key: f for f in [
    Feature("tasks", "Task tracker", "✅", "To-dos with status, priority, due dates and a board", _tasks),
    Feature("projects", "Projects & timeline", "🚀", "Projects with owners and a timeline view", _projects),
    Feature("meetings", "Meeting notes", "🗓️", "Notes with an agenda/action-items template", _meetings),
    Feature("notes", "Notes & docs", "📝", "A home for notes, ideas and reference docs", _notes,
            names={"school": "Class notes"}),
    Feature("wiki", "Wiki / handbook", "📖", "A shared knowledge page with collapsible sections", _wiki,
            categorized=False),
    Feature("goals", "Goals", "🎯", "Goals with progress and status", _goals),
    Feature("contacts", "Contacts", "📇", "People, companies and when you last spoke", _contacts),
    Feature("decisions", "Decision log", "⚖️", "What was decided, by whom and why", _decisions),
    Feature("team", "Team directory", "👥", "Who does what and how to reach them", _team),
    Feature("journal", "Journal", "📔", "Daily entries with mood and gratitude", _journal, categorized=False),
    Feature("habits", "Habit tracker", "🔁", "Daily checkboxes for the habits you're building", _habits,
            categorized=False),
    Feature("budget", "Budget", "💸", "Money in and out, by category", _budget, categorized=False),
    Feature("reading", "Reading & watch list", "📚", "Books, shows and articles with ratings", _reading,
            categorized=False),
    Feature("courses", "Courses", "🏫", "One row per class with schedule and grades", _courses, categorized=False),
    Feature("assignments", "Assignments & exams", "📌", "Every deadline, with a calendar and weights", _assignments),
    Feature("events", "Calendar & events", "📅", "Dates that matter on one calendar", _events),
    Feature("weekly", "Weekly planner", "🗒️", "A reusable week-at-a-glance page", _weekly, categorized=False),
]}


def feature_name(key: str, context: str) -> str:
    f = FEATURES[key]
    return f.names.get(context, f.name)
