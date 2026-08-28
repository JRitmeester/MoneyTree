"""Tests for allocation bucket CRUD and lifecycle integration.

Spec: docs/superpowers/specs/2026-08-28-salary-allocation-design.md,
sections "Data model", "Validation rules", "Bucket CRUD".
"""
from sqlalchemy.orm import Session

from app.models import AllocationBucket, Category


def _create(client, **overrides):
    payload = {"name": "Long-term savings", "rule_type": "percent", "value": 50.0}
    payload.update(overrides)
    return client.post("/api/allocation-buckets", json=payload)


class TestBucketCrud:
    def test_create_and_list_ordered_by_position(self, client):
        assert _create(client, name="Investing", rule_type="fixed", value=300).status_code == 200
        assert _create(client, name="Long-term", rule_type="percent", value=50).status_code == 200

        rows = client.get("/api/allocation-buckets").json()
        assert [r["name"] for r in rows] == ["Investing", "Long-term"]
        assert [r["position"] for r in rows] == [0, 1]
        assert rows[0]["rule_type"] == "fixed"
        assert rows[0]["is_active"] is True
        assert rows[0]["category_id"] is None

    def test_create_rejects_duplicate_name(self, client):
        assert _create(client).status_code == 200
        resp = _create(client)
        assert resp.status_code == 409

    def test_create_rejects_blank_name(self, client):
        assert _create(client, name="   ").status_code == 422

    def test_create_rejects_bad_values(self, client):
        assert _create(client, rule_type="fixed", value=0).status_code == 422
        assert _create(client, rule_type="percent", value=0).status_code == 422
        assert _create(client, rule_type="percent", value=101).status_code == 422
        assert _create(client, rule_type="weekly", value=10).status_code == 422

    def test_create_rejects_missing_category(self, client):
        resp = _create(client, category_id=9999)
        assert resp.status_code == 404

    def test_percent_cap_on_create(self, client):
        assert _create(client, name="A", value=60).status_code == 200
        resp = _create(client, name="B", value=50)
        assert resp.status_code == 409
        assert "60" in resp.json()["detail"]

    def test_percent_cap_ignores_inactive_and_fixed(self, client):
        assert _create(client, name="A", value=60).status_code == 200
        a_id = client.get("/api/allocation-buckets").json()[0]["id"]
        client.patch(f"/api/allocation-buckets/{a_id}", json={"is_active": False})
        assert _create(client, name="Fixed", rule_type="fixed", value=1000).status_code == 200
        assert _create(client, name="B", value=90).status_code == 200

    def test_percent_cap_on_update_and_reactivate(self, client):
        _create(client, name="A", value=60)
        _create(client, name="B", value=30)
        rows = client.get("/api/allocation-buckets").json()
        b_id = next(r["id"] for r in rows if r["name"] == "B")

        assert client.patch(
            f"/api/allocation-buckets/{b_id}", json={"value": 50}
        ).status_code == 409

        client.patch(f"/api/allocation-buckets/{b_id}", json={"is_active": False})
        assert client.patch(
            f"/api/allocation-buckets/{b_id}", json={"value": 50}
        ).status_code == 200
        assert client.patch(
            f"/api/allocation-buckets/{b_id}", json={"is_active": True}
        ).status_code == 409

    def test_patch_partial_and_explicit_null_category(self, client, db: Session):
        cat = Category(name="Sparen", category_type="expense")
        db.add(cat)
        db.commit()

        _create(client, name="A", category_id=cat.id)
        bucket_id = client.get("/api/allocation-buckets").json()[0]["id"]

        resp = client.patch(f"/api/allocation-buckets/{bucket_id}", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"
        assert resp.json()["category_id"] == cat.id

        resp = client.patch(f"/api/allocation-buckets/{bucket_id}", json={"category_id": None})
        assert resp.status_code == 200
        assert resp.json()["category_id"] is None

    def test_patch_duplicate_name_409(self, client):
        _create(client, name="A", value=10)
        _create(client, name="B", value=10)
        b_id = next(
            r["id"] for r in client.get("/api/allocation-buckets").json() if r["name"] == "B"
        )
        assert client.patch(f"/api/allocation-buckets/{b_id}", json={"name": "A"}).status_code == 409

    def test_delete_recompacts_positions(self, client):
        for name in ["A", "B", "C"]:
            _create(client, name=name, rule_type="fixed", value=10)
        rows = client.get("/api/allocation-buckets").json()
        b_id = next(r["id"] for r in rows if r["name"] == "B")

        assert client.delete(f"/api/allocation-buckets/{b_id}").status_code == 200
        rows = client.get("/api/allocation-buckets").json()
        assert [(r["name"], r["position"]) for r in rows] == [("A", 0), ("C", 1)]

    def test_reorder(self, client):
        for name in ["A", "B", "C"]:
            _create(client, name=name, rule_type="fixed", value=10)
        ids = {r["name"]: r["id"] for r in client.get("/api/allocation-buckets").json()}

        resp = client.put(
            "/api/allocation-buckets/order",
            json={"ids": [ids["C"], ids["A"], ids["B"]]},
        )
        assert resp.status_code == 200
        rows = client.get("/api/allocation-buckets").json()
        assert [r["name"] for r in rows] == ["C", "A", "B"]
        assert [r["position"] for r in rows] == [0, 1, 2]

    def test_reorder_rejects_mismatched_ids(self, client):
        _create(client, name="A", rule_type="fixed", value=10)
        a_id = client.get("/api/allocation-buckets").json()[0]["id"]
        assert client.put(
            "/api/allocation-buckets/order", json={"ids": [a_id, 9999]}
        ).status_code == 400
        assert client.put("/api/allocation-buckets/order", json={"ids": []}).status_code == 400


class TestLifecycle:
    def test_category_delete_clears_link_without_blocking(self, client, db: Session):
        cat = Category(name="Sparen", category_type="expense")
        db.add(cat)
        db.commit()
        _create(client, name="A", category_id=cat.id)

        resp = client.delete(f"/api/categories/{cat.id}")
        assert resp.status_code == 200

        row = client.get("/api/allocation-buckets").json()[0]
        assert row["category_id"] is None

    def test_category_merge_repoints_buckets(self, client, db: Session):
        source = Category(name="Old", category_type="expense")
        target = Category(name="New", category_type="expense")
        db.add_all([source, target])
        db.commit()
        _create(client, name="A", category_id=source.id)

        dry = client.post(
            f"/api/categories/{source.id}/merge-into/{target.id}?dry_run=true"
        ).json()
        assert dry["allocation_buckets"] == 1

        resp = client.post(f"/api/categories/{source.id}/merge-into/{target.id}")
        assert resp.status_code == 200
        assert resp.json()["allocation_buckets"] == 1
        assert client.get("/api/allocation-buckets").json()[0]["category_id"] == target.id

    def test_delete_everything_wipes_buckets(self, client, db: Session):
        _create(client, name="A", rule_type="fixed", value=10)
        assert client.delete("/api/settings/everything").status_code == 200
        assert db.query(AllocationBucket).count() == 0
