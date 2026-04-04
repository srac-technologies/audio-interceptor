"""transcription.py の単体テスト"""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestTranscriptionServiceInit:
    def test_invalid_mode_raises(self):
        """不正なWHISPER_MODEでValueError"""
        with patch.dict(os.environ, {"WHISPER_MODE": "invalid"}):
            # モジュールを再ロードして環境変数を反映
            import importlib
            import transcription
            importlib.reload(transcription)
            with pytest.raises(ValueError, match="Invalid WHISPER_MODE"):
                transcription.TranscriptionService()

    def test_api_mode_without_key_raises(self):
        """API モードでAPI Keyがない場合ValueError"""
        with patch.dict(os.environ, {"WHISPER_MODE": "api", "OPENAI_API_KEY": ""}):
            import importlib
            import transcription
            importlib.reload(transcription)
            # OPENAI_API_KEYを確実にNoneにする
            with patch.object(transcription, "OPENAI_API_KEY", None):
                with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                    transcription.TranscriptionService()


class TestTranscriptionServiceTranscribe:
    @pytest.mark.asyncio
    async def test_file_not_found_raises(self):
        """存在しないファイルでFileNotFoundError"""
        with patch.dict(os.environ, {"WHISPER_MODE": "local"}):
            import importlib
            import transcription
            importlib.reload(transcription)

            mock_model = MagicMock()
            with patch.object(transcription, "WHISPER_MODE", "local"):
                service = transcription.TranscriptionService.__new__(transcription.TranscriptionService)
                service.mode = "local"
                service.model = mock_model

                with pytest.raises(FileNotFoundError):
                    await service.transcribe("/nonexistent/file.wav")

    @pytest.mark.asyncio
    async def test_local_transcribe_returns_dict(self):
        """ローカルモードでdict形式の結果を返す"""
        import transcription

        # モックのセグメントとinfo
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 1.5
        mock_segment.text = " テスト文字起こし"

        mock_info = MagicMock()
        mock_info.language = "ja"
        mock_info.duration = 1.5

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        service = transcription.TranscriptionService.__new__(transcription.TranscriptionService)
        service.mode = "local"
        service.language = "ja"
        service.model = mock_model

        with patch("os.path.exists", return_value=True):
            result = await service._transcribe_local("/fake/audio.wav")

        assert result["text"] == "テスト文字起こし"
        assert result["language"] == "ja"
        assert result["duration"] == 1.5
        assert len(result["segments"]) == 1
