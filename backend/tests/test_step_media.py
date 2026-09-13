"""media_asset_ids parsing, FlowStep CRUD, reorder, duplicate, worker multi-send."""

import io
from unittest.mock import patch

from app.models.entities import Customer, ExecutionStatus, Flow, FlowExecution, FlowStep, Page, StepType
from app.services.step_media import dump_media_asset_ids, parse_media_asset_ids
from app.workers.tasks import run_flow_execution


def test_parse_media_asset_ids_effective_list():
    assert parse_media_asset_ids('["a","b"]', None) == ["a", "b"]
    assert parse_media_asset_ids(None, "legacy") == ["legacy"]
    assert parse_media_asset_ids("[]", "legacy") == ["legacy"]
    assert parse_media_asset_ids('["x"]', "legacy") == ["x"]
    assert parse_media_asset_ids(None, None) == []
    assert parse_media_asset_ids("not-json", "legacy") == ["legacy"]
    assert parse_media_asset_ids(["a", "a", "b"], None) == ["a", "b"]
    dumped = dump_media_asset_ids(["u1", "u2"])
    assert dumped == '["u1", "u2"]'
    assert dump_media_asset_ids([]) is None
    # cap at 50
    many = [str(i) for i in range(60)]
    assert len(parse_media_asset_ids(many, None)) == 50


def _upload_png(client, auth_headers, name="pic.png"):
    r = client.post(
        "/api/media/upload",
        headers=auth_headers,
        files={"file": (name, io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 40), "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_flow_step_media_asset_ids_and_reorder(client, auth_headers):
    a1 = _upload_png(client, auth_headers, "one.png")
    a2 = _upload_png(client, auth_headers, "two.png")

    r = client.post(
        "/api/flows",
        headers=auth_headers,
        json={
            "name": "Multi Image Flow",
            "description": "d",
            "steps": [
                {"step_type": "TEXT", "content": "Hi", "delay_seconds": 0},
                {
                    "step_type": "IMAGE",
                    "content": "gallery",
                    "media_asset_ids": [a1["id"], a2["id"]],
                    "delay_seconds": 0,
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    flow = r.json()
    flow_id = flow["id"]
    steps = sorted(flow["steps"], key=lambda s: s["position"])
    assert len(steps) == 2
    img = steps[1]
    assert img["media_asset_ids"] == [a1["id"], a2["id"]]
    assert img["media_asset_id"] == a1["id"]

    # Add a DELAY step then reorder
    r = client.post(
        f"/api/flows/{flow_id}/steps",
        headers=auth_headers,
        json={"step_type": "DELAY", "delay_seconds": 2},
    )
    assert r.status_code == 201
    delay_id = r.json()["id"]

    r = client.get(f"/api/flows/{flow_id}", headers=auth_headers)
    steps = sorted(r.json()["steps"], key=lambda s: s["position"])
    ids = [s["id"] for s in steps]
    # move last to first
    new_order = [ids[-1]] + ids[:-1]
    r = client.post(
        f"/api/flows/{flow_id}/steps/reorder",
        headers=auth_headers,
        json={"step_ids": new_order},
    )
    assert r.status_code == 200, r.text
    reordered = sorted(r.json()["steps"], key=lambda s: s["position"])
    assert [s["id"] for s in reordered] == new_order
    assert reordered[0]["id"] == delay_id

    # PATCH image step — replace media list with one id
    r = client.patch(
        f"/api/flows/{flow_id}/steps/{img['id']}",
        headers=auth_headers,
        json={"media_asset_ids": [a2["id"]], "delay_seconds": 0, "content": "updated"},
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["media_asset_ids"] == [a2["id"]]
    assert patched["media_asset_id"] == a2["id"]
    assert patched["content"] == "updated"

    # Duplicate copies media_asset_ids
    r = client.post(f"/api/flows/{flow_id}/duplicate", headers=auth_headers)
    assert r.status_code == 201
    copy_steps = sorted(r.json()["steps"], key=lambda s: s["position"])
    copy_img = next(s for s in copy_steps if s["step_type"] == "IMAGE")
    assert copy_img["media_asset_ids"] == [a2["id"]]


def test_legacy_single_media_id_reads_as_list(client, auth_headers):
    a1 = _upload_png(client, auth_headers, "legacy.png")
    r = client.post(
        "/api/flows",
        headers=auth_headers,
        json={
            "name": "Legacy Media",
            "steps": [
                {"step_type": "IMAGE", "media_asset_id": a1["id"], "delay_seconds": 0},
            ],
        },
    )
    assert r.status_code == 201, r.text
    step = r.json()["steps"][0]
    assert step["media_asset_id"] == a1["id"]
    assert step["media_asset_ids"] == [a1["id"]]


def test_worker_multi_media_tiny_gap_zero_delay(client, auth_headers, db):
    a1 = _upload_png(client, auth_headers, "w1.png")
    a2 = _upload_png(client, auth_headers, "w2.png")
    a3 = _upload_png(client, auth_headers, "w3.png")

    page = Page(page_id="P-MULTI", name="T", access_token="tok", is_connected=True)
    db.add(page)
    cust = Customer(page_id="P-MULTI", psid="PSID-MULTI", display_name="C")
    db.add(cust)
    db.flush()
    flow = Flow(name="Burst Images", description="", is_active=True)
    db.add(flow)
    db.flush()
    db.add(
        FlowStep(
            flow_id=flow.id,
            position=0,
            step_type=StepType.IMAGE,
            content="burst",
            media_asset_id=a1["id"],
            media_asset_ids=dump_media_asset_ids([a1["id"], a2["id"], a3["id"]]),
            delay_seconds=0,
        )
    )
    db.add(
        FlowStep(
            flow_id=flow.id,
            position=1,
            step_type=StepType.TEXT,
            content="done",
            delay_seconds=0,
        )
    )
    db.commit()

    # Use API send path? Direct execution is more precise for sleep asserts.
    from app.services.flow_engine import start_flow_execution

    with patch("app.workers.tasks.time.sleep") as sleep_mock:
        with patch("app.workers.tasks.MetaClient") as MC:
            inst = MC.return_value
            inst.send_text.return_value = {"message_id": "t1"}
            inst.send_attachment.return_value = {"message_id": "m1"}
            ex = start_flow_execution(db, flow.id, cust.id, user_id=None)
            db.refresh(ex)
            assert ex.status == ExecutionStatus.COMPLETED
            assert inst.send_attachment.call_count == 3
            # micro-gap between 3 images = 2 sleeps; no post-step delay
            gap_calls = [c for c in sleep_mock.call_args_list if c.args and 0 < c.args[0] <= 0.2]
            assert len(gap_calls) == 2
            long_sleeps = [c for c in sleep_mock.call_args_list if c.args and c.args[0] >= 1]
            assert long_sleeps == []
