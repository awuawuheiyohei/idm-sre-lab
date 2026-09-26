"""
Security compliance endpoints (Week 25-26):
- GET /security/iso27001/mapping — ISO 27001 控制项 → 实现 映射
- GET /security/pci-dss/mapping — PCI-DSS 控制项 → 实现 映射
- GET /security/threat-model — STRIDE 威胁模型
- GET /security/summary — 合规摘要
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

SECURITY_DIR = Path(__file__).resolve().parent.parent.parent / "security"


def _read_md(filename: str) -> str:
    path = SECURITY_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"Security doc not found: {filename}")
    return path.read_text(encoding="utf-8")


@router.get("/security/iso27001/mapping")
async def iso27001_mapping():
    """ISO 27001:2022 控制项 → IdM SRE Lab 实现映射"""
    md = _read_md("iso27001-mapping.md")
    return {
        "format": "markdown",
        "standard": "ISO 27001:2022",
        "version": "v1.0.0",
        "content": md,
    }


@router.get("/security/pci-dss/mapping")
async def pci_dss_mapping():
    """PCI-DSS v4.0 控制项 → IdM SRE Lab 实现映射"""
    md = _read_md("pci-controls.md")
    return {
        "format": "markdown",
        "standard": "PCI-DSS v4.0",
        "version": "v1.0.0",
        "content": md,
    }


@router.get("/security/threat-model")
async def threat_model():
    """STRIDE 威胁模型"""
    md = _read_md("threat-model.md")
    return {
        "format": "markdown",
        "methodology": "STRIDE",
        "version": "v1.0.0",
        "content": md,
    }


@router.get("/security/summary")
async def security_summary():
    """合规摘要（JSON）"""
    return {
        "version": "v1.0.0",
        "standards": {
            "iso27001_2022": {
                "total_controls": 93,
                "implemented": 24,
                "coverage_pct": 25.8,
                "focus_areas": ["A.5 组织 (8)", "A.8 技术 (12)", "A.9 访问控制 (8)"],
            },
            "pci_dss_v4": {
                "section_8_auth": "完整实现 (8.1-8.7)",
                "section_10_log": "完整实现 (10.1-10.7)",
                "other_sections": "dev 模拟环境，部署在 k8s 生产环境时全部覆盖",
            },
            "threat_model_stride": {
                "total_threats": 25,
                "mitigated": 23,
                "partial": 1,
                "unmitigated": 1,
                "coverage_pct": 92.0,
            },
        },
        "evidence": {
            "iso27001_doc": "security/iso27001-mapping.md",
            "pci_dss_doc": "security/pci-controls.md",
            "threat_model_doc": "security/threat-model.md",
        },
    }