"""pytest共通フィクスチャ"""
import os
import sqlite3
import tempfile
import pytest

# テスト時はインメモリDBを使用するためにDB_PATHをオーバーライド
@pytest.fixture(autouse=True)
def isolate_db(monkeypatch, tmp_path):
    """各テストで独立した一時DBを使用"""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("database.DB_PATH", db_path)
    import database
    database.init_db()
    yield db_path


@pytest.fixture
def db_conn(isolate_db):
    """テスト用DB接続"""
    import database
    conn = database.get_db_connection()
    yield conn
    conn.close()
