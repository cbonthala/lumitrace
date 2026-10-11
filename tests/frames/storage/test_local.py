from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from lumen.config import Settings
from lumen.frames.storage import InvalidPathError, get_storage, normalize_path
from lumen.frames.storage.local import LocalStorage


def test_write_read_roundtrip(storage: LocalStorage) -> None:
    info = storage.write_bytes("2026/10/2026-10-10/a.bin", b"\x00\x01")
    assert info.path == "2026/10/2026-10-10/a.bin"
    assert info.size == 2
    assert info.modified.tzinfo is not None
    assert storage.read_bytes("2026/10/2026-10-10/a.bin") == b"\x00\x01"


def test_text_roundtrip_unicode(storage: LocalStorage) -> None:
    storage.write_text("notes/today.md", "café · ☕\n")
    assert storage.read_text("notes/today.md") == "café · ☕\n"


def test_overwrite_replaces(storage: LocalStorage) -> None:
    storage.write_text("a.md", "one")
    storage.write_text("a.md", "two")
    assert storage.read_text("a.md") == "two"


def test_missing_file_raises(storage: LocalStorage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.read_bytes("nope.md")
    with pytest.raises(FileNotFoundError):
        storage.stat("nope.md")
    with pytest.raises(FileNotFoundError):
        storage.delete("nope.md")
    with pytest.raises(FileNotFoundError):
        storage.get_share_link("nope.md")
    storage.delete("nope.md", missing_ok=True)


def test_exists_and_stat(storage: LocalStorage) -> None:
    assert not storage.exists("x/y.md")
    storage.write_text("x/y.md", "hi")
    assert storage.exists("x/y.md")
    assert not storage.exists("x")
    assert storage.stat("x/y.md").size == 2


def test_list_is_recursive_sorted_and_prefix_is_a_folder(storage: LocalStorage) -> None:
    for p in ["2026/10/b.md", "2026/10/a.md", "2026/100/c.md", "2025/01/d.md"]:
        storage.write_text(p, p)
    assert [f.path for f in storage.list()] == [
        "2025/01/d.md",
        "2026/10/a.md",
        "2026/10/b.md",
        "2026/100/c.md",
    ]
    assert [f.path for f in storage.list("2026/10")] == ["2026/10/a.md", "2026/10/b.md"]
    assert [f.path for f in storage.list("2026/10/")] == ["2026/10/a.md", "2026/10/b.md"]
    assert storage.list("missing") == []


def test_hidden_files_are_ignored(storage: LocalStorage) -> None:
    storage.write_text("a.md", "a")
    (storage.root / ".obsidian").mkdir()
    (storage.root / ".obsidian" / "app.json").write_text("{}")
    (storage.root / ".DS_Store").write_text("x")
    assert [f.path for f in storage.list()] == ["a.md"]
    changes, _ = storage.list_changes(None)
    assert [c.path for c in changes] == ["a.md"]


def test_delete_removes_empty_folders(storage: LocalStorage) -> None:
    storage.write_text("2026/10/2026-10-10/a.md", "a")
    storage.delete("2026/10/2026-10-10/a.md")
    assert not (storage.root / "2026").exists()
    assert storage.root.exists()


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "a/../../x", "", "a\\b"])
def test_invalid_paths_rejected(storage: LocalStorage, bad: str) -> None:
    with pytest.raises(InvalidPathError):
        storage.write_text(bad, "x")


def test_normalize_path() -> None:
    assert normalize_path("a//b/./c/") == "a/b/c"
    assert normalize_path("", allow_root=True) == ""


def test_atomic_write_leaves_no_temp_files(storage: LocalStorage) -> None:
    storage.write_text("a.md", "x" * 10000)
    assert sorted(os.listdir(storage.root)) == ["a.md"]


def test_list_changes_full_then_incremental(storage: LocalStorage) -> None:
    storage.write_text("a.md", "a")
    storage.write_text("b.md", "b")
    changes, token = storage.list_changes(None)
    assert {(c.path, c.kind) for c in changes} == {("a.md", "upserted"), ("b.md", "upserted")}

    changes, token = storage.list_changes(token)
    assert changes == []

    time.sleep(0.01)
    storage.write_text("a.md", "a2")
    storage.write_text("c.md", "c")
    storage.delete("b.md")
    changes, token = storage.list_changes(token)
    assert {(c.path, c.kind) for c in changes} == {
        ("a.md", "upserted"),
        ("c.md", "upserted"),
        ("b.md", "deleted"),
    }
    upserted = next(c for c in changes if c.path == "c.md")
    assert upserted.modified is not None
    assert next(c for c in changes if c.kind == "deleted").modified is None

    changes, _ = storage.list_changes(token)
    assert changes == []


def test_list_changes_rejects_foreign_token(storage: LocalStorage) -> None:
    with pytest.raises(ValueError):
        storage.list_changes("12345")


def test_share_link_is_file_uri(storage: LocalStorage) -> None:
    storage.write_bytes("2026/10/2026-10-10/2026-10-10-2130.m4a", b"audio")
    link = storage.get_share_link("2026/10/2026-10-10/2026-10-10-2130.m4a")
    assert link.startswith("file://")
    assert link.endswith("2026-10-10-2130.m4a")


def test_get_storage_local(settings: Settings, tmp_path: Path) -> None:
    store = get_storage(settings)
    assert isinstance(store, LocalStorage)
    assert store.root == (tmp_path / "Lumen").resolve()
