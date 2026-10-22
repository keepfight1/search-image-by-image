from __future__ import annotations


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "embedding_provider": "lightweight"}


def test_upload_rejects_invalid_and_oversized_files(client):
    invalid = client.post(
        "/api/upload",
        files={"image": ("pet.jpg", b"not an image", "image/jpeg")},
    )
    assert invalid.status_code == 415

    oversized = client.post(
        "/api/upload",
        files={"image": ("pet.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")},
    )
    assert oversized.status_code == 413


def test_publish_and_get_details(client, upload_image, base_payload):
    image_url = upload_image()
    payload = {**base_payload, "type": "lost", "images": [image_url]}
    response = client.post("/api/pets", json=payload)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["type"] == "lost"
    assert created["images"] == [image_url]

    details = client.get(f"/api/pets/{created['id']}")
    assert details.status_code == 200
    assert details.json() == created


def test_searches_opposite_library_in_same_district(client, upload_image, base_payload):
    image_url = upload_image()
    sighting = {**base_payload, "type": "sighting", "images": [image_url]}
    created = client.post("/api/sightings", json=sighting)
    assert created.status_code == 201, created.text

    query_url = upload_image()
    query = {
        **{key: value for key, value in base_payload.items() if key != "contact"},
        "type": "lost",
        "images": [query_url],
        "top_k": 5,
    }
    response = client.post("/api/search", json=query)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expanded"] is False
    assert body["message"] == ""
    assert body["results"][0]["id"] == created.json()["id"]
    assert body["results"][0]["distance"] == 0.0
    assert body["results"][0]["score"] >= 0.999


def test_search_auto_expands_to_same_city(client, upload_image, base_payload):
    gallery_url = upload_image(color=(40, 100, 200))
    sighting = {
        **base_payload,
        "type": "sighting",
        "images": [gallery_url],
        "event_district": "徐汇区",
    }
    created = client.post("/api/sightings", json=sighting)
    assert created.status_code == 201, created.text

    query_url = upload_image(color=(40, 100, 200))
    query = {
        **{key: value for key, value in base_payload.items() if key != "contact"},
        "type": "lost",
        "images": [query_url],
        "top_k": 5,
    }
    response = client.post("/api/search", json=query)
    assert response.status_code == 200, response.text
    assert response.json()["expanded"] is True
    assert response.json()["results"][0]["district"] == "徐汇区"


def test_search_does_not_cross_city(client, upload_image, base_payload):
    gallery_url = upload_image()
    sighting = {
        **base_payload,
        "type": "sighting",
        "images": [gallery_url],
        "event_city": "杭州",
        "event_district": "西湖区",
    }
    assert client.post("/api/sightings", json=sighting).status_code == 201

    query_url = upload_image()
    query = {
        **{key: value for key, value in base_payload.items() if key != "contact"},
        "type": "lost",
        "images": [query_url],
        "top_k": 5,
    }
    response = client.post("/api/search", json=query)
    assert response.status_code == 200
    assert response.json() == {"results": [], "expanded": True, "message": "暂无可靠线索"}


def test_image_cannot_be_attached_to_two_records(client, upload_image, base_payload):
    image_url = upload_image()
    first = {**base_payload, "type": "lost", "images": [image_url]}
    assert client.post("/api/pets", json=first).status_code == 201

    second = {**base_payload, "type": "sighting", "images": [image_url]}
    response = client.post("/api/sightings", json=second)
    assert response.status_code == 409
    assert "已绑定" in response.json()["detail"]


def test_validation_requires_coordinate_pair(client, upload_image, base_payload):
    image_url = upload_image()
    payload = {
        **base_payload,
        "type": "lost",
        "images": [image_url],
        "event_lng": None,
    }
    response = client.post("/api/pets", json=payload)
    assert response.status_code == 422
