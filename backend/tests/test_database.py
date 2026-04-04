"""database.py の単体テスト"""
import pytest
import database


class TestInitDb:
    def test_tables_created(self, db_conn):
        """init_dbで必要なテーブルが全て作成される"""
        cursor = db_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}
        expected = {"sessions", "transcripts", "advices", "meeting_types", "prompts", "app_settings"}
        assert expected.issubset(tables)

    def test_default_settings_seeded(self, db_conn):
        """デフォルト設定が投入される"""
        settings = database.get_settings()
        assert settings["auto_summary_enabled"] == "true"
        assert settings["research_enabled"] == "false"
        assert settings["research_method"] == "llm"
        assert "save_dir" in settings

    def test_seed_data_created(self, db_conn):
        """初期マスタデータが投入される"""
        types = database.get_meeting_types()
        assert len(types) >= 1
        names = [t["name"] for t in types]
        assert "商談・セールス" in names


class TestSessionManagement:
    def test_create_session(self):
        """セッション作成"""
        sid = database.create_session(None, "テスト会議")
        assert sid > 0

    def test_end_session(self):
        """セッション終了でend_timeが設定される"""
        sid = database.create_session(None, "test")
        database.end_session(sid)
        details = database.get_session_details(sid)
        assert details["session"]["end_time"] is not None

    def test_create_session_with_meeting_type(self):
        """meeting_type_id付きでセッション作成"""
        types = database.get_meeting_types()
        tid = types[0]["id"]
        sid = database.create_session(tid, "商談テスト")
        details = database.get_session_details(sid)
        assert details["session"]["meeting_type_id"] == tid


class TestTranscripts:
    def test_add_and_retrieve_transcript(self):
        """文字起こしの追加と取得"""
        sid = database.create_session(None, "test")
        database.add_transcript(sid, "speaker", "こんにちは")
        database.add_transcript(sid, "mic", "はい、どうぞ")

        details = database.get_session_details(sid)
        assert len(details["transcripts"]) == 2
        assert details["transcripts"][0]["text"] == "こんにちは"
        assert details["transcripts"][0]["source"] == "speaker"


class TestAdvices:
    def test_add_and_retrieve_advice(self):
        """アドバイスの追加と取得"""
        sid = database.create_session(None, "test")
        database.add_advice(sid, "価格への懸念", "ROIを強調してください")

        details = database.get_session_details(sid)
        assert len(details["advices"]) == 1
        assert details["advices"][0]["trigger_condition"] == "価格への懸念"


class TestMeetingTypes:
    def test_create_meeting_type(self):
        """会議種別の作成"""
        new_id = database.create_meeting_type("テスト種別", "テスト用")
        assert new_id > 0

    def test_duplicate_meeting_type_returns_minus1(self):
        """重複する会議種別名は-1を返す"""
        database.create_meeting_type("ユニーク名", "desc")
        result = database.create_meeting_type("ユニーク名", "desc")
        assert result == -1

    def test_delete_meeting_type(self):
        """会議種別の削除（関連プロンプトも削除）"""
        tid = database.create_meeting_type("削除テスト", "")
        database.create_prompt(tid, "trigger", "action")
        database.delete_meeting_type(tid)

        types = database.get_meeting_types()
        assert all(t["id"] != tid for t in types)
        assert database.get_prompts_for_type(tid) == []


class TestPrompts:
    def test_create_and_get_prompt(self):
        """プロンプトの作成と取得"""
        tid = database.create_meeting_type("プロンプトテスト", "")
        pid = database.create_prompt(tid, "test trigger", "test action")
        assert pid > 0

        prompts = database.get_prompts_for_type(tid)
        assert len(prompts) == 1
        assert prompts[0]["trigger_condition"] == "test trigger"

    def test_delete_prompt(self):
        """プロンプトの削除"""
        tid = database.create_meeting_type("削除テスト2", "")
        pid = database.create_prompt(tid, "trigger", "action")
        database.delete_prompt(pid)
        assert database.get_prompts_for_type(tid) == []


class TestSettings:
    def test_update_and_get_setting(self):
        """設定の更新と取得"""
        database.update_setting("test_key", "test_value")
        settings = database.get_settings()
        assert settings["test_key"] == "test_value"

    def test_upsert_setting(self):
        """設定のupsert"""
        database.update_setting("upsert_key", "v1")
        database.update_setting("upsert_key", "v2")
        settings = database.get_settings()
        assert settings["upsert_key"] == "v2"


class TestSummary:
    def test_save_summary(self):
        """サマリーの保存"""
        sid = database.create_session(None, "summary test")
        database.save_summary(sid, "これはサマリーです")
        details = database.get_session_details(sid)
        assert details["session"]["summary"] == "これはサマリーです"


class TestHistory:
    def test_get_sessions_returns_list(self):
        """セッション一覧がリストで返る"""
        database.create_session(None, "first")
        database.create_session(None, "second")
        sessions = database.get_sessions()
        assert len(sessions) >= 2
        titles = [s["title"] for s in sessions]
        assert "first" in titles
        assert "second" in titles

    def test_get_session_details_not_found(self):
        """存在しないセッションIDはNoneを返す"""
        result = database.get_session_details(99999)
        assert result is None

    def test_update_session_title(self):
        """セッションタイトルの更新"""
        sid = database.create_session(None, "old title")
        database.update_session_title(sid, "new title")
        details = database.get_session_details(sid)
        assert details["session"]["title"] == "new title"
