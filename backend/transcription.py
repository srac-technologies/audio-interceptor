#!/usr/bin/env python3
"""
Transcription Service - 複数エンジン対応の文字起こしサービス

エンジンをプラグイン的に切り替え可能。設定はDB (app_settings) から読み込み。
環境変数によるレガシー設定もフォールバックとしてサポート。
"""
import os
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

from transcription_engines import (
    TranscriptionEngine,
    create_engine,
    get_available_engines,
    ENGINE_REGISTRY,
)

# .envファイルのパスを明示的に指定
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

# レガシー環境変数（フォールバック用）
WHISPER_MODE = os.getenv("WHISPER_MODE", "local")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ja")


class TranscriptionService:
    """音声文字起こしサービス（複数エンジン対応）"""

    def __init__(self, engine_id: Optional[str] = None, settings: Optional[Dict[str, str]] = None):
        """
        Args:
            engine_id: エンジンID（省略時はsettings or 環境変数から決定）
            settings: DB設定（省略時はレガシー環境変数を使用）
        """
        # エンジンIDの決定
        if engine_id:
            self.engine_id = engine_id
        elif settings and settings.get("transcription_engine"):
            self.engine_id = settings["transcription_engine"]
        else:
            # レガシー: WHISPER_MODE から変換
            mode_map = {"api": "openai-whisper", "moonshine": "moonshine-tiny-ja"}
            self.engine_id = mode_map.get(WHISPER_MODE, "faster-whisper")

        # エンジン固有オプションの構築
        self.language = WHISPER_LANGUAGE if WHISPER_LANGUAGE != "auto" else None
        if settings and settings.get("transcription_language"):
            lang = settings["transcription_language"]
            self.language = lang if lang != "auto" else None

        engine_kwargs = self._build_engine_kwargs(settings)

        # エンジンの初期化
        try:
            self.engine: TranscriptionEngine = create_engine(self.engine_id, **engine_kwargs)
            logger.info(f"Transcription engine initialized: {self.engine_id}")
        except Exception as e:
            logger.error(f"Failed to init engine '{self.engine_id}': {e}")
            # フォールバック: faster-whisper (安全なデフォルトモデルを使用)
            if self.engine_id != "faster-whisper":
                fallback_model = "small"
                logger.info("Falling back to faster-whisper (model=%s)", fallback_model)
                self.engine_id = "faster-whisper"
                self.engine = create_engine("faster-whisper", model=fallback_model)
            else:
                raise

    def _build_engine_kwargs(self, settings: Optional[Dict[str, str]] = None) -> dict:
        """エンジン初期化用のkwargsを構築"""
        kwargs = {}
        model = WHISPER_MODEL
        if settings and settings.get("transcription_model"):
            model = settings["transcription_model"]

        if self.engine_id == "faster-whisper":
            kwargs["model"] = model
        elif self.engine_id == "openai-whisper":
            pass  # API keyは環境変数から自動取得
        elif self.engine_id == "google-speech":
            creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if settings and settings.get("google_speech_credentials"):
                creds = settings["google_speech_credentials"]
            if creds:
                kwargs["credentials_path"] = creds
        elif self.engine_id == "kotoba-whisper":
            kotoba_model = "kotoba-tech/kotoba-whisper-v2.2"
            if settings and settings.get("kotoba_whisper_model"):
                kotoba_model = settings["kotoba_whisper_model"]
            kwargs["model"] = kotoba_model
        elif self.engine_id == "moonshine-tiny-ja":
            moonshine_model = "UsefulSensors/moonshine-tiny-ja"
            if settings and settings.get("moonshine_model"):
                moonshine_model = settings["moonshine_model"]
            kwargs["model"] = moonshine_model

        return kwargs

    async def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        音声ファイルを文字起こし

        Args:
            audio_path: 音声ファイルパス（WAV推奨）

        Returns:
            {"text", "language", "duration", "segments", "engine"}
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        return await self.engine.transcribe(audio_path, language=self.language)


# シングルトンインスタンス
_service: Optional[TranscriptionService] = None


def get_transcription_service(settings: Optional[Dict[str, str]] = None) -> TranscriptionService:
    """TranscriptionServiceシングルトン取得"""
    global _service
    if _service is None:
        _service = TranscriptionService(settings=settings)
    return _service


def reset_transcription_service():
    """エンジン変更時にシングルトンをリセット"""
    global _service
    _service = None


# CLI テスト用
if __name__ == "__main__":
    import asyncio
    import sys

    async def test_transcribe(audio_path: str):
        service = get_transcription_service()
        print(f"Engine: {service.engine_id}")

        result = await service.transcribe(audio_path)
        print(f"\nTranscription result:")
        print(f"Engine: {result['engine']}")
        print(f"Language: {result['language']}")
        print(f"Duration: {result['duration']:.1f}s")
        print(f"Text: {result['text']}")

        if result["segments"]:
            print(f"\nSegments ({len(result['segments'])}):")
            for seg in result["segments"][:3]:
                print(f"  [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")

    if len(sys.argv) < 2:
        print("Usage: python transcription.py <audio_file.wav>")
        print("\nAvailable engines:")
        for eng in get_available_engines():
            status = "OK" if eng["available"] else "N/A"
            print(f"  [{status}] {eng['id']}: {eng['description']}")
        sys.exit(1)

    asyncio.run(test_transcribe(sys.argv[1]))
