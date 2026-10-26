from __future__ import annotations

from io import BytesIO

from PIL import Image


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), (230, 120, 30)).save(output, format="JPEG")
    return output.getvalue()


def _auth(client, username: str) -> dict[str, str]:
    payload = {"username": username, "password": "long-enough-secret"}
    assert client.post("/api/v2/auth/register", json=payload).status_code == 201
    response = client.post("/api/v2/auth/login", json=payload)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v2/images",
        files={"image": ("cat.jpg", image_bytes(), "image/jpeg")},
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
