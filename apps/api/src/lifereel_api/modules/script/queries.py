from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.modules.script.models import ScriptProject, ScriptScene, ScriptShot

# Bound IN parameters even on SQLite builds with the legacy 999-variable limit.
_PROJECT_BATCH_SIZE = 500


def project_contents(
    db: Session, tenant_id: UUID, projects: Sequence[ScriptProject],
) -> list[tuple[ScriptProject, list[ScriptScene], list[ScriptShot]]]:
    """Load list children in batches, retaining the detail endpoint's ordering."""
    result = []
    for offset in range(0, len(projects), _PROJECT_BATCH_SIZE):
        batch = projects[offset:offset + _PROJECT_BATCH_SIZE]
        project_ids = [project.id for project in batch]
        scenes_by_project: dict[UUID, list[ScriptScene]] = {key: [] for key in project_ids}
        shots_by_project: dict[UUID, list[ScriptShot]] = {key: [] for key in project_ids}
        scene_projects = {}
        for scene in db.scalars(
            select(ScriptScene)
            .where(ScriptScene.project_id.in_(project_ids), ScriptScene.tenant_id == tenant_id)
            .order_by(ScriptScene.order_index)
        ):
            scenes_by_project[scene.project_id].append(scene)
            scene_projects[scene.id] = scene.project_id
        if scene_projects:
            # Join through the same tenant-owned scenes as get_project; avoid an
            # unbounded IN list when a single project has many scenes.
            for shot in db.scalars(
                select(ScriptShot)
                .join(ScriptScene, ScriptShot.scene_id == ScriptScene.id)
                .where(ScriptScene.project_id.in_(project_ids), ScriptScene.tenant_id == tenant_id)
                .order_by(ScriptShot.scene_id, ScriptShot.order_index)
            ):
                project_id = scene_projects.get(shot.scene_id)
                # A concurrent insert may add a scene after our scene snapshot.
                if project_id is not None:
                    shots_by_project[project_id].append(shot)
        result.extend(
            (project, scenes_by_project[project.id], shots_by_project[project.id])
            for project in batch
        )
    return result
