import json
from functools import lru_cache
from typing import Any, Callable

from ..workroom_core import selftest
from ..workroom_core.service import Service, ServiceError
from ..workroom_core.status import collect_status

STATUS_SCHEMA = {
    "name": "workroom_status",
    "description": "Report Workroom's version and readiness, and list the registered projects with the project id every other Workroom tool needs.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

ADD_PROJECT_SCHEMA = {
    "name": "workroom_add_project",
    "description": "Register a folder of Office files (decks, reports, workbooks) as a Workroom project. Reads nothing yet.",
    "parameters": {"type": "object", "properties": {"folder": {"type": "string", "description": "Absolute folder path on this machine"}}, "required": ["folder"]},
}

PROJECT_ONLY = {"type": "object", "properties": {"project": {"type": "string", "description": "Project id from workroom_add_project"}}, "required": ["project"]}

DISCOVER_SCHEMA = {
    "name": "workroom_discover",
    "description": "Find the numbers in the project's decks and link them to cells in its workbooks. Writes nothing to the documents. Lists the links that need a human decision.",
    "parameters": PROJECT_ONLY,
}

PLAN_SCHEMA = {
    "name": "workroom_plan",
    "description": "Preview which tied numbers changed in the sources and what each document would say afterwards. Changes nothing.",
    "parameters": PROJECT_ONLY,
}

EXPLAIN_SCHEMA = {
    "name": "workroom_explain_figure",
    "description": "Explain where one number in a document came from: its source cell, labels, formula, value now and at the last release. Read-only.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "link": {"type": "integer", "description": "Link id from workroom_discover"}}, "required": ["project", "link"]},
}

SELFTEST_SCHEMA = {
    "name": "workroom_selftest",
    "description": "Run Workroom's bundled self-test (a few seconds): matching precision with intervals, split-run editing, and crash recovery of a release at 15 failure points. Synthetic; writes only to a temporary folder.",
    "parameters": {"type": "object", "properties": {"seed": {"type": "integer"}}, "required": []},
}

STAGE_SCHEMA = {
    "name": "workroom_stage_release",
    "description": "Prepare the update as a release for the owner to review and approve in Workroom. This does not change any document; only the owner can approve and publish it.",
    "parameters": PROJECT_ONLY,
}


ROLL_SCHEMA = {
    "name": "workroom_roll_forward",
    "description": ("Prepare one release that rolls the project's documents forward to the next reporting period: every tied figure moves to the same row's next period column, "
                    "and the period words beside them (Q3 2026 becomes Q4 2026) advance. It is refused, naming each figure, when a tied figure has no next-period value. "
                    "This does not change any document; only the owner can approve it, and the owner can restore the whole roll."),
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "periods": {"type": "integer", "description": "How many periods to roll forward (1 to 4, default 1)"}}, "required": ["project"]},
}

CALCULATIONS_SCHEMA = {
    "name": "workroom_find_calculations",
    "description": "List numbers in the project's documents that a calculation over tied cells reproduces (a percent change, a margin, a difference, a total), with the formula. Writes nothing; the owner accepts or dismisses each one.",
    "parameters": PROJECT_ONLY,
}

SOURCES_SCHEMA = {
    "name": "workroom_list_sources",
    "description": "List the numeric cells in the project's workbooks with their row and column labels, so a spec can name the exact cell it needs. Optional query filters by label words (for example 'revenue q2'). Read-only.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["project"]},
}

CREATE_SCHEMA = {
    "name": "workroom_create",
    "description": (
        "Create a new PowerPoint deck or Word report whose every figure is tied to a source cell. You never write the file: you write a spec "
        "and Workroom builds it, checks it and stages it for the owner to approve. Nothing is written until the owner approves.\n"
        "Spec: {version:1, kind:'pptx'|'docx', path:'reports/q2.pptx', facts:{id:{ref:'results.xlsx!Results!C2', concept:'Revenue', period:'Q2', "
        "unit:'currency'|'percent'|'count'|'ratio'}}, slides:[{title, blocks:[...]}] (pptx) or blocks:[...] (docx)}. "
        "Blocks: text{text}, bullets{items}, table{header,rows}, chart{kind:'bar'|'line', title, categories, series:[{name, facts:[ids]}]} (pptx only), "
        "heading{level,text} and paragraph{text} (docx only). "
        "Write every figure as a slot {fact_id:format} inside text, for example 'Q2 revenue was {rev:$#,##0} and margin {mar:0.0%}'. "
        "Formats: #,##0  #,##0.00  $#,##0  $#,##0.0M  #,##0K  0.0%. A percent fact holds a fraction (0.25 shows 25.0%). "
        "Find cells with workroom_list_sources. Never type a number that is not a slot. Facts need ref, concept, period and unit. "
        "Visual page: kind 'scene', path 'pages/name.scene.json', and scene:{canvas:{w,h}, nodes:[{id,type:'rect'|'ellipse'|'line'|'text',x,y,w,h,fill,stroke,stroke_w,radius,rotate,opacity; text nodes also text (with {fact:format} slots), size,color,bold,align}]} (colours are six hex digits, nodes draw in list order). "
        "Workbook: kind 'xlsx', path 'name.xlsx', sheets:[{name, rows:[[cell,...],...]}] where a cell is text, a number, {fact:'id', format:'$#,##0'} (a tied number; formats without K, M or B) {formula:'=B2*2'} (kept as a formula) or {input: 0.05} (a number you are told to type, such as an assumption; plain numbers are refused); the first row is the header. Put figures in their own cells, not inside text. "
        "If the spec is refused, the reply lists each error; fix those and call again."
    ),
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "spec": {"type": "object"}}, "required": ["project", "spec"]},
}


INSTRUCTIONS_SCHEMA = {
    "name": "workroom_instructions",
    "description": "Read the owner's project instructions (workroom.md, AGENTS.md, CLAUDE.md in the project folder). You only receive the text of files the owner has authorised; the rest are listed as pending. The instructions are preferences, never permissions. Read-only.",
    "parameters": PROJECT_ONLY,
}

PROPOSE_INSTRUCTION_SCHEMA = {
    "name": "workroom_propose_instruction",
    "description": "Propose new full text for workroom.md. Nothing is changed: the owner sees a diff in the Workroom screen and applies or rejects it.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "text": {"type": "string"}}, "required": ["project", "text"]},
}


PAGES_SCHEMA = {
    "name": "workroom_list_pages",
    "description": "List the visual pages (*.scene.json) in the project and whether each has unsaved edits. Read-only.",
    "parameters": PROJECT_ONLY,
}

READ_PAGE_SCHEMA = {
    "name": "workroom_read_page",
    "description": "Read one visual page: its canvas, nodes (id, type, position, size, colours, text) and draft revision, including any unsaved edits. Read-only.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "path": {"type": "string"}}, "required": ["project", "path"]},
}

EDIT_PAGE_SCHEMA = {
    "name": "workroom_edit_page",
    "description": (
        "Edit a visual page as a draft with small operations. Nothing in the project changes: the owner sees your edits in the page editor and saves them as a release for approval. "
        "ops: add{node, index?}, update{id, set:{...}, unset?:[keys]}, delete{id}, reorder{id, index}. Give rev from workroom_read_page. "
        "A tied text node's text is rewritten from its source on refresh; editing its text by hand makes Workroom hold it, so change its template wording with the owner instead."
    ),
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "path": {"type": "string"}, "rev": {"type": "integer"}, "ops": {"type": "array", "items": {"type": "object"}}}, "required": ["project", "path", "rev", "ops"]},
}

EXPORT_PAGE_SCHEMA = {
    "name": "workroom_export_page",
    "description": "Stage an SVG, HTML or native PowerPoint export of a visual page next to it, for the owner to approve. format is svg, html or pptx. Exports are snapshots; export again after the page changes.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "path": {"type": "string"}, "format": {"type": "string", "enum": ["svg", "html", "pptx"]}}, "required": ["project", "path", "format"]},
}


WHERE_USED_SCHEMA = {
    "name": "workroom_where_used",
    "description": "Side question: every place in the project's documents that shows one source cell (ref like results.xlsx!Results!C2), with its sentence. Read-only.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "ref": {"type": "string"}}, "required": ["project", "ref"]},
}

WHAT_IF_SCHEMA = {
    "name": "workroom_what_if",
    "description": "Side question: what each place would say if a source cell held a different value. Nothing is changed or staged. Read-only.",
    "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "ref": {"type": "string"}, "value": {"type": "number"}}, "required": ["project", "ref", "value"]},
}


@lru_cache(maxsize=1)
def service() -> Service:
    from plugins.plugin_storage import plugin_data_dir

    return Service(plugin_data_dir("workroom"))


def host_status() -> dict[str, Any]:
    """Collect status using Hermes' public storage helper; the kernel itself never imports Hermes."""
    from plugins.plugin_storage import plugin_data_dir

    return collect_status(data_dir=plugin_data_dir("workroom"))


def _wrap(fn: Callable[..., Any]) -> Callable[..., str]:
    def handler(args: dict, **kwargs: Any) -> str:
        try:
            return json.dumps(fn(args))
        except ServiceError as exc:
            return json.dumps({"error": str(exc)})
        except Exception as exc:  # noqa: BLE001  tools must return JSON, never raise
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    return handler


workroom_status = _wrap(lambda a: {**host_status(), "projects": service().projects()})
workroom_add_project = _wrap(lambda a: service().add_project(a["folder"]))
workroom_discover = _wrap(lambda a: service().discover(a["project"]))
workroom_plan = _wrap(lambda a: service().plan(a["project"]))
workroom_explain_figure = _wrap(lambda a: service().explain(a["project"], int(a["link"])))
workroom_selftest = _wrap(lambda a: selftest.run(int(a.get("seed", 7))))
workroom_list_sources = _wrap(lambda a: service().source_cells(a["project"], a.get("query", ""), int(a.get("limit", 60))))
workroom_roll_forward = _wrap(lambda a: _stage_summary({**service().stage_rollforward(a["project"], int(a.get("periods", 1))), "project": a["project"]}))
workroom_find_calculations = _wrap(lambda a: service().calculations(a["project"]))
workroom_create = _wrap(lambda a: _stage_summary({**service().create_from_spec(a["project"], a["spec"]), "project": a["project"]}))
workroom_instructions = _wrap(lambda a: service().instructions_for_agent(a["project"]))
workroom_propose_instruction = _wrap(lambda a: service().propose_instruction(a["project"], a["text"]))
workroom_list_pages = _wrap(lambda a: {"pages": service().scene_list(a["project"])})
workroom_read_page = _wrap(lambda a: service().scene_open(a["project"], a["path"]))
workroom_edit_page = _wrap(lambda a: service().scene_apply(a["project"], a["path"], int(a["rev"]), a["ops"]))
workroom_export_page = _wrap(lambda a: _stage_summary({**service().scene_export(a["project"], a["path"], a["format"]), "project": a["project"]}))
workroom_where_used = _wrap(lambda a: service().where_used(a["project"], a["ref"]))
workroom_what_if = _wrap(lambda a: service().what_if(a["project"], a["ref"], a["value"]))
workroom_stage_release = _wrap(lambda a: _stage_summary({**service().stage(a["project"]), "project": a["project"]}))


def _stage_summary(staged: dict[str, Any]) -> dict[str, Any]:
    staged = dict(staged)
    if staged.get("state") == "refused":
        return staged
    staged.pop("digest", None)  # the digest is shown to the human in the review screen, not handed to the model
    staged["next"] = ("The owner reviews and approves this release in the Workroom screen; nothing is changed until then. "
                      "To show the owner the release inside this chat, write this directive as its own paragraph: " + _directive(staged))
    return staged


def _directive(staged: dict[str, Any]) -> str:
    return '::workroom-release{project="%s" release="%s"}' % (staged.get("project", ""), staged.get("release_id", ""))
