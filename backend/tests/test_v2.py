from __future__ import annotations

from io import BytesIO

from PIL import Image


def image_bytes(color=(230, 120, 30)) -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format="JPEG")
    return output.getvalue()


def _auth(client, username: str) -> dict[str, str]:
    payload = {"username": username, "password": "long-enough-secret"}
    assert client.post("/api/v2/auth/register", json=payload).status_code == 201
    response = client.post("/api/v2/auth/login", json=payload)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client, auth: dict[str, str], color=(230, 120, 30)) -> str:
    response = client.post(
        "/api/v2/images",
        files={"image": ("cat.jpg", image_bytes(color), "image/jpeg")},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()["image_url"]


def test_authenticated_cat_reports_and_private_contact(client, upload_image, base_payload):
    finder = _auth(client, "finder_01")
    owner = _auth(client, "owner_01")
    image = _upload(client, finder)
    sighting = {**base_payload, "species": "cat", "type": "sighting", "images": [image]}
    created = client.post("/api/v2/reports/sighting", json=sighting, headers=finder)
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]
    assert "contact" not in created.json()

    public = client.get(f"/api/v2/reports/sighting/{report_id}")
    assert public.status_code == 200
    assert "contact" not in public.json()
    assert "owner_user_id" not in public.json()
    assert "event_lat" not in public.json()
    assert "event_lng" not in public.json()

    query_image = _upload(client, owner)
    lost = {**base_payload, "species": "cat", "type": "lost", "images": [query_image]}
    lost_response = client.post("/api/v2/reports/lost", json=lost, headers=owner)
    assert lost_response.status_code == 201, lost_response.text
    matches = client.get(f"/api/v2/reports/lost/{lost_response.json()['id']}/matches", headers=owner)
    assert matches.status_code == 200, matches.text
    assert matches.json()["results"][0]["id"] == report_id
    assert "contact" not in matches.json()["results"][0]
    assert client.get(f"/api/v2/reports/lost/{lost_response.json()['id']}/matches", headers=finder).status_code == 403

    distant = {**sighting, "images": [_upload(client, finder)], "event_city": "杭州", "event_district": "西湖区"}
    distant_created = client.post("/api/v2/reports/sighting", json=distant, headers=finder)
    assert distant_created.status_code == 201, distant_created.text
    local_ids = {item["id"] for item in matches.json()["results"]}
    assert distant_created.json()["id"] not in local_ids
    expanded = client.get(f"/api/v2/reports/lost/{lost_response.json()['id']}/matches?expand=true", headers=owner)
    assert expanded.status_code == 200
    assert expanded.json()["scope"] == "all_cities"
    assert distant_created.json()["id"] in {item["id"] for item in expanded.json()["results"]}

    message = {"target_type": "sighting", "target_id": report_id, "message": "我认为这是我丢失的猫，可以核对照片吗？"}
    contact = client.post("/api/v2/contact-requests", json=message, headers=owner)
    assert contact.status_code == 201, contact.text
    assert client.post("/api/v2/contact-requests", json=message, headers=owner).status_code == 409
    reply = client.post(
        f"/api/v2/contact-requests/{contact.json()['id']}/reply",
        json={"reply": "请提供猫的正脸照片核对。"},
        headers=finder,
    )
    assert reply.status_code == 200, reply.text
    inbox = client.get("/api/v2/me/contact-requests", headers=owner)
    assert inbox.json()["items"][0]["state"] == "replied"

    assert client.patch(f"/api/v2/reports/sighting/{report_id}/status", json={"status": "resolved"}, headers=owner).status_code == 404
    assert client.patch(f"/api/v2/reports/sighting/{report_id}/status", json={"status": "resolved"}, headers=finder).status_code == 200
    assert client.get(f"/api/v2/reports/sighting/{report_id}").status_code == 404
    assert client.get("/api/v2/reports?type=sighting&city=上海").json()["items"] == []


def test_cat_only_and_auth_required(client, upload_image, base_payload):
    image = upload_image()
    report = {**base_payload, "type": "lost", "species": "cat", "images": [image]}
    assert client.post("/api/v2/reports/lost", json=report).status_code == 401
    auth = _auth(client, "owner_02")
    assert client.post("/api/v2/reports/lost", json={**report, "species": "dog"}, headers=auth).status_code == 422
    assert client.post("/api/v2/reports/lost", json=report, headers=auth).status_code == 403
    report["images"] = [_upload(client, auth)]
    assert client.post("/api/v2/reports/lost", json=report, headers=auth).status_code == 201


def test_v2_upload_requires_login(client):
    files = {"image": ("cat.jpg", image_bytes(), "image/jpeg")}
    assert client.post("/api/v2/images", files=files).status_code == 401
    auth = _auth(client, "uploader_01")
    response = client.post("/api/v2/images", files=files, headers=auth)
    assert response.status_code == 201
    assert response.json()["image_url"].startswith("/uploads/")


def test_edit_and_replace_image_keeps_owner_permissions(client, base_payload):
    finder = _auth(client, "editor_finder")
    stranger = _auth(client, "editor_stranger")
    old_image = _upload(client, finder)
    payload = {**base_payload, "species": "cat", "type": "sighting", "images": [old_image]}
    created = client.post("/api/v2/reports/sighting", json=payload, headers=finder)
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]
    url = f"/api/v2/reports/sighting/{report_id}"
    assert client.patch(url, json={"event_district": "新城区"}, headers=stranger).status_code == 403
    new_image = _upload(client, finder, color=(20, 80, 190))
    edit = client.patch(url, json={"images": [new_image], "event_district": "新城区"}, headers=finder)
    assert edit.status_code == 200, edit.text
    assert edit.json()["images"] == [new_image]
    assert edit.json()["event_district"] == "新城区"
    assert "event_lat" not in edit.json()
    mine = client.get("/api/v2/me/reports", headers=finder).json()["items"][0]
    assert mine["event_lat"] == base_payload["event_lat"]
    assert client.patch(url, json={"images": [_upload(client, stranger)]}, headers=finder).status_code == 403
    assert client.patch(url + "/status", json={"status": "resolved"}, headers=finder).status_code == 200
    assert client.patch(url, json={"event_district": "再编辑"}, headers=finder).status_code == 409


def test_report_and_admin_hide_removes_public_record(client, base_payload):
    owner = _auth(client, "mod_owner")
    reporter = _auth(client, "mod_reporter")
    admin = _auth(client, "mod_admin")
    assert client.app.state.database.set_user_role("mod_admin", "admin")
    report = {**base_payload, "type": "sighting", "species": "cat", "images": [_upload(client, owner)]}
    created = client.post("/api/v2/reports/sighting", json=report, headers=owner)
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    url = f"/api/v2/reports/sighting/{target_id}/report"
    flagged = client.post(url, json={"reason": "这条目击信息使用了虚假的图片和地点"}, headers=reporter)
    assert flagged.status_code == 201, flagged.text
    assert client.post(url, json={"reason": "重复举报这条明显虚假的线索"}, headers=reporter).status_code == 409
    assert client.get("/api/v2/admin/reports", headers=reporter).status_code == 403
    queue = client.get("/api/v2/admin/reports", headers=admin)
    assert queue.status_code == 200
    assert queue.json()["items"][0]["id"] == flagged.json()["id"]
    reviewed = client.patch(f"/api/v2/admin/reports/{flagged.json()['id']}", json={"action": "hide"}, headers=admin)
    assert reviewed.status_code == 200
    assert client.get(f"/api/v2/reports/sighting/{target_id}").status_code == 404
    assert client.get("/api/v2/reports?type=sighting").json()["items"] == []
