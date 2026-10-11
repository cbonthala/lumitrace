"""GDriveStorage against an in-memory fake of the Drive v3 API (no network)."""

from __future__ import annotations

import pytest

from lifelog.config import Settings
from lifelog.storage import StorageError, get_storage
from lifelog.storage.gdrive import GDriveStorage
from tests.storage.fake_drive import FOLDER, FakeDrive


@pytest.fixture
def drive() -> FakeDrive:
    return FakeDrive()


@pytest.fixture
def store(drive: FakeDrive) -> GDriveStorage:
    return GDriveStorage("LifeLog", service=drive)


def test_root_folder_created_once_in_my_drive(store: GDriveStorage, drive: FakeDrive) -> None:
    root = store.root_id()
    assert drive.items[root]["name"] == "LifeLog"
    assert drive.items[root]["parents"] == [drive.root_id]
    assert drive.items[root]["mimeType"] == FOLDER
    again = GDriveStorage("LifeLog", service=drive)
    assert again.root_id() == root


def test_write_creates_folders_and_reads_back(store: GDriveStorage, drive: FakeDrive) -> None:
    info = store.write_text("2026/10/2026-10-10/2026-10-10.md", "# hi\n")
    assert info.id and info.size == 5
    assert store.read_text("2026/10/2026-10-10/2026-10-10.md") == "# hi\n"
    folders = sorted(it["name"] for it in drive.items.values() if it["mimeType"] == FOLDER)
    assert folders == ["10", "2026", "2026-10-10", "LifeLog"]
    assert drive.items[info.id]["mimeType"].startswith("text/markdown")


def test_overwrite_updates_same_file(store: GDriveStorage) -> None:
    first = store.write_text("a.md", "one")
    second = store.write_text("a.md", "two")
    assert first.id == second.id
    assert store.read_text("a.md") == "two"


def test_exists_stat_missing(store: GDriveStorage) -> None:
    assert not store.exists("a/b.md")
    with pytest.raises(FileNotFoundError):
        store.read_bytes("a/b.md")
    with pytest.raises(FileNotFoundError):
        store.stat("a/b.md")
    store.write_text("a/b.md", "x")
    assert store.exists("a/b.md")
    assert not store.exists("a")
    assert store.stat("a/b.md").size == 1


def test_names_with_quotes(store: GDriveStorage) -> None:
    store.write_text("it's/a 'quoted' file.md", "q")
    assert store.read_text("it's/a 'quoted' file.md") == "q"


def test_list_recursive_with_prefix(store: GDriveStorage) -> None:
    for p in ["2026/10/b.md", "2026/10/a.md", "2026/100/c.md", "2025/01/d.md"]:
        store.write_text(p, p)
    assert [f.path for f in store.list()] == [
        "2025/01/d.md",
        "2026/10/a.md",
        "2026/10/b.md",
        "2026/100/c.md",
    ]
    assert [f.path for f in store.list("2026/10")] == ["2026/10/a.md", "2026/10/b.md"]
    assert store.list("nope") == []


def test_delete_trashes(store: GDriveStorage, drive: FakeDrive) -> None:
    info = store.write_text("a.md", "x")
    store.delete("a.md")
    assert drive.items[info.id]["trashed"] is True
    assert not store.exists("a.md")
    with pytest.raises(FileNotFoundError):
        store.delete("a.md")
    store.delete("a.md", missing_ok=True)


def test_share_link(store: GDriveStorage) -> None:
    info = store.write_bytes("2026/10/2026-10-10/2026-10-10-2130.m4a", b"aac")
    link = store.get_share_link("2026/10/2026-10-10/2026-10-10-2130.m4a")
    assert link == f"https://drive.google.com/file/d/{info.id}/view"
    with pytest.raises(FileNotFoundError):
        store.get_share_link("missing.m4a")


def test_list_changes_full_then_incremental(store: GDriveStorage, drive: FakeDrive) -> None:
    store.write_text("2026/10/2026-10-10/2026-10-10.md", "a")
    store.write_text("2026/10/2026-10-11/2026-10-11.md", "b")
    changes, token = store.list_changes(None)
    assert {(c.path, c.kind) for c in changes} == {
        ("2026/10/2026-10-10/2026-10-10.md", "upserted"),
        ("2026/10/2026-10-11/2026-10-11.md", "upserted"),
    }

    changes, token = store.list_changes(token)
    assert changes == []

    store.write_text("2026/10/2026-10-10/2026-10-10.md", "a2")
    store.write_text("2026/10/2026-10-12/2026-10-12.md", "c")
    store.write_text("2026/10/2026-10-12/2026-10-12.md", "c2")
    store.delete("2026/10/2026-10-11/2026-10-11.md")
    changes, token = store.list_changes(token)
    assert {(c.path, c.kind) for c in changes} == {
        ("2026/10/2026-10-10/2026-10-10.md", "upserted"),
        ("2026/10/2026-10-12/2026-10-12.md", "upserted"),
        ("2026/10/2026-10-11/2026-10-11.md", "deleted"),
    }
    assert store.list_changes(token)[0] == []


def test_changes_after_restart_map_deletions(drive: FakeDrive) -> None:
    first = GDriveStorage("LifeLog", service=drive)
    first.write_text("a/x.md", "x")
    _, token = first.list_changes(None)
    first.delete("a/x.md")

    restarted = GDriveStorage("LifeLog", service=drive)
    changes, _ = restarted.list_changes(token)
    assert [(c.path, c.kind) for c in changes] == [("a/x.md", "deleted")]


def test_rename_by_owner_is_delete_plus_upsert(store: GDriveStorage, drive: FakeDrive) -> None:
    info = store.write_text("a/old.md", "x")
    _, token = store.list_changes(None)
    drive.rename(info.id, "new.md")
    changes, _ = store.list_changes(token)
    assert {(c.path, c.kind) for c in changes} == {
        ("a/old.md", "deleted"),
        ("a/new.md", "upserted"),
    }


def test_folder_rename_moves_children(store: GDriveStorage, drive: FakeDrive) -> None:
    store.write_text("2026/10/day/one.md", "1")
    store.write_text("2026/10/day/two.md", "2")
    _, token = store.list_changes(None)
    drive.rename(drive.id_of("day"), "renamed")
    changes, _ = store.list_changes(token)
    assert {(c.path, c.kind) for c in changes} == {
        ("2026/10/day/one.md", "deleted"),
        ("2026/10/day/two.md", "deleted"),
        ("2026/10/renamed/one.md", "upserted"),
        ("2026/10/renamed/two.md", "upserted"),
    }
    assert store.read_text("2026/10/renamed/one.md") == "1"


def test_changes_outside_root_are_ignored(store: GDriveStorage, drive: FakeDrive) -> None:
    _, token = store.list_changes(None)
    drive.files().create(body={"name": "elsewhere.txt", "parents": ["root"]}).execute()
    store.write_text(".hidden/thing.md", "h")
    changes, _ = store.list_changes(token)
    assert changes == []


def test_get_storage_gdrive_without_token_errors(settings: Settings, tmp_path) -> None:
    settings = settings.model_copy(
        update={"storage_backend": "gdrive", "gdrive_token_file": tmp_path / "missing.json"}
    )
    with pytest.raises(StorageError, match="lifelog-gdrive-login"):
        get_storage(settings)
