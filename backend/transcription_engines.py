#!/usr/bin/env python3
"""
Transcription Engines - 文字起こしエンジンの抽象化レイヤー

各エンジンはTranscriptionEngineを継承し、transcribe()を実装する。
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class TranscriptionEngine(ABC):
    """文字起こしエンジンの基底クラス"""

    name: str = "base"
    description: str = ""

    @abstractmethod
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        音声ファイルを文字起こし

        Args:
            audio_path: 音声ファイルパス（WAV推奨）
            language: 言語コード（"ja", "en", None=自動検出）

        Returns:
            {
                "text": "文字起こし結果",
                "language": "ja",
                "duration": 5.2,
                "segments": [{"start": 0.0, "end": 1.5, "text": "..."}],
                "engine": "engine_name"
            }
        """
        pass

    @classmethod
    def get_required_env_vars(cls) -> List[str]:
        """必要な環境変数のリスト"""
        return []

    @classmethod
    def is_available(cls) -> bool:
        """エンジンが利用可能かチェック"""
        return True


class FasterWhisperEngine(TranscriptionEngine):
    """faster-whisper（ローカルCPU/GPU）"""

    name = "faster-whisper"
    description = "ローカルWhisper (faster-whisper) - オフライン対応、CPU/GPU"

    def __init__(self, model: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self._init_model()

    def _init_model(self):
        from faster_whisper import WhisperModel

        logger.info(f"Loading faster-whisper model: {self.model_name} on {self.device}")
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=str(Path.home() / ".cache" / "whisper"),
        )
        logger.info("faster-whisper model loaded")

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        segments_list = []
        full_text = []
        for segment in segments:
            segments_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
            })
            full_text.append(segment.text.strip())

        return {
            "text": " ".join(full_text),
            "language": info.language,
            "duration": info.duration,
            "segments": segments_list,
            "engine": self.name,
        }

    @classmethod
    def is_available(cls) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False


class OpenAIWhisperEngine(TranscriptionEngine):
    """OpenAI Whisper API"""

    name = "openai-whisper"
    description = "OpenAI Whisper API - クラウド、高精度"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        from openai import OpenAI
        self.client = OpenAI(api_key=self.api_key)
        logger.info("OpenAI Whisper API client initialized")

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        with open(audio_path, "rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=language,
                response_format="verbose_json",
            )

        return {
            "text": transcript.text,
            "language": transcript.language,
            "duration": transcript.duration,
            "segments": [],
            "engine": self.name,
        }

    @classmethod
    def get_required_env_vars(cls) -> List[str]:
        return ["OPENAI_API_KEY"]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import openai  # noqa: F401
            return bool(os.getenv("OPENAI_API_KEY"))
        except ImportError:
            return False


class GoogleSpeechEngine(TranscriptionEngine):
    """Google Cloud Speech-to-Text V2"""

    name = "google-speech"
    description = "Google Cloud Speech-to-Text - 日本語高精度、ストリーミング対応"

    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self._init_client()

    def _init_client(self):
        from google.cloud import speech_v1p1beta1 as speech

        if self.credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
        self.client = speech.SpeechClient()
        logger.info("Google Cloud Speech client initialized")

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        from google.cloud import speech_v1p1beta1 as speech
        import wave

        lang_code = self._to_bcp47(language) if language else "ja-JP"

        # WAVファイルのサンプルレートを取得
        with wave.open(audio_path, "rb") as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()

        with open(audio_path, "rb") as f:
            content = f.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            audio_channel_count=channels,
            language_code=lang_code,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
            model="latest_long",
        )

        response = self.client.recognize(config=config, audio=audio)

        segments = []
        full_text = []
        for result in response.results:
            alt = result.alternatives[0]
            full_text.append(alt.transcript)
            if alt.words:
                segments.append({
                    "start": alt.words[0].start_time.total_seconds(),
                    "end": alt.words[-1].end_time.total_seconds(),
                    "text": alt.transcript,
                })

        duration = segments[-1]["end"] if segments else 0.0

        return {
            "text": " ".join(full_text),
            "language": language or "ja",
            "duration": duration,
            "segments": segments,
            "engine": self.name,
        }

    @staticmethod
    def _to_bcp47(lang: str) -> str:
        mapping = {"ja": "ja-JP", "en": "en-US", "zh": "zh-CN", "ko": "ko-KR"}
        return mapping.get(lang, f"{lang}-{lang.upper()}")

    @classmethod
    def get_required_env_vars(cls) -> List[str]:
        return ["GOOGLE_APPLICATION_CREDENTIALS"]

    @classmethod
    def is_available(cls) -> bool:
        try:
            from google.cloud import speech_v1p1beta1  # noqa: F401
            return True
        except ImportError:
            return False


class KotobaWhisperEngine(TranscriptionEngine):
    """Kotoba-Whisper（日本語特化モデル）"""

    name = "kotoba-whisper"
    description = "Kotoba-Whisper - 日本語特化、ローカル実行"

    def __init__(self, model: str = "kotoba-tech/kotoba-whisper-v2.2"):
        self.model_name = model
        self.pipe = None
        self._init_model()

    def _init_model(self):
        import torch
        from transformers import pipeline

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        logger.info(f"Loading Kotoba-Whisper: {self.model_name} on {device}")
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=self.model_name,
            torch_dtype=torch_dtype,
            device=device,
        )
        logger.info("Kotoba-Whisper model loaded")

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        result = self.pipe(
            audio_path,
            chunk_length_s=15,
            batch_size=16,
            return_timestamps=True,
            generate_kwargs={"language": "ja", "task": "transcribe"},
        )

        segments = []
        if result.get("chunks"):
            for chunk in result["chunks"]:
                ts = chunk.get("timestamp", (0, 0))
                segments.append({
                    "start": ts[0] if ts[0] is not None else 0,
                    "end": ts[1] if ts[1] is not None else 0,
                    "text": chunk["text"].strip(),
                })

        duration = segments[-1]["end"] if segments else 0.0

        return {
            "text": result["text"].strip(),
            "language": "ja",
            "duration": duration,
            "segments": segments,
            "engine": self.name,
        }

    @classmethod
    def is_available(cls) -> bool:
        try:
            import transformers  # noqa: F401
            import torch  # noqa: F401
            return True
        except ImportError:
            return False


class AzureSpeechEngine(TranscriptionEngine):
    """Azure Speech Services"""

    name = "azure-speech"
    description = "Azure Speech Services - エンタープライズ向け、多言語対応"

    def __init__(self):
        self.speech_key = os.getenv("AZURE_SPEECH_KEY")
        self.speech_region = os.getenv("AZURE_SPEECH_REGION")
        if not self.speech_key or not self.speech_region:
            raise ValueError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION required")

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        import azure.cognitiveservices.speech as speechsdk

        lang_code = self._to_locale(language) if language else "ja-JP"

        speech_config = speechsdk.SpeechConfig(
            subscription=self.speech_key, region=self.speech_region
        )
        speech_config.speech_recognition_language = lang_code

        audio_config = speechsdk.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )

        all_results = []
        done = False

        def on_recognized(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                all_results.append(evt.result.text)

        def on_stopped(evt):
            nonlocal done
            done = True

        recognizer.recognized.connect(on_recognized)
        recognizer.session_stopped.connect(on_stopped)
        recognizer.canceled.connect(on_stopped)

        recognizer.start_continuous_recognition()
        import asyncio
        while not done:
            await asyncio.sleep(0.1)
        recognizer.stop_continuous_recognition()

        return {
            "text": " ".join(all_results),
            "language": language or "ja",
            "duration": 0.0,
            "segments": [],
            "engine": self.name,
        }

    @staticmethod
    def _to_locale(lang: str) -> str:
        mapping = {"ja": "ja-JP", "en": "en-US", "zh": "zh-CN", "ko": "ko-KR"}
        return mapping.get(lang, f"{lang}-{lang.upper()}")

    @classmethod
    def get_required_env_vars(cls) -> List[str]:
        return ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import azure.cognitiveservices.speech  # noqa: F401
            return bool(os.getenv("AZURE_SPEECH_KEY"))
        except ImportError:
            return False


# エンジンレジストリ
ENGINE_REGISTRY: Dict[str, type] = {
    "faster-whisper": FasterWhisperEngine,
    "openai-whisper": OpenAIWhisperEngine,
    "google-speech": GoogleSpeechEngine,
    "kotoba-whisper": KotobaWhisperEngine,
    "azure-speech": AzureSpeechEngine,
}


def get_available_engines() -> List[Dict[str, Any]]:
    """利用可能なエンジン一覧を返す"""
    engines = []
    for key, cls in ENGINE_REGISTRY.items():
        engines.append({
            "id": key,
            "name": cls.name,
            "description": cls.description,
            "available": cls.is_available(),
            "required_env_vars": cls.get_required_env_vars(),
        })
    return engines


def create_engine(engine_id: str, **kwargs) -> TranscriptionEngine:
    """エンジンIDからインスタンスを生成"""
    if engine_id not in ENGINE_REGISTRY:
        raise ValueError(f"Unknown engine: {engine_id}. Available: {list(ENGINE_REGISTRY.keys())}")

    cls = ENGINE_REGISTRY[engine_id]
    return cls(**kwargs)
