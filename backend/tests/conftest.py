import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


@pytest.fixture(scope="session")
def dev_kb():
    from eis.services.ingest import ingest_dir
    d = ROOT / "dataset" / "out" / "dev" / "docs"
    if not d.exists():
        pytest.skip("датасет не собран: python dataset/generator/build.py")
    return ingest_dir(d)


@pytest.fixture(scope="session")
def dev_graph(dev_kb):
    from eis.graph.store import build_graph
    return build_graph(dev_kb)
