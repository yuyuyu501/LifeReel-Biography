from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from lifereel_api.core.database import SessionLocal, engine
from lifereel_api.core.tenant import get_tenant_id
from lifereel_api.main import app
from lifereel_api.modules.identity.models import Person, Tenant
from lifereel_api.modules.script import queries
from lifereel_api.modules.script.models import ScriptProject, ScriptScene, ScriptShot


@contextmanager
def statements():
    executed = []

    def record(conn, cursor, statement, parameters, context, executemany):
        executed.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield executed
    finally:
        event.remove(engine, "before_cursor_execute", record)


def seed_projects(db, tenant_id, count):
    db.add(Tenant(id=tenant_id, name="List queries", slug=str(tenant_id)))
    db.flush()
    ids = []
    for index in range(count):
        person = Person(tenant_id=tenant_id, display_name=f"Person {index}")
        db.add(person)
        db.flush()
        project = ScriptProject(
            tenant_id=tenant_id, subject_id=person.id, title=f"Project {index}",
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        )
        db.add(project)
        db.flush()
        ids.append(project.id)
        # Reverse scene UUID order relative to narrative order: shots are ordered by UUID.
        scene_id_base = uuid4().int // 4 * 4
        for order_index in (2, 1):
            scene = ScriptScene(
                id=UUID(int=scene_id_base + (3 - order_index)),
                tenant_id=tenant_id, project_id=project.id, order_index=order_index,
                heading=f"Scene {order_index}", narration="Narration", visual_prompt="Visual",
                reference_asset_ids=[] if order_index == 1 else None,
                plot="Plot", dialogues=[{"kind": "narration", "speaker": "Me", "text": "Text"}],
            )
            db.add(scene)
            db.flush()
            for shot_order in (2, 1):
                db.add(ScriptShot(
                    tenant_id=tenant_id, scene_id=scene.id, order_index=shot_order,
                    visual_prompt=f"Shot {shot_order}", source_claim_ids=[str(uuid4())],
                ))
    db.commit()
    return ids


@pytest.mark.parametrize("count,batch_size,expected_queries", [(1, 500, 3), (8, 500, 3), (5, 2, 7)])
def test_list_has_bounded_queries_and_matches_detail(
    client, monkeypatch, count, batch_size, expected_queries,
):
    monkeypatch.setattr(queries, "_PROJECT_BATCH_SIZE", batch_size)
    tenant_id, other_tenant = uuid4(), uuid4()
    with SessionLocal() as db:
        ids = seed_projects(db, tenant_id, count + 1)
        db.get(ScriptProject, ids.pop()).status = "superseded"
        db.commit()
        seed_projects(db, other_tenant, 1)
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    try:
        with statements() as executed:
            response = client.get("/v1/scripts")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [item["id"] for item in payload] == [str(item) for item in reversed(ids)]
        for item in payload:
            assert item == client.get(f"/v1/scripts/{item['id']}").json()
            assert [scene["order_index"] for scene in item["scenes"]] == [1, 2]
            assert [(shot["scene_id"], shot["order_index"]) for shot in item["shots"]] == sorted(
                (shot["scene_id"], shot["order_index"]) for shot in item["shots"]
            )
        assert all(sql.lstrip().upper().startswith("SELECT") for sql in executed)
        assert len(executed) == expected_queries, executed
    finally:
        app.dependency_overrides.pop(get_tenant_id)


def test_list_preserves_empty_children_and_filters_foreign_scenes(client):
    tenant_id, other_tenant = uuid4(), uuid4()
    with SessionLocal() as db:
        ids = seed_projects(db, tenant_id, 2)
        other_ids = seed_projects(db, other_tenant, 1)
        for scene in db.query(ScriptScene).filter(ScriptScene.project_id == ids[0]):
            for shot in db.query(ScriptShot).filter(ScriptShot.scene_id == scene.id):
                db.delete(shot)
            db.delete(scene)
        for scene in db.query(ScriptScene).filter(ScriptScene.project_id == ids[1]):
            for shot in db.query(ScriptShot).filter(ScriptShot.scene_id == scene.id):
                db.delete(shot)
        # Even malformed legacy child ownership must not leak foreign scenes/shots.
        foreign_scene = db.query(ScriptScene).filter(
            ScriptScene.project_id == other_ids[0],
        ).first()
        foreign_scene.project_id = ids[0]
        db.commit()
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    try:
        response = client.get("/v1/scripts")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        assert [len(item["scenes"]) for item in payload] == [2, 0]
        assert all(item["shots"] == [] for item in payload)
        for item in payload:
            assert item == client.get(f"/v1/scripts/{item['id']}").json()
    finally:
        app.dependency_overrides.pop(get_tenant_id)


def test_empty_list_only_reads_projects(client):
    app.dependency_overrides[get_tenant_id] = uuid4
    try:
        with statements() as executed:
            response = client.get("/v1/scripts")
        assert response.status_code == 200
        assert response.json() == []
        assert len(executed) == 1
        assert executed[0].lstrip().upper().startswith("SELECT")
    finally:
        app.dependency_overrides.pop(get_tenant_id)
