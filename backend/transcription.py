#!/usr/bin/env python3
"""
Transcription Service - API/Local Whisper切り替え対応
"""
import os
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# 設定
WHISPER_MODE = os.getenv("WHISPER_MODE", "local")  # "local" or "api"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny, base, small, medium, large-v3
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ja")  # ja, en, auto
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class TranscriptionService:
    """音声文字起こしサービス（API/Local統合）"""
    
    def __init__(self):
        self.mode = WHISPER_MODE
        self.model_name = WHISPER_MODEL
        self.language = WHISPER_LANGUAGE if WHISPER_LANGUAGE != "auto" else None
        
        if self.mode == "local":
            self._init_local_whisper()
        elif self.mode == "api":
            self._init_api_client()
        else:
            raise ValueError(f"Invalid WHISPER_MODE: {self.mode}. Must be 'local' or 'api'")
        
        logger.info(f"Transcription service initialized: mode={self.mode}, model={self.model_name}")
    
    def _init_local_whisper(self):
        """ローカルWhisper初期化（faster-whisper）"""
        try:
            from faster_whisper import WhisperModel
            
            # CPU環境向け設定
            device = "cpu"
            compute_type = "int8"  # CPU最適化（int8量子化）
            
            logger.info(f"Loading local Whisper model: {self.model_name} on {device}")
            self.model = WhisperModel(
                self.model_name,
                device=device,
                compute_type=compute_type,
                download_root=str(Path.home() / ".cache" / "whisper")
            )
            logger.info("Local Whisper model loaded successfully")
            
        except ImportError:
            raise ImportError(
                "faster-whisper not installed. Run: pip install faster-whisper"
            )
        except Exception as e:
            logger.error(f"Failed to load local Whisper model: {e}")
            raise
    
    def _init_api_client(self):
        """OpenAI API初期化"""
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set in .env")
        
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            logger.info("OpenAI API client initialized")
        except ImportError:
            raise ImportError("openai not installed. Run: pip install openai")
    
    async def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        音声ファイルを文字起こし
        
        Args:
            audio_path: 音声ファイルパス（WAV推奨）
        
        Returns:
            {
                "text": "文字起こし結果",
                "language": "ja",
                "duration": 5.2,
                "segments": [...]  # ローカルモードのみ
            }
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        if self.mode == "local":
            return await self._transcribe_local(audio_path)
        else:
            return await self._transcribe_api(audio_path)
    
    async def _transcribe_local(self, audio_path: str) -> Dict[str, Any]:
        """ローカルWhisperで文字起こし"""
        try:
            # faster-whisperは同期API
            segments, info = self.model.transcribe(
                audio_path,
                language=self.language,
                beam_size=5,
                vad_filter=True,  # VAD（音声区間検出）有効化
                vad_parameters=dict(
                    min_silence_duration_ms=500  # 0.5秒以上の無音で区切り
                )
            )
            
            # セグメント結果を収集
            segments_list = []
            full_text = []
            
            for segment in segments:
                segments_list.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip()
                })
                full_text.append(segment.text.strip())
            
            result = {
                "text": " ".join(full_text),
                "language": info.language,
                "duration": info.duration,
                "segments": segments_list
            }
            
            logger.debug(f"Local transcription completed: {len(segments_list)} segments, {info.duration:.1f}s")
            return result
            
        except Exception as e:
            logger.error(f"Local transcription failed: {e}")
            raise
    
    async def _transcribe_api(self, audio_path: str) -> Dict[str, Any]:
        """OpenAI APIで文字起こし"""
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=self.language if self.language else None,
                    response_format="verbose_json"
                )
            
            result = {
                "text": transcript.text,
                "language": transcript.language,
                "duration": transcript.duration,
                "segments": []  # API版はセグメント情報が限定的
            }
            
            logger.debug(f"API transcription completed: {transcript.duration:.1f}s")
            return result
            
        except Exception as e:
            logger.error(f"API transcription failed: {e}")
            raise


# シングルトンインスタンス
_service: Optional[TranscriptionService] = None

def get_transcription_service() -> TranscriptionService:
    """TranscriptionServiceシングルトン取得"""
    global _service
    if _service is None:
        _service = TranscriptionService()
    return _service


# CLI テスト用
if __name__ == "__main__":
    import asyncio
    import sys
    
    async def test_transcribe(audio_path: str):
        service = get_transcription_service()
        print(f"Mode: {service.mode}, Model: {service.model_name}")
        
        result = await service.transcribe(audio_path)
        print(f"\nTranscription result:")
        print(f"Language: {result['language']}")
        print(f"Duration: {result['duration']:.1f}s")
        print(f"Text: {result['text']}")
        
        if result['segments']:
            print(f"\nSegments ({len(result['segments'])}):")
            for seg in result['segments'][:3]:  # 最初の3つのみ表示
                print(f"  [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")
    
    if len(sys.argv) < 2:
        print("Usage: python transcription.py <audio_file.wav>")
        sys.exit(1)
    
    asyncio.run(test_transcribe(sys.argv[1]))
