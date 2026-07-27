from pathlib import Path

from scripts.migrate_output import migrate_output


def test_migration_is_dry_run_by_default(tmp_path: Path) -> None:
    old = tmp_path / "author-20260726-title"
    old.mkdir()

    results = migrate_output(tmp_path, apply=False)

    assert old.exists()
    assert results == [("would-move", old, tmp_path / "x" / old.name)]


def test_migration_moves_only_legacy_directories_and_skips_conflicts(tmp_path: Path) -> None:
    movable = tmp_path / "a-20260726-one"
    conflict = tmp_path / "b-20260726-two"
    movable.mkdir()
    conflict.mkdir()
    (tmp_path / "x" / conflict.name).mkdir(parents=True)

    results = migrate_output(tmp_path, apply=True)

    assert (tmp_path / "x" / movable.name).is_dir()
    assert conflict.is_dir()
    assert any(status == "skipped" for status, *_ in results)
