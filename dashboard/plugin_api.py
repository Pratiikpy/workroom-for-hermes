import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# This file is loaded on its own by the Hermes web server, so the plugin folder is added to the import path
# to reach the kernel package.
_PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from workroom_core.service import Service, ServiceError  # noqa: E402
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


class ApproveBody(BaseModel):
    project: str = Field(min_length=1, max_length=64)
    release_id: str = Field(min_length=1, max_length=64)
    digest: str = Field(min_length=64, max_length=64)


def _guard(fn):
    try:
        return fn()
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
    return _guard(lambda: _service().approve_and_publish(body.project, body.release_id, body.digest))
