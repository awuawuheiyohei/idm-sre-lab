"""
IdM SRE Lab - Week 27-28 (Post-Mortem) tests
- PM template endpoint
- PM CRUD
- 3 real PM docs persisted in docs/postmortems/
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.postmortem.manager import create_pm, get_pm, list_pms, update_pm_status  # noqa: E402


@pytest.fixture
def client():
    db = ROOT / "data" / "idm.db"
    for ext in ("", "-wal", "-shm"):
        p = Path(str(db) + ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    with TestClient(app) as c:
        r = c.post("/admin/seed")
        assert r.status_code == 200
        yield c


# ============================================
# Template
# ============================================
def test_endpoint_template(client):
    r = client.get("/pm-template")
    assert r.status_code == 200
    d = r.json()
    assert d["format"] == "markdown"
    md = d["content"]
    assert "5 Whys" in md
    assert "blameless" in md.lower()
    assert "Action Items" in md


def test_template_file_exists():
    """postmortem-template.md 物理存在"""
    path = ROOT / "docs" / "postmortem-template.md"
    assert path.exists()
    assert path.stat().st_size > 1000


# ============================================
# CRUD
# ============================================
def test_create_pm():
    pm_id = create_pm(incident_id="INC-001", title="Test PM", severity="SEV-2",
                       summary="Test summary", root_cause="5 Whys test",
                       blameless=True)
    assert pm_id.startswith("PM-")
    d = get_pm(pm_id)
    assert d["status"] == "DRAFT"
    assert d["title"] == "Test PM"
    assert d["blameless"] is True


def test_create_pm_with_timeline():
    pm_id = create_pm(
        incident_id="INC-002", title="Timeline test", severity="SEV-1",
        timeline=[{"time": "T+0", "event": "alert fired"},
                   {"time": "T+5min", "event": "ack"}],
        action_items=[{"owner": "alice", "action": "fix", "due_date": "2026-10-01"}],
    )
    d = get_pm(pm_id)
    assert len(d["timeline"]) == 2
    assert len(d["action_items"]) == 1
    assert d["timeline"][0]["event"] == "alert fired"


def test_update_pm_status_publish():
    pm_id = create_pm("INC-003", "Publish test", "SEV-2")
    d = update_pm_status(pm_id, "PUBLISHED")
    assert d["status"] == "PUBLISHED"
    assert d["published_at"] is not None


def test_update_pm_status_invalid():
    pm_id = create_pm("INC-004", "Invalid status", "SEV-3")
    with pytest.raises(ValueError):
        update_pm_status(pm_id, "INVALID_STATUS")


def test_list_pms():
    create_pm("INC-005", "PM-A", "SEV-1")
    create_pm("INC-006", "PM-B", "SEV-2")
    items = list_pms(limit=10)
    assert len(items) >= 2


def test_list_pms_filter_severity():
    create_pm("INC-007", "PM-C", "SEV-1")
    items = list_pms(severity="SEV-1", limit=10)
    for it in items:
        assert it["severity"] == "SEV-1"


# ============================================
# Endpoints
# ============================================
def test_endpoint_create_pm(client):
    r = client.post("/pm-documents", data={
        "title": "Endpoint PM",
        "severity": "SEV-1",
        "incident_id": "INC-X",
        "summary": "test",
    })
    assert r.status_code == 200
    assert "pm_id" in r.json()


def test_endpoint_create_pm_missing_title(client):
    r = client.post("/pm-documents", data={"severity": "SEV-1"})
    assert r.status_code == 400


def test_endpoint_create_pm_invalid_severity(client):
    r = client.post("/pm-documents", data={"title": "x", "severity": "INVALID"})
    assert r.status_code == 400


def test_endpoint_get_pm(client):
    r = client.post("/pm-documents", data={
        "title": "Get test", "severity": "SEV-2"
    })
    pm_id = r.json()["pm_id"]
    r2 = client.get(f"/pm-documents/{pm_id}")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Get test"


def test_endpoint_get_pm_404(client):
    r = client.get("/pm-documents/PM-DOES-NOT-EXIST")
    assert r.status_code == 404


def test_endpoint_patch_pm_publish(client):
    r = client.post("/pm-documents", data={
        "title": "Publish test", "severity": "SEV-2"
    })
    pm_id = r.json()["pm_id"]
    r2 = client.patch(f"/pm-documents/{pm_id}", data={"status": "PUBLISHED"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "PUBLISHED"
    assert r2.json()["published_at"] is not None


def test_endpoint_patch_pm_invalid_status(client):
    r = client.post("/pm-documents", data={"title": "x", "severity": "SEV-1"})
    pm_id = r.json()["pm_id"]
    r2 = client.patch(f"/pm-documents/{pm_id}", data={"status": "BAD"})
    assert r2.status_code == 400


def test_endpoint_patch_pm_404(client):
    r = client.patch("/pm-documents/PM-X", data={"status": "PUBLISHED"})
    assert r.status_code == 404


def test_endpoint_list_pm(client):
    client.post("/pm-documents", data={"title": "PM-1", "severity": "SEV-1"})
    client.post("/pm-documents", data={"title": "PM-2", "severity": "SEV-2"})
    r = client.get("/pm-documents")
    assert r.status_code == 200
    assert r.json()["count"] >= 2


def test_endpoint_list_pm_filter(client):
    """filter by status"""
    r = client.post("/pm-documents", data={"title": "Draft", "severity": "SEV-3"})
    client.patch(f"/pm-documents/{r.json()['pm_id']}", data={"status": "PUBLISHED"})
    r2 = client.get("/pm-documents?status=PUBLISHED")
    for it in r2.json()["items"]:
        assert it["status"] == "PUBLISHED"


# ============================================
# 3 real PM docs in docs/postmortems/
# ============================================
def test_three_real_pm_docs_exist():
    """3 个真实 PM 文档存在（基于之前 chaos experiments + incidents）"""
    docs_dir = ROOT / "docs" / "postmortems"
    assert docs_dir.exists()
    expected = [
        "PM-20260926-001-oauth-token-spike.md",
        "PM-20260926-002-auth-fail-storm.md",
        "PM-20260926-003-memory-leak.md",
    ]
    for f in expected:
        path = docs_dir / f
        assert path.exists(), f"Missing PM doc: {f}"
        content = path.read_text(encoding="utf-8")
        assert "## 1. Summary" in content
        assert "## 5 Whys" in content.lower() or "## 3. Root Cause" in content
        assert "## 7. Action Items" in content or "Action Items" in content
        assert "Blameless" in content or "blameless" in content.lower()


def test_pm_docs_have_action_items():
    """每个 PM 都有具体 action items（不空话）"""
    docs_dir = ROOT / "docs" / "postmortems"
    for f in docs_dir.glob("PM-*.md"):
        content = f.read_text(encoding="utf-8")
        # 至少有 1 个 action item
        assert "P0" in content or "P1" in content
        # 至少有 1 个 owner 名字
        assert any(name in content for name in ["alice", "bob", "carol"])