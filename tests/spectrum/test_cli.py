from __future__ import annotations

import datetime as dt
import json

import pytest

from lumitrace.config import Settings
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.spectrum.__main__ import main
from lumitrace.spectrum.backup import BACKUP_PATH
from tests.spectrum.conftest import make_day, write_day


def test_sync_rebuild_and_backup_commands(
    settings: Settings, storage: LocalStorage, capsys: pytest.CaptureFixture[str]
) -> None:
    write_day(storage, make_day(dt.date(2026, 10, 10)))

    main(["sync"], settings=settings)
    first = json.loads(capsys.readouterr().out)
    assert first["indexed"] == 1 and first["failed"] == []

    main(["sync"], settings=settings)
    assert json.loads(capsys.readouterr().out)["indexed"] == 0

    main(["rebuild"], settings=settings)
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["kind"] == "rebuild" and rebuilt["indexed"] == 1

    main(["backup"], settings=settings)
    assert json.loads(capsys.readouterr().out)["backup"] == BACKUP_PATH
    assert storage.exists(BACKUP_PATH)


def test_unknown_command_is_rejected(settings: Settings) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["explode"], settings=settings)
    assert exc.value.code == 2
