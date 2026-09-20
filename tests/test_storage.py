import pytest

from app.modules.media.storage import LocalStorage


def test_storage_cannot_escape_root_or_overwrite_original(tmp_path):
    storage = LocalStorage(tmp_path / "storage")
    source = tmp_path / "source"
    source.write_bytes(b"original")
    with pytest.raises(ValueError):
        storage.put("../outside", source)
    storage.put("originals/sample", source)
    source.write_bytes(b"changed")
    with pytest.raises(FileExistsError):
        storage.put("originals/sample", source)
    assert storage.path("originals/sample").read_bytes() == b"original"
