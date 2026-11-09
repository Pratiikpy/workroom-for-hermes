import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# This file is loaded on its own by the Hermes web server, so the plugin folder is added to the import path
# to reach the kernel package.
_PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from workroom_core.service import NeedsAcknowledgement, Service, ServiceError  # noqa: E402
from workroom_core.status import collect_status  # noqa: E402

router = APIRouter()


def _service() -> Service:
    from plugins.plugin_storage import plugin_data_dir

    return Service(plugin_data_dir("workroom"))


class FolderBody(BaseModel):
    folder: str = Field(min_length=1, max_length=1024)


class ProjectBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)


class TieBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    tie_id: int = Field(ge=1)


class ReleaseBody(BaseModel):
    project: str = Field(pattern=r"^[0-9a-f]{12}$")
    release_id: str = Field(pattern=r"^[0-9a-f]{16}$")


class RollBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    periods: int = Field(default=1, ge=1, le=4)


class CalcBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    candidate: str = Field(pattern=r"^[0-9a-f]{20}$")
    option: int = Field(default=0, ge=0, le=9)


class FindingBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    finding: str = Field(pattern=r"^[0-9a-f]{20}$")
    decision: str = Field(pattern=r"^(dismissed|acknowledged)$")


class ApproveBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    release_id: str = Field(min_length=1, max_length=64)
    digest: str = Field(min_length=64, max_length=64)
    acknowledge: bool = False


def _guard(fn):
    try:
        return fn()
    except NeedsAcknowledgement as exc:
        raise HTTPException(status_code=409, detail={"needs_acknowledgement": True, "message": str(exc), "flags": exc.flags}) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
async def status() -> dict:
    from plugins.plugin_storage import plugin_data_dir

    return collect_status(data_dir=plugin_data_dir("workroom"))


@router.get("/projects")
async def projects() -> list:
    return _service().projects()


@router.post("/projects")
async def add_project(body: FolderBody) -> dict:
    return _guard(lambda: _service().add_project(body.folder))


@router.post("/discover")
async def discover(body: ProjectBody) -> dict:
    return _guard(lambda: _service().discover(body.project))


@router.post("/ties")
async def ties(body: ProjectBody) -> list:
    return _guard(lambda: _service().ties(body.project))


@router.post("/confirm")
async def confirm(body: TieBody) -> dict:
    _guard(lambda: _service().confirm(body.project, body.tie_id))
    return {"ok": True}


@router.post("/skip")
async def skip(body: TieBody) -> dict:
    _guard(lambda: _service().skip(body.project, body.tie_id))
    return {"ok": True}


@router.post("/explain")
async def explain(body: TieBody) -> dict:
    return _guard(lambda: _service().explain(body.project, body.tie_id))


@router.post("/release")
async def release(body: ReleaseBody) -> dict:
    return _guard(lambda: _service().release_view(body.project, body.release_id))


@router.post("/plan")
async def plan(body: ProjectBody) -> dict:
    return _guard(lambda: _service().plan(body.project))


@router.post("/changes")
async def changes(body: ProjectBody) -> dict:
    return _guard(lambda: _service().changes_inbox(body.project))


@router.post("/change-map")
async def change_map(body: ProjectBody) -> dict:
    return _guard(lambda: _service().change_map(body.project))


@router.post("/awaiting")
async def awaiting(body: ProjectBody) -> list:
    return _guard(lambda: _service().awaiting(body.project))


class InstructionBody(BaseModel):
    project: str
    name: str = ""
    sha: str = ""
    proposal: str = ""


@router.post("/instructions")
async def instructions(body: ProjectBody) -> dict:
    return _guard(lambda: {**_service().instructions(body.project), "proposals": _service().proposals(body.project)})


@router.post("/instruction-read")
async def instruction_read(body: InstructionBody) -> dict:
    return _guard(lambda: _service().read_instruction(body.project, body.name))


@router.post("/instruction-authorise")
async def instruction_authorise(body: InstructionBody) -> dict:
    return _guard(lambda: _service().authorise_instruction(body.project, body.name, body.sha))


@router.post("/instruction-apply")
async def instruction_apply(body: InstructionBody) -> dict:
    return _guard(lambda: _service().apply_instruction_proposal(body.project, body.proposal))


class ReviewBody(BaseModel):
    project: str
    deck: str = ""
    side: str = "before"
    page: int = 1


@router.post("/review")
async def review(body: ReviewBody) -> dict:
    return _guard(lambda: _service().review_overview(body.project))


@router.post("/review-pages")
async def review_pages(body: ReviewBody) -> dict:
    return _guard(lambda: _service().review_pages(body.project, body.deck))


@router.post("/review-page")
async def review_page(body: ReviewBody) -> dict:
    return _guard(lambda: _service().review_page(body.project, body.deck, body.side, body.page))


@router.post("/review-structural")
async def review_structural(body: ReviewBody) -> dict:
    return _guard(lambda: _service().review_structural(body.project, body.deck))


class ColumnBody(BaseModel):
    project: str
    signature: str = ""
    file: str = ""
    sheet: str = ""
    column: int = 0


@router.post("/column-questions")
async def column_questions(body: ColumnBody) -> list:
    return _guard(lambda: _service().column_questions(body.project))


@router.post("/column-choose")
async def column_choose(body: ColumnBody) -> dict:
    return _guard(lambda: _service().choose_column(body.project, body.signature, body.file, body.sheet, body.column))


class RecipeBody(BaseModel):
    project: str
    deck: str = ""
    proposal: str = ""
    digest: str = ""


@router.post("/recipe")
async def recipe_status(body: RecipeBody) -> dict:
    return _guard(lambda: _service().recipe_status(body.project))


@router.post("/recipe-propose")
async def recipe_propose(body: RecipeBody) -> dict:
    return _guard(lambda: _service().recipe_propose(body.project, body.deck))


@router.post("/recipe-approve")
async def recipe_approve(body: RecipeBody) -> dict:
    return _guard(lambda: _service().recipe_approve(body.project, body.proposal, body.digest))


@router.post("/recipe-revoke")
async def recipe_revoke(body: RecipeBody) -> dict:
    return _guard(lambda: _service().recipe_revoke(body.project))


class SceneBody(BaseModel):
    project: str
    path: str = ""
    rev: int = 0
    ops: list = Field(default_factory=list)


@router.get("/scene-frame")
async def scene_frame() -> dict:
    from pathlib import Path

    return {"doc": (Path(__file__).with_name("canvas.html")).read_text(encoding="utf-8")}


@router.post("/scenes")
async def scenes(body: ProjectBody) -> list:
    return _guard(lambda: _service().scene_list(body.project))


@router.post("/scene-open")
async def scene_open(body: SceneBody) -> dict:
    return _guard(lambda: _service().scene_open(body.project, body.path))


@router.post("/scene-apply")
async def scene_apply(body: SceneBody) -> dict:
    return _guard(lambda: _service().scene_apply(body.project, body.path, body.rev, body.ops))


@router.post("/scene-save")
async def scene_save(body: SceneBody) -> dict:
    return _guard(lambda: _service().scene_save(body.project, body.path))


@router.post("/scene-discard")
async def scene_discard(body: SceneBody) -> dict:
    return _guard(lambda: _service().scene_discard(body.project, body.path))


@router.post("/sample")
async def sample() -> dict:
    return _guard(lambda: _service().create_sample())


@router.post("/sample-next")
async def sample_next(body: ProjectBody) -> dict:
    return _guard(lambda: _service().sample_next_quarter(body.project))


@router.post("/proof")
async def proof(body: ReleaseBody) -> dict:
    return _guard(lambda: _service().render_proof(body.project, body.release_id))


@router.post("/stage")
async def stage(body: ProjectBody) -> dict:
    return _guard(lambda: _service().stage(body.project))


class AcceptHistoryBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    seen: dict[str, int] | None = None


@router.post("/history")
async def history(body: ProjectBody) -> dict:
    return _guard(lambda: _service().history_review(body.project))


@router.post("/accept-history")
async def accept_history(body: AcceptHistoryBody) -> dict:
    """Owner action: like /approve it is not an agent tool and needs an authenticated Hermes session."""
    return _guard(lambda: _service().accept_history(body.project, body.seen))


class SettingsBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    tracked_changes: bool | None = None


@router.post("/settings")
async def settings(body: SettingsBody) -> dict:
    if body.tracked_changes is None:
        return _guard(lambda: _service().settings(body.project))
    return _guard(lambda: _service().set_settings(body.project, body.tracked_changes))


@router.post("/releases")
async def releases(body: ProjectBody) -> list:
    return _guard(lambda: _service().releases(body.project))


@router.post("/restore")
async def restore(body: ReleaseBody) -> dict:
    """Owner action: like /approve it is not an agent tool and needs an authenticated Hermes session."""
    return _guard(lambda: _service().restore_release(body.project, body.release_id))


@router.post("/approve")
async def approve(body: ApproveBody) -> dict:
    """The only route that approves and publishes. It is not an agent tool; it needs an authenticated Hermes session."""
    return _guard(lambda: _service().approve_and_publish(body.project, body.release_id, body.digest, acknowledge=body.acknowledge))


@router.post("/calculations")
async def calculations(body: ProjectBody) -> dict:
    return _guard(lambda: _service().calculations(body.project))


@router.post("/calculation-accept")
async def calculation_accept(body: CalcBody) -> dict:
    return _guard(lambda: _service().accept_calculation(body.project, body.candidate, body.option))


@router.post("/calculations-accept-certain")
async def calculations_accept_certain(body: ProjectBody) -> dict:
    return _guard(lambda: _service().accept_certain_calculations(body.project))


@router.post("/calculation-dismiss")
async def calculation_dismiss(body: CalcBody) -> dict:
    return _guard(lambda: _service().dismiss_calculation(body.project, body.candidate))


@router.post("/finding-decision")
async def finding_decision(body: FindingBody) -> dict:
    """Owner action: like /approve it is not an agent tool and needs an authenticated Hermes session."""
    return _guard(lambda: _service().decide_finding(body.project, body.finding, body.decision))


@router.post("/stage-rollforward")
async def stage_rollforward(body: RollBody) -> dict:
    """Prepares a release that moves the documents to the next reporting period. It approves nothing."""
    return _guard(lambda: _service().stage_rollforward(body.project, body.periods))
