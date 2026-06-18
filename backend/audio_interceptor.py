#!/usr/bin/env python3
"""
Audio Interceptor v4 - マルチプラットフォーム対応
Linux (PulseAudio/PipeWire), macOS (CoreAudio), Windows (WASAPI)
スピーカー出力とマイク入力をインターセプトして記録 + Whisper文字起こし
"""

import os
import sys
import time
import wave
import array
import signal
import subprocess
import threading
import json
import asyncio
import logging
import platform
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# 設定
SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_SECONDS = 10
SAMPLE_WIDTH = 2  # 16-bit


def get_platform():
    """現在のプラットフォームを返す"""
    system = platform.system()
    if system == "Linux":
        return "linux"
    elif system == "Darwin":
        return "macos"
    elif system == "Windows":
        return "windows"
    return system.lower()


class AudioBackend(ABC):
    """音声キャプチャのプラットフォーム抽象化レイヤー"""

    @abstractmethod
    def setup(self, target_sink=None):
        """音声デバイスをセットアップ"""
        pass

    @abstractmethod
    def cleanup(self):
        """音声デバイスをクリーンアップ"""
        pass

    @abstractmethod
    def get_speaker_source(self) -> str:
        """スピーカー録音用のソース識別子を返す"""
        pass

    @abstractmethod
    def get_mic_source(self) -> str:
        """マイク録音用のソース識別子を返す"""
        pass

    @abstractmethod
    def record_chunk(self, source: str, label: str) -> bytes:
        """指定ソースからCHUNK_SECONDS分のPCMデータを録音して返す"""
        pass

    @abstractmethod
    def get_available_sinks(self) -> list:
        """利用可能な出力デバイスのリストを返す"""
        pass


class LinuxAudioBackend(AudioBackend):
    """Linux (PulseAudio/PipeWire) 用バックエンド"""

    def __init__(self):
        self.virtual_sink_name = "virtual_speaker_interceptor"
        self.sink_module_id = None
        self.loopback_module_id = None
        self.default_source = None

    def setup(self, target_sink=None):
        # デフォルトのマイクソースを取得
        try:
            result = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self.default_source = result.stdout.strip()
                logger.info("Default microphone source: %s", self.default_source)
        except Exception:
            pass

        # 仮想スピーカー（null sink）を作成
        result = subprocess.run([
            "pactl", "load-module", "module-null-sink",
            f"sink_name={self.virtual_sink_name}",
            f"sink_properties=device.description='Virtual_Speaker_Interceptor'"
        ], capture_output=True, text=True)

        if result.returncode == 0:
            self.sink_module_id = result.stdout.strip()
            logger.info("Created virtual speaker: %s (module %s)", self.virtual_sink_name, self.sink_module_id)
        else:
            raise Exception(f"Failed to create virtual sink: {result.stderr}")

        # 仮想スピーカーから実際のスピーカーへループバック
        loopback_args = [
            "pactl", "load-module", "module-loopback",
            f"source={self.virtual_sink_name}.monitor",
            "latency_msec=50"
        ]
        if target_sink:
            loopback_args.append(f"sink={target_sink}")
            logger.info("Looping back to: %s", target_sink)

        result = subprocess.run(loopback_args, capture_output=True, text=True)
        if result.returncode == 0:
            self.loopback_module_id = result.stdout.strip()
            logger.info("Created loopback to real speaker (module %s)", self.loopback_module_id)

    def cleanup(self):
        if self.loopback_module_id:
            subprocess.run(["pactl", "unload-module", self.loopback_module_id],
                         stderr=subprocess.DEVNULL)
        if self.sink_module_id:
            subprocess.run(["pactl", "unload-module", self.sink_module_id],
                         stderr=subprocess.DEVNULL)

    def get_speaker_source(self) -> str:
        return f"{self.virtual_sink_name}.monitor"

    def get_mic_source(self) -> str:
        return self.default_source or ""

    def record_chunk(self, source: str, label: str) -> bytes:
        chunk_size = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CHUNK_SECONDS
        process = subprocess.Popen([
            "parec",
            "--device", source,
            "--format", "s16le",
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--raw"
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        audio_data = b''
        bytes_read = 0
        while bytes_read < chunk_size:
            chunk = process.stdout.read(min(8192, chunk_size - bytes_read))
            if not chunk:
                break
            audio_data += chunk
            bytes_read += len(chunk)

        process.terminate()
        try:
            process.wait(timeout=1)
        except Exception:
            process.kill()

        return audio_data

    def get_available_sinks(self) -> list:
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return []
            sinks = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 2:
                    sinks.append({"id": parts[0], "name": parts[1]})
            return sinks
        except Exception:
            return []


class SounddeviceAudioBackend(AudioBackend):
    """macOS / Windows 用バックエンド (sounddevice + PortAudio)"""

    def __init__(self):
        self._sd = None
        self._np = None
        self._speaker_device = None
        self._mic_device = None
        self._loopback_device = None

    def _import_deps(self):
        if self._sd is None:
            try:
                import sounddevice as sd
                import numpy as np
                self._sd = sd
                self._np = np
            except ImportError:
                raise ImportError(
                    "sounddevice と numpy が必要です。\n"
                    "pip install sounddevice numpy"
                )

    def setup(self, target_sink=None):
        self._import_deps()
        sd = self._sd

        current_platform = get_platform()

        # デフォルトデバイスを取得
        default_input, default_output = sd.default.device

        # マイクデバイス
        if default_input is not None and default_input >= 0:
            self._mic_device = default_input
            info = sd.query_devices(default_input)
            logger.info("Default microphone: %s", info['name'])
        else:
            logger.warning("No default input device found")

        # スピーカー（ループバック）デバイス
        if current_platform == "macos":
            self._setup_macos_loopback(target_sink)
        elif current_platform == "windows":
            self._setup_windows_loopback(target_sink)

    def _setup_macos_loopback(self, target_sink=None):
        """macOS: BlackHole / Soundflower などの仮想デバイスを検索"""
        sd = self._sd
        devices = sd.query_devices()

        # 仮想ループバックデバイスを探す
        loopback_names = ["BlackHole", "Soundflower", "Loopback"]
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                for name in loopback_names:
                    if name.lower() in dev['name'].lower():
                        self._loopback_device = i
                        logger.info("Found loopback device: %s", dev['name'])
                        break
            if self._loopback_device is not None:
                break

        if self._loopback_device is None:
            logger.warning("No loopback device found (BlackHole/Soundflower). "
                           "スピーカー音声のキャプチャには BlackHole のインストールが必要です: "
                           "brew install blackhole-2ch / Audio MIDI Setup でマルチ出力デバイスを作成")

        # target_sinkが指定されていれば出力デバイスを設定
        if target_sink:
            for i, dev in enumerate(devices):
                if dev['max_output_channels'] > 0 and target_sink in dev['name']:
                    self._speaker_device = i
                    logger.info("Output device: %s", dev['name'])
                    break

    def _setup_windows_loopback(self, target_sink=None):
        """Windows: WASAPI loopback を使用"""
        sd = self._sd
        devices = sd.query_devices()

        # Windows WASAPI loopback デバイスを探す
        # sounddevice は hostapi=WASAPI の場合、ループバック入力が利用可能
        for i, dev in enumerate(devices):
            name_lower = dev['name'].lower()
            if dev['max_input_channels'] > 0 and (
                'loopback' in name_lower or
                'stereo mix' in name_lower or
                'what u hear' in name_lower or
                'wave out' in name_lower
            ):
                self._loopback_device = i
                logger.info("Found loopback device: %s", dev['name'])
                break

        if self._loopback_device is None:
            # WASAPI loopback を試行 (sounddevice >= 0.4.0)
            for i, dev in enumerate(devices):
                if dev['max_output_channels'] > 0 and dev.get('hostapi') is not None:
                    hostapi = sd.query_hostapis(dev['hostapi'])
                    if 'wasapi' in hostapi.get('name', '').lower():
                        # WASAPI output devices can be opened as loopback
                        self._loopback_device = i
                        logger.info("Using WASAPI loopback: %s", dev['name'])
                        break

        if self._loopback_device is None:
            logger.warning("No loopback device found. "
                           "スピーカー音声のキャプチャには「ステレオミキサー」を有効にするか、"
                           "VB-Audio Virtual Cable のインストールが必要な場合があります。")

        if target_sink:
            for i, dev in enumerate(devices):
                if dev['max_output_channels'] > 0 and target_sink in dev['name']:
                    self._speaker_device = i
                    logger.info("Output device: %s", dev['name'])
                    break

    def cleanup(self):
        # sounddevice は明示的なクリーンアップ不要
        pass

    def get_speaker_source(self) -> str:
        if self._loopback_device is not None:
            return str(self._loopback_device)
        return ""

    def get_mic_source(self) -> str:
        if self._mic_device is not None:
            return str(self._mic_device)
        return ""

    def record_chunk(self, source: str, label: str) -> bytes:
        sd = self._sd
        np = self._np

        device_id = int(source) if source else None
        num_frames = SAMPLE_RATE * CHUNK_SECONDS

        try:
            recording = sd.rec(
                frames=num_frames,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype='int16',
                device=device_id,
                blocking=True
            )
            return recording.tobytes()
        except Exception as e:
            logger.error("Recording error (%s): %s", label, e)
            return b''

    def get_available_sinks(self) -> list:
        self._import_deps()
        sd = self._sd
        devices = sd.query_devices()
        sinks = []
        for i, dev in enumerate(devices):
            if dev['max_output_channels'] > 0:
                sinks.append({"id": str(i), "name": dev['name']})
        return sinks


def create_audio_backend() -> AudioBackend:
    """プラットフォームに応じた AudioBackend を返す"""
    current_platform = get_platform()
    if current_platform == "linux":
        return LinuxAudioBackend()
    elif current_platform in ("macos", "windows"):
        return SounddeviceAudioBackend()
    else:
        logger.warning("Unknown platform: %s, falling back to sounddevice", current_platform)
        return SounddeviceAudioBackend()


class AudioInterceptor:
    def __init__(self, tmp_dir="./tmp", target_sink=None, transcribe_enabled=False, on_transcript=None):
        self.tmp_dir = Path(tmp_dir)
        self.running = True
        self.threads = []
        self.target_sink = target_sink
        self.transcribe_enabled = transcribe_enabled
        self.on_transcript = on_transcript
        self.mic_muted = False
        self.backend = create_audio_backend()
        self.recorded_chunks: Dict[str, list] = {"speaker": [], "mic": []}

        # Transcription Serviceの初期化（遅延初期化）
        self.transcription_service = None
        if self.transcribe_enabled:
            try:
                from transcription import get_transcription_service
                self.transcription_service = get_transcription_service()
                logger.info("Transcription Service initialized: engine=%s", self.transcription_service.engine_id)
            except Exception as e:
                logger.warning("Failed to initialize Transcription Service: %s. Falling back to recording only mode.", e)
                self.transcribe_enabled = False

    def setup(self):
        """音声デバイスをセットアップ"""
        logger.info("Setting up audio devices (platform: %s)...", get_platform())

        try:
            self.backend.setup(target_sink=self.target_sink)

            speaker_src = self.backend.get_speaker_source()
            mic_src = self.backend.get_mic_source()

            logger.info("Setup complete! Speaker source: %s, Microphone: %s, Transcription: %s",
                        speaker_src or '(none)', mic_src or 'default',
                        'ENABLED' if self.transcribe_enabled else 'DISABLED')

        except Exception as e:
            logger.error("Setup failed: %s", e, exc_info=True)
            self.cleanup()
            sys.exit(1)

    def set_mic_mute(self, muted: bool):
        """マイクのミュート状態を設定"""
        self.mic_muted = muted
        logger.info("Microphone %s", "MUTED" if muted else "UNMUTED")

    def cleanup(self):
        """音声デバイスをクリーンアップ"""
        logger.info("Cleaning up audio devices...")
        self.running = False

        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2)

        self.backend.cleanup()
        logger.info("Audio cleanup complete")

    def start_intercepting(self):
        """音声インターセプションを開始"""
        logger.info("Starting audio interception...")

        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        # スピーカー出力を録音
        speaker_src = self.backend.get_speaker_source()
        if speaker_src:
            speaker_thread = threading.Thread(
                target=self.record_audio_stream,
                args=(speaker_src, "speaker"),
                daemon=True
            )
            speaker_thread.start()
            self.threads.append(speaker_thread)
        else:
            logger.warning("No speaker loopback source available, skipping speaker recording")

        # マイク入力を録音
        mic_src = self.backend.get_mic_source()
        if mic_src:
            mic_thread = threading.Thread(
                target=self.record_audio_stream,
                args=(mic_src, "mic"),
                daemon=True
            )
            mic_thread.start()
            self.threads.append(mic_thread)
        else:
            logger.warning("No default microphone found, only recording speaker output")

        logger.info("Saving 10-second chunks to: %s", self.tmp_dir.absolute())

    def record_audio_stream(self, source, label):
        """音声ストリームを10秒チャンクで録音"""
        chunk_index = 0

        while self.running:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = self.tmp_dir / f"{label}_{timestamp}_{chunk_index}.wav"

                logger.debug("Recording %s chunk %d...", label, chunk_index)

                audio_data = self.backend.record_chunk(source, label)

                if not self.running:
                    break

                if audio_data:
                    # マイクミュート中はスキップ
                    if label == "mic" and self.mic_muted:
                        logger.debug("Mic muted - skipping chunk %d", chunk_index)
                        chunk_index += 1
                        continue

                    self.write_wav(filename, audio_data)
                    self.recorded_chunks[label].append(filename)
                    size_kb = len(audio_data) / 1024
                    logger.debug("Saved %s chunk %d: %s (%.1f KB)", label, chunk_index, filename.name, size_kb)

                    if self.transcribe_enabled:
                        transcribe_thread = threading.Thread(
                            target=self.transcribe_audio,
                            args=(filename, label),
                            daemon=True
                        )
                        transcribe_thread.start()

                chunk_index += 1

            except Exception as e:
                if self.running:
                    logger.error("Error recording %s: %s", label, e)
                    time.sleep(1)
                else:
                    break

    def write_wav(self, filename, pcm_data):
        """PCMデータをWAVファイルとして書き込む"""
        try:
            with wave.open(str(filename), 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(pcm_data)
        except Exception as e:
            logger.error("Failed to write WAV file %s: %s", filename, e)

    def merge_recording(self, output_path: str) -> Optional[str]:
        """全チャンクを結合して1つのWAVファイルとして保存する。
        speaker と mic の両方のチャンクを時系列順にミックスする。
        Returns: 保存先パス or None (チャンクがない場合)
        """
        all_chunks = []
        for label in ("speaker", "mic"):
            for path in self.recorded_chunks.get(label, []):
                if path.exists():
                    all_chunks.append(path)

        if not all_chunks:
            logger.info("No recorded chunks to merge")
            return None

        # ファイル名のタイムスタンプ順にソート
        all_chunks.sort(key=lambda p: p.name)

        try:
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)

            with wave.open(str(output), 'wb') as out_wav:
                out_wav.setnchannels(CHANNELS)
                out_wav.setsampwidth(SAMPLE_WIDTH)
                out_wav.setframerate(SAMPLE_RATE)

                for chunk_path in all_chunks:
                    try:
                        with wave.open(str(chunk_path), 'rb') as in_wav:
                            out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))
                    except Exception as e:
                        logger.warning("Failed to read chunk %s: %s", chunk_path, e)

            size_mb = output.stat().st_size / (1024 * 1024)
            logger.info("Merged recording saved: %s (%.1f MB, %d chunks)", output, size_mb, len(all_chunks))
            return str(output)
        except Exception as e:
            logger.error("Failed to merge recording: %s", e, exc_info=True)
            return None

    def is_silent(self, filename, threshold=500):
        """音声ファイルが無音かどうかをチェック"""
        try:
            with wave.open(str(filename), 'rb') as wav_file:
                n_frames = wav_file.getnframes()
                frames = wav_file.readframes(n_frames)
                samples = array.array('h', frames)
                if len(samples) == 0:
                    return True
                sum_squares = sum(s * s for s in samples)
                rms = (sum_squares / len(samples)) ** 0.5
                return rms < threshold
        except Exception as e:
            logger.warning("Failed to check silence: %s", e)
            return False

    def transcribe_audio(self, filename, label):
        """Transcription Serviceを使って文字起こし"""
        try:
            if self.is_silent(filename):
                logger.debug("Skipping silent audio: %s", filename.name)
                return

            if not self.transcription_service:
                logger.warning("Transcription service not available")
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.transcription_service.transcribe(str(filename))
                )
            finally:
                loop.close()

            text = result.get('text', '').strip()

            # ハルシネーション対策フィルタ
            hallucination_phrases = [
                'ご視聴ありがとうございました',
                'ご視聴ありがとうございます',
                'チャンネル登録',
                '高評価',
                'ご清聴ありがとうございました',
                'Thanks for watching',
                'Subscribe',
                'Like and subscribe'
            ]

            if text and len(text) < 50:
                for phrase in hallucination_phrases:
                    if phrase in text:
                        logger.debug("Filtered hallucination: %s", text)
                        return

            if text:
                logger.info("[%s] %s", label.upper(), text)

                if self.on_transcript:
                    try:
                        self.on_transcript(label, text)
                    except Exception as cb_err:
                        logger.error("Transcript callback error: %s", cb_err)

        except Exception as e:
            logger.error("Transcription error: %s", e, exc_info=True)


def get_available_sinks():
    """利用可能なシンク（出力デバイス）のリストを返す（後方互換）"""
    backend = create_audio_backend()
    return [s["name"] for s in backend.get_available_sinks()]


def select_sink():
    """インタラクティブにスピーカーを選択"""
    sinks = get_available_sinks()
    if not sinks:
        print("⚠️  No sinks found. Using default.")
        return None

    print("\n🔊 Available Output Devices:")
    for i, sink in enumerate(sinks):
        print(f"  [{i+1}] {sink}")
    print(f"  [Enter] Default (OS setting)")

    while True:
        try:
            choice = input("\nSelect output device (number): ").strip()
            if not choice:
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(sinks):
                return sinks[idx]
            print("Invalid selection. Try again.")
        except ValueError:
            print("Please enter a number.")


def select_mode():
    """インタラクティブにモードを選択"""
    print("\n🎙️  Operation Mode:")
    print("  [1] Recording only (WAV)")
    print("  [2] Recording + Transcription (Whisper API)")

    while True:
        choice = input("\nSelect mode [1/2]: ").strip()
        if choice == "1" or not choice:
            return False
        if choice == "2":
            if not os.environ.get("OPENAI_API_KEY"):
                print("❌ OPENAI_API_KEY not found. Please set it first.")
                continue
            return True


def print_instructions(interceptor):
    """使用方法を表示"""
    current_platform = get_platform()
    print("\n" + "="*60)
    print("🎧 Audio Interceptor Started")
    print(f"   Platform: {current_platform}")
    print("="*60)

    if current_platform == "linux":
        print("\n📝 Setup Instructions:")
        speaker_src = interceptor.backend.get_speaker_source()
        mic_src = interceptor.backend.get_mic_source()
        print(f"   1. Open your meeting app (Zoom, Discord, Meet, etc.)")
        print(f"   2. Set the app's SPEAKER/OUTPUT to:")
        print(f"      → Virtual_Speaker_Interceptor")
        print(f"   3. Keep your MICROPHONE as:")
        print(f"      → {mic_src or 'default microphone'}")
    elif current_platform == "macos":
        print("\n📝 Setup Instructions (macOS):")
        print(f"   1. BlackHole をインストール: brew install blackhole-2ch")
        print(f"   2. Audio MIDI Setup でマルチ出力デバイスを作成")
        print(f"      (内蔵出力 + BlackHole 2ch)")
        print(f"   3. システム出力をマルチ出力デバイスに設定")
    elif current_platform == "windows":
        print("\n📝 Setup Instructions (Windows):")
        print(f"   1. サウンド設定で「ステレオミキサー」を有効化")
        print(f"      または VB-Audio Virtual Cable をインストール")
        print(f"   2. 会議アプリのスピーカー出力を仮想デバイスに設定")

    print(f"\n💾 Recording:")
    print(f"   - Location: {interceptor.tmp_dir.absolute()}")
    print(f"   - Format: 10-second WAV chunks")
    print(f"   - Mode: {'Transcription + Recording' if interceptor.transcribe_enabled else 'Recording only'}")
    print("\n⚠️  Press Ctrl+C to stop recording and cleanup")
    print("="*60 + "\n")


def main():
    tmp_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "./tmp"

    print(f"\n=== Audio Interceptor Setup (Platform: {get_platform()}) ===")

    transcribe_enabled = select_mode()
    target_sink = select_sink()

    interceptor = AudioInterceptor(tmp_dir, target_sink, transcribe_enabled)

    def shutdown_handler(sig, frame):
        print("\n\n⚠️  Shutdown signal received...")
        interceptor.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        interceptor.setup()
        interceptor.start_intercepting()
        print_instructions(interceptor)

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        interceptor.cleanup()


if __name__ == "__main__":
    main()
