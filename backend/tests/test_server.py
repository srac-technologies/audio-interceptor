"""server.py (FastAPI) の単体テスト"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json


@pytest.fixture
def client(isolate_db):
    """FastAPIテストクライアント"""
    # server.pyのインポート前にモックを設定
    with patch("audio_interceptor.AudioInterceptor"), \
         patch("calendar_service.calendar_service"):
        from fastapi.testclient import TestClient
        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        # stateをリセット
        server_mod.state.recording = False
        server_mod.state.websocket_clients = set()
        server_mod.state.interceptor = None
        server_mod.state.llm_pipeline = None
        server_mod.state.slack_service = None
        server_mod.state.current_session_id = None

        with TestClient(server_mod.app) as c:
            yield c


class TestRootEndpoint:
    def test_root_returns_service_info(self, client):
        """/ がサービス情報を返す"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "Meeting Assistant Backend"
        assert "version" in data
        assert data["status"] == "running"


class TestStatusEndpoint:
    def test_status_when_not_recording(self, client):
        """/status 非録音時"""
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["recording"] is False


class TestSettingsAPI:
    def test_get_settings(self, client):
        """/settings GET"""
        resp = client.get("/settings")
        assert resp.status_code == 200
        settings = resp.json()["settings"]
        assert "auto_summary_enabled" in settings

    def test_update_settings(self, client):
        """/settings POST"""
        resp = client.post("/settings", json={"settings": {"test_key": "test_val"}})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 確認
        resp = client.get("/settings")
        assert resp.json()["settings"]["test_key"] == "test_val"


class TestMeetingTypesAPI:
    def test_list_meeting_types(self, client):
        """会議種別一覧"""
        resp = client.get("/meeting-types")
        assert resp.status_code == 200
        types = resp.json()["meeting_types"]
        assert isinstance(types, list)

    def test_create_meeting_type(self, client):
        """会議種別作成"""
        resp = client.post("/meeting-types", json={"name": "APIテスト", "description": "テスト"})
        assert resp.status_code == 200
        assert resp.json()["id"] > 0

    def test_delete_meeting_type(self, client):
        """会議種別削除"""
        resp = client.post("/meeting-types", json={"name": "削除用", "description": ""})
        tid = resp.json()["id"]
        resp = client.delete(f"/meeting-types/{tid}")
        assert resp.status_code == 200


class TestPromptsAPI:
    def test_create_and_list_prompts(self, client):
        """プロンプト作成と取得"""
        # 会議種別を先に作成
        resp = client.post("/meeting-types", json={"name": "プロンプトテスト", "description": ""})
        tid = resp.json()["id"]

        resp = client.post("/prompts", json={
            "meeting_type_id": tid,
            "trigger_condition": "test trigger",
            "action_prompt": "test action",
        })
        assert resp.status_code == 200

        resp = client.get(f"/meeting-types/{tid}/prompts")
        prompts = resp.json()["prompts"]
        assert len(prompts) == 1

    def test_delete_prompt(self, client):
        """プロンプト削除"""
        resp = client.post("/meeting-types", json={"name": "削除テスト", "description": ""})
        tid = resp.json()["id"]
        resp = client.post("/prompts", json={
            "meeting_type_id": tid,
            "trigger_condition": "t",
            "action_prompt": "a",
        })
        pid = resp.json()["id"]
        resp = client.delete(f"/prompts/{pid}")
        assert resp.status_code == 200


class TestHistoryAPI:
    def test_list_history(self, client):
        """履歴一覧"""
        resp = client.get("/history")
        assert resp.status_code == 200
        assert isinstance(resp.json()["sessions"], list)

    def test_get_history_details(self, client):
        """履歴詳細"""
        import database
        sid = database.create_session(None, "history test")
        database.add_transcript(sid, "speaker", "hello")

        resp = client.get(f"/history/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["title"] == "history test"
        assert len(data["transcripts"]) == 1

    def test_update_history_title(self, client):
        """履歴タイトル更新"""
        import database
        sid = database.create_session(None, "old")
        resp = client.patch(f"/history/{sid}", json={"title": "new"})
        assert resp.status_code == 200

        details = database.get_session_details(sid)
        assert details["session"]["title"] == "new"
