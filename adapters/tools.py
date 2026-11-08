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
workroom_stage_release = _wrap(lambda a: _stage_summary({**service().stage(a["project"]), "project": a["project"]}))


def _stage_summary(staged: dict[str, Any]) -> dict[str, Any]:
    staged = dict(staged)
    staged.pop("digest", None)  # the digest is shown to the human in the review screen, not handed to the model
    staged["next"] = ("The owner reviews and approves this release in the Workroom screen; nothing is changed until then. "
                      "To show the owner the release inside this chat, write this directive as its own paragraph: " + _directive(staged))
    return staged


def _directive(staged: dict[str, Any]) -> str:
    return '::workroom-release{project="%s" release="%s"}' % (staged.get("project", ""), staged.get("release_id", ""))
