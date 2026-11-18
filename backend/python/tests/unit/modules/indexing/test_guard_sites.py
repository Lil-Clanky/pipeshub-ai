"""The registry the structural guards read: empty by default, and an extra root is scanned and its sites are keyed by it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.support import guard_sites

if TYPE_CHECKING:
    from pathlib import Path


def test_the_registry_is_empty_by_default() -> None:
    assert guard_sites.EXTRA_SOURCE_ROOTS == ()
    assert not guard_sites.EXTRA_STATUS_SITES and not guard_sites.EXTRA_TX_OWNERS and not guard_sites.EXTRA_HELPER_WRITERS
    assert not guard_sites.EXTRA_DIAGNOSTIC_WRITER_FILES and not guard_sites.EXTRA_DELETE_FENCED


def test_an_extra_root_is_scanned_and_resolved_by_its_own_key(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "extras"
    root.mkdir()
    (root / "writer.py").write_text("x = 1\n")
    monkeypatch.setattr(guard_sites, "EXTRA_SOURCE_ROOTS", (root,))

    keys = {key for key, _ in guard_sites.source_files()}

    assert "extras/writer.py" in keys
    assert "modules/indexing/run.py" in keys
    assert guard_sites.path_of("extras/writer.py") == root / "writer.py"
    assert guard_sites.path_of("modules/indexing/run.py") == guard_sites.APP / "modules/indexing/run.py"
