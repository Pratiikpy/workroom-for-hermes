import logging

from .adapters import tools

logger = logging.getLogger(__name__)


READ_ONLY_TOOLSET = "workroom_ro"
FULL_TOOLSET = "workroom"

TOOLS = (
    # (name, schema, handler, description, toolset)
    ("workroom_status", tools.STATUS_SCHEMA, tools.workroom_status, "Report Workroom's version, storage location and readiness.", FULL_TOOLSET),
    ("workroom_add_project", tools.ADD_PROJECT_SCHEMA, tools.workroom_add_project, "Register a folder of Office files as a project.", FULL_TOOLSET),
    ("workroom_discover", tools.DISCOVER_SCHEMA, tools.workroom_discover, "Link numbers in documents to their source cells.", FULL_TOOLSET),
    ("workroom_stage_release", tools.STAGE_SCHEMA, tools.workroom_stage_release, "Prepare a release for the owner to approve.", FULL_TOOLSET),
    ("workroom_roll_forward", tools.ROLL_SCHEMA, tools.workroom_roll_forward, "Prepare a release that rolls the documents to the next reporting period.", FULL_TOOLSET),
    ("workroom_find_calculations", tools.CALCULATIONS_SCHEMA, tools.workroom_find_calculations, "List calculated numbers (percent change, margin, difference, total) found in the documents.", READ_ONLY_TOOLSET),
    ("workroom_create", tools.CREATE_SCHEMA, tools.workroom_create, "Create a deck or report whose figures are tied to source cells, staged for approval.", FULL_TOOLSET),
    ("workroom_propose_instruction", tools.PROPOSE_INSTRUCTION_SCHEMA, tools.workroom_propose_instruction, "Propose a change to workroom.md for the owner to review.", FULL_TOOLSET),
    ("workroom_edit_page", tools.EDIT_PAGE_SCHEMA, tools.workroom_edit_page, "Edit a visual page as a draft for the owner to save.", FULL_TOOLSET),
    ("workroom_export_page", tools.EXPORT_PAGE_SCHEMA, tools.workroom_export_page, "Stage an export of a visual page for approval.", FULL_TOOLSET),
    # The read-only toolset is what a verifying sub-agent is given: it can look, never change anything.
    ("workroom_plan", tools.PLAN_SCHEMA, tools.workroom_plan, "Preview what a refresh would change.", READ_ONLY_TOOLSET),
    ("workroom_selftest", tools.SELFTEST_SCHEMA, tools.workroom_selftest, "Run the bundled self-test.", READ_ONLY_TOOLSET),
    ("workroom_list_sources", tools.SOURCES_SCHEMA, tools.workroom_list_sources, "List source cells with their labels.", READ_ONLY_TOOLSET),
    ("workroom_instructions", tools.INSTRUCTIONS_SCHEMA, tools.workroom_instructions, "Read the owner-authorised project instructions.", READ_ONLY_TOOLSET),
    ("workroom_list_pages", tools.PAGES_SCHEMA, tools.workroom_list_pages, "List visual pages.", READ_ONLY_TOOLSET),
    ("workroom_read_page", tools.READ_PAGE_SCHEMA, tools.workroom_read_page, "Read a visual page.", READ_ONLY_TOOLSET),
    ("workroom_where_used", tools.WHERE_USED_SCHEMA, tools.workroom_where_used, "Where is a source cell used.", READ_ONLY_TOOLSET),
    ("workroom_what_if", tools.WHAT_IF_SCHEMA, tools.workroom_what_if, "What would change if a cell had another value.", READ_ONLY_TOOLSET),
    ("workroom_explain_figure", tools.EXPLAIN_SCHEMA, tools.workroom_explain_figure, "Explain where a number came from.", READ_ONLY_TOOLSET),
    ("workroom_release_record", tools.RECORD_SCHEMA, tools.workroom_release_record, "The record of one published release.", READ_ONLY_TOOLSET),
    ("workroom_recipe_status", tools.RECIPE_STATUS_SCHEMA, tools.workroom_recipe_status, "Which recipe is active for a project.", READ_ONLY_TOOLSET),
    ("workroom_recipe_propose", tools.RECIPE_PROPOSE_SCHEMA, tools.workroom_recipe_propose, "Propose a report as the model for a recurring report.", FULL_TOOLSET),
    ("workroom_room_read", tools.ROOM_READ_SCHEMA, tools.workroom_room_read, "Read the project's Room: authorised instructions, sources, approved memory.", READ_ONLY_TOOLSET),
    ("workroom_room_add_source", tools.ROOM_SOURCE_SCHEMA, tools.workroom_room_add_source, "Add a source (file, folder, link or note) to the project's Room.", FULL_TOOLSET),
    ("workroom_room_remember", tools.ROOM_REMEMBER_SCHEMA, tools.workroom_room_remember, "Propose something for the project's Room memory; the owner decides.", FULL_TOOLSET),
    ("workroom_attention", tools.ATTENTION_SCHEMA, tools.workroom_attention, "What waits for the owner across all projects.", READ_ONLY_TOOLSET),
    ("workroom_deliverable_register", tools.DELIVERABLE_SCHEMA, tools.workroom_deliverable_register, "List a file you produced as a deliverable for the owner to review.", FULL_TOOLSET),
)


def register(ctx):
    from .adapters.commands import make_approve_command, make_watch_command

    def _service():
        svc = tools.service()
        svc.approvers = frozenset(str(a) for a in (ctx.get_config("approvers", []) or []))
        return svc

    from .adapters.guard import make_guard

    ctx.register_hook("pre_tool_call", make_guard(lambda: [p["folder"] for p in tools.service().projects()]))
    from .adapters.workspace_guard import make_workspace_guard

    ctx.register_hook("pre_tool_call", make_workspace_guard(lambda: tools.service().projects(), lambda pid: tools.service().room_policy(pid)))
    from .adapters.snapshotter import make_snapshotter

    ctx.register_hook("pre_tool_call", make_snapshotter(lambda: tools.service().projects(), lambda pid, path, tool: tools.service().snapshot_take(pid, path, tool)))
    from .adapters.room_context import make_room_context

    ctx.register_hook("pre_llm_call", make_room_context(lambda: tools.service().projects(), lambda pid: tools.service().room_read(pid)))
    ctx.register_command(
        "workroom-approve",
        make_approve_command(_service, ctx.ask_choice, lambda: ctx.get_config("approvers", [])),
        description="Approve a prepared Workroom release from this chat.",
        args_hint="[<project> <release>]",
    )
    ctx.register_command(
        "workroom-watch",
        make_watch_command(_service),
        description="Show how to have Hermes cron check a Workroom project on a schedule.",
        args_hint="<project>",
    )
    for name, schema, handler, description, toolset in TOOLS:
        ctx.register_tool(name=name, toolset=toolset, schema=schema, handler=handler, description=description)
