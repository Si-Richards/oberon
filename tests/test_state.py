from pathlib import Path
from app.state import StateStore


def test_store_creates_parent(tmp_path: Path):
    path = tmp_path / "nested" / "oberon.db"
    store = StateStore(path)
    assert path.exists()
    store.close()
