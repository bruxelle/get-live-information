from __future__ import annotations

import sqlite3

from myojou_sync.cli import main
from myojou_sync.sqlite_schema import REQUIRED_COLUMNS, SCHEMA_INDEXES, SCHEMA_TABLES, initialize_sqlite_schema
from myojou_sync.state import SQLiteStateStore


def _table_names(db_path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _columns(db_path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _indexes(db_path, table_name: str) -> dict[str, bool]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return {row[1]: bool(row[2]) for row in rows}


def test_initialize_sqlite_schema_creates_required_tables_and_columns(tmp_path):
    db_path = tmp_path / "future.sqlite"

    result = initialize_sqlite_schema(db_path)

    assert result.db_path == db_path
    assert set(result.tables) == set(SCHEMA_TABLES)
    assert set(SCHEMA_TABLES).issubset(_table_names(db_path))
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        assert required_columns.issubset(_columns(db_path, table_name))


def test_initialize_sqlite_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "future.sqlite"

    first = initialize_sqlite_schema(db_path)
    second = initialize_sqlite_schema(db_path)

    assert first.tables == second.tables
    assert first.indexes == second.indexes
    assert set(SCHEMA_TABLES).issubset(_table_names(db_path))


def test_initialize_sqlite_schema_creates_key_indexes_and_unique_constraints(tmp_path):
    db_path = tmp_path / "future.sqlite"
    initialize_sqlite_schema(db_path)

    source_indexes = _indexes(db_path, "source_posts")
    event_source_indexes = _indexes(db_path, "event_sources")

    assert set(SCHEMA_INDEXES).issubset(
        source_indexes
        | _indexes(db_path, "events")
        | _indexes(db_path, "ticket_sales")
        | _indexes(db_path, "deadlines")
        | event_source_indexes
        | _indexes(db_path, "classification_reviews")
    )
    assert source_indexes["ux_source_posts_platform_source_post_id"] is True
    assert event_source_indexes["ux_event_sources_event_source"] is True


def test_init_db_cli_initializes_schema(tmp_path, capsys):
    db_path = tmp_path / "cli.sqlite"

    result = main(["init-db", "--db", str(db_path)])
    output = capsys.readouterr().out

    assert result == 0
    assert "Initialized SQLite schema:" in output
    assert "source_posts" in output
    assert "classification_reviews" in output
    assert set(SCHEMA_TABLES).issubset(_table_names(db_path))


def test_init_db_cli_fails_clearly_for_legacy_state_db(tmp_path, capsys):
    db_path = tmp_path / "state.sqlite"
    SQLiteStateStore(db_path)

    result = main(["init-db", "--db", str(db_path)])
    error = capsys.readouterr().err

    assert result == 2
    assert "not compatible with the future normalized schema" in error
    assert "Use a fresh DB path for init-db" in error
