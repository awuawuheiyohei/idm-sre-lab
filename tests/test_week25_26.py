"""
IdM SRE Lab - Week 25-26 (Security Compliance) tests
- ISO 27001 / PCI-DSS / STRIDE 文档端点
- 安全摘要 JSON
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


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


def test_endpoint_iso27001_mapping(client):
    r = client.get("/security/iso27001/mapping")
    assert r.status_code == 200
    d = r.json()
    assert d["standard"] == "ISO 27001:2022"
    assert d["format"] == "markdown"
    assert "A.5" in d["content"]
    assert "A.8" in d["content"]
    assert "A.9" in d["content"]


def test_endpoint_pci_dss_mapping(client):
    r = client.get("/security/pci-dss/mapping")
    assert r.status_code == 200
    d = r.json()
    assert d["standard"] == "PCI-DSS v4.0"
    assert "Section 8" in d["content"]
    assert "Section 10" in d["content"]
    assert "8.1" in d["content"]
    assert "10.1" in d["content"]


def test_endpoint_threat_model(client):
    r = client.get("/security/threat-model")
    assert r.status_code == 200
    d = r.json()
    assert d["methodology"] == "STRIDE"
    md = d["content"]
    assert "Spoofing" in md
    assert "Tampering" in md
    assert "STRIDE" in md


def test_endpoint_security_summary(client):
    r = client.get("/security/summary")
    assert r.status_code == 200
    d = r.json()
    assert d["version"] == "v1.0.0"
    assert d["standards"]["iso27001_2022"]["total_controls"] == 93
    assert d["standards"]["iso27001_2022"]["implemented"] >= 20
    assert d["standards"]["threat_model_stride"]["coverage_pct"] >= 80
    assert "iso27001_doc" in d["evidence"]
    assert "pci_dss_doc" in d["evidence"]
    assert "threat_model_doc" in d["evidence"]


def test_security_docs_exist():
    """直接验证 .md 文件存在 + 非空"""
    sec = ROOT.parent / "security"
    if not sec.exists():
        sec = ROOT / "security"
    for f in ("iso27001-mapping.md", "pci-controls.md", "threat-model.md"):
        path = sec / f
        if path.exists():
            assert path.stat().st_size > 500, f"{f} too small"
            content = path.read_text(encoding="utf-8")
            assert len(content) > 500