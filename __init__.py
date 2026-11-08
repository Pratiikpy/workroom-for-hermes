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
    # The read-only toolset is what a verifying sub-agent is given: it can look, never change anything.
    ("workroom_plan", tools.PLAN_SCHEMA, tools.workroom_plan, "Preview what a refresh would change.", READ_ONLY_TOOLSET),
    ("workroom_selftest", tools.SELFTEST_SCHEMA, tools.workroom_selftest, "Run the bundled self-test.", READ_ONLY_TOOLSET),
    ("workroom_explain_figure", tools.EXPLAIN_SCHEMA, tools.workroom_explain_figure, "Explain where a number came from.", READ_ONLY_TOOLSET),
)


def register(ctx):
    from .adapters.commands import make_approve_command

    def _service():
        svc = tools.service()
        svc.approvers = frozenset(str(a) for a in (ctx.get_config("approvers", []) or []))
        return svc

    from .adapters.guard import make_guard

    ctx.register_hook("pre_tool_call", make_guard(lambda: [p["folder"] for p in tools.service().projects()]))
    ctx.register_command(
        "workroom-approve",
        make_approve_command(_service, ctx.ask_choice, lambda: ctx.get_config("approvers", [])),
        description="Approve a prepared Workroom release from this chat.",
        args_hint="[<project> <release>]",
    )
    for name, schema, handler, description, toolset in TOOLS:
        ctx.register_tool(name=name, toolset=toolset, schema=schema, handler=handler, description=description)
