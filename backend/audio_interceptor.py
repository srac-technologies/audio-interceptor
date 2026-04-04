#!/usr/bin/env python3
"""
Audio Interceptor v4 - VAD統合版
チャンクベース文字起こし + VADによる発言区間検出・再文字起こし
"""

import os
import sys
import time
import wave
import signal
import subprocess
import threading
import json
import array
import asyncio
from pathlib import Path
from datetime import datetime

from vad_service import VADService, stereo_to_mono

# 設定
SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_SECONDS = 10          # interim文字起こしの間隔(秒)
MAX_UTTERANCE_SECONDS = 60  # 最大発言長(秒) - これを超えたら強制的にfinal
SAMPLE_WIDTH = 2            # 16-bit
VAD_FRAME_MS = 30           # VADフレーム長(ms)

class AudioInterceptor:
    def __init__(self, tmp_dir="./tmp", target_sink=None, transcribe_enabled=False, on_transcript=None):
        self.virtual_sink_name = "virtual_speaker_interceptor"
        self.tmp_dir = Path(tmp_dir)
        self.running = True
        self.sink_module_id = None
        self.loopback_module_id = None
        self.threads = []
        self.default_source = None
        self.target_sink = target_sink
        self.transcribe_enabled = transcribe_enabled
        self.on_transcript = on_transcript
        self.mic_muted = False

        # Transcription Serviceの初期化（遅延初期化）
        self.transcription_service = None
        if self.transcribe_enabled:
            try:
                from transcription import get_transcription_service
                self.transcription_service = get_transcription_service()
                print(f"✅ Transcription Service initialized: mode={self.transcription_service.mode}, model={self.transcription_service.model_name}")
            except Exception as e:
                print(f"⚠️  Warning: Failed to initialize Transcription Service: {e}")
                print("   Falling back to recording only mode.")
                self.transcribe_enabled = False

    def get_default_source(self):
        """デフォルトのマイクソースを取得"""
        try:
            result = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    def setup(self):
        """仮想オーディオデバイスをセットアップ"""
        print("Setting up virtual audio devices...")

        try:
            # デフォルトのマイクソースを取得
            self.default_source = self.get_default_source()
            if self.default_source:
                print(f"Default microphone source: {self.default_source}")

            # 仮想スピーカー（null sink）を作成
            result = subprocess.run([
                "pactl", "load-module", "module-null-sink",
                f"sink_name={self.virtual_sink_name}",
                f"sink_properties=device.description='Virtual_Speaker_Interceptor'"
            ], capture_output=True, text=True)

            if result.returncode == 0:
                self.sink_module_id = result.stdout.strip()
                print(f"✅ Created virtual speaker: {self.virtual_sink_name} (module {self.sink_module_id})")
            else:
                raise Exception(f"Failed to create virtual sink: {result.stderr}")

            # 仮想スピーカーから実際のスピーカーへループバック
            loopback_args = [
                "pactl", "load-module", "module-loopback",
                f"source={self.virtual_sink_name}.monitor",
                "latency_msec=50"
            ]

            # ターゲットシンクが指定されている場合は追加
            if self.target_sink:
                loopback_args.append(f"sink={self.target_sink}")
                print(f"   Looping back to: {self.target_sink}")

            result = subprocess.run(loopback_args, capture_output=True, text=True)

            if result.returncode == 0:
                self.loopback_module_id = result.stdout.strip()
                print(f"✅ Created loopback to real speaker (module {self.loopback_module_id})")

            print("\n📋 Setup complete!")
            print(f"   Virtual Speaker: {self.virtual_sink_name}")
            print(f"   Microphone: {self.default_source or 'default'}")
            if self.transcribe_enabled:
                print("   📝 Transcription: ENABLED (VAD + Chunk)")
            else:
                print("   📝 Transcription: DISABLED")

        except Exception as e:
            print(f"❌ Setup failed: {e}")
            self.cleanup()
            sys.exit(1)

    def set_mic_mute(self, muted: bool):
        """マイクのミュート状態を設定"""
        self.mic_muted = muted
        status = "MUTED 🔇" if muted else "UNMUTED 🎤"
        print(f"🎤 Microphone {status}")

    def cleanup(self):
        """仮想オーディオデバイスをクリーンアップ"""
        print("\n🧹 Cleaning up virtual audio devices...")
        self.running = False

        # スレッドの終了を待つ
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2)

        # モジュールをアンロード
        if self.loopback_module_id:
            subprocess.run(["pactl", "unload-module", self.loopback_module_id],
                         stderr=subprocess.DEVNULL)

        if self.sink_module_id:
            subprocess.run(["pactl", "unload-module", self.sink_module_id],
                         stderr=subprocess.DEVNULL)

        print("✅ Cleanup complete")

    def start_intercepting(self):
        """音声インターセプションを開始"""
        print("\n🎙️  Starting audio interception (VAD + Chunk mode)...")

        # 出力ディレクトリを作成
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        # スピーカー出力を録音（会議アプリからの出力）
        speaker_thread = threading.Thread(
            target=self.record_audio_stream,
            args=(f"{self.virtual_sink_name}.monitor", "speaker"),
            daemon=True
        )
        speaker_thread.start()
        self.threads.append(speaker_thread)

        # マイク入力を録音（実際のマイクから）
        if self.default_source:
            mic_thread = threading.Thread(
                target=self.record_audio_stream,
                args=(self.default_source, "mic"),
                daemon=True
            )
            mic_thread.start()
            self.threads.append(mic_thread)
        else:
            print("⚠️  Warning: No default microphone found, only recording speaker output")

        print(f"💾 VAD-based recording with {CHUNK_SECONDS}s interim chunks")
        print(f"   Max utterance: {MAX_UTTERANCE_SECONDS}s, tmp dir: {self.tmp_dir.absolute()}")

    def record_audio_stream(self, source, label):
        """VAD統合の音声ストリーム録音

        アーキテクチャ:
        - 30msフレーム単位でオーディオを連続読み取り
        - VADで発言開始/終了を検出
        - 発言中は CHUNK_SECONDS 秒ごとに interim 文字起こし（リアルタイムフィードバック）
        - 発言終了時に発言全体を final 文字起こし（高精度、interimを置換）
        - 発言が MAX_UTTERANCE_SECONDS を超えたら強制的に final
        """
        vad = VADService(
            sample_rate=SAMPLE_RATE,
            frame_duration_ms=VAD_FRAME_MS,
            aggressiveness=2,
            speech_pad_ms=600,
            min_speech_ms=500
        )

        # フレームサイズ計算
        stereo_frame_bytes = vad.frame_size * CHANNELS * SAMPLE_WIDTH  # 48000 * 0.03 * 2 * 2 = 5760

        # 状態管理
        utterance_audio = bytearray()   # 現在の発言のオーディオ全体
        utterance_id = 0                # 発言ID（source内で一意）
        in_utterance = False            # 発言中フラグ
        last_interim_time = 0.0         # 最後のinterim送信時刻
        interim_count = 0               # 現在の発言内でのinterim数

        # parec起動（長期稼働プロセス）
        process = subprocess.Popen([
            "parec",
            "--device", source,
            "--format", "s16le",
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--raw"
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        try:
            while self.running:
                # 1フレーム読み込み (30ms)
                stereo_data = process.stdout.read(stereo_frame_bytes)
                if not stereo_data or len(stereo_data) < stereo_frame_bytes:
                    if self.running:
                        print(f"⚠️ {label}: parec stream ended unexpectedly")
                    break

                # マイクミュート中はVAD処理をスキップ
                if label == "mic" and self.mic_muted:
                    continue

                # VAD処理（モノラル変換して判定）
                mono_data = stereo_to_mono(stereo_data)
                vad_result = vad.process_frame(mono_data)

                # --- 発言開始 ---
                if vad_result["event"] == "speech_start":
                    in_utterance = True
                    utterance_audio = bytearray()
                    last_interim_time = time.time()
                    interim_count = 0
                    print(f"🗣️  [{label}] Speech started (utterance #{utterance_id})")

                # --- 発言中: オーディオ蓄積 ---
                if in_utterance:
                    utterance_audio.extend(stereo_data)

                    now = time.time()

                    # CHUNK_SECONDS ごとに interim 文字起こし
                    if (now - last_interim_time) >= CHUNK_SECONDS and self.transcribe_enabled:
                        interim_count += 1
                        print(f"⏺️  [{label}] Interim transcription #{interim_count} (utterance #{utterance_id})")
                        self._transcribe_and_emit(
                            bytes(utterance_audio), label, utterance_id, is_final=False
                        )
                        last_interim_time = now

                    # 最大発言長チェック
                    utterance_duration = len(utterance_audio) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
                    if utterance_duration >= MAX_UTTERANCE_SECONDS:
                        print(f"⚠️  [{label}] Max utterance length reached ({MAX_UTTERANCE_SECONDS}s), forcing final")
                        vad.force_end()
                        if self.transcribe_enabled:
                            self._transcribe_and_emit(
                                bytes(utterance_audio), label, utterance_id, is_final=True
                            )
                        utterance_id += 1
                        utterance_audio = bytearray()
                        in_utterance = False
                        interim_count = 0
                        continue

                # --- 発言終了 ---
                if vad_result["event"] == "speech_end" and in_utterance:
                    duration = len(utterance_audio) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
                    print(f"🔇 [{label}] Speech ended (utterance #{utterance_id}, {duration:.1f}s, {interim_count} interims)")

                    if self.transcribe_enabled and utterance_audio:
                        self._transcribe_and_emit(
                            bytes(utterance_audio), label, utterance_id, is_final=True
                        )

                    utterance_id += 1
                    utterance_audio = bytearray()
                    in_utterance = False
                    interim_count = 0

        except Exception as e:
            if self.running:
                print(f"❌ Error in {label} recording loop: {e}")
                import traceback
                traceback.print_exc()
        finally:
            process.terminate()
            try:
                process.wait(timeout=1)
            except:
                process.kill()

            # 残りの発言があればfinalとして処理
            if in_utterance and utterance_audio and self.transcribe_enabled:
                print(f"🔇 [{label}] Flushing remaining utterance #{utterance_id}")
                self._transcribe_and_emit(
                    bytes(utterance_audio), label, utterance_id, is_final=True
                )

    def _transcribe_and_emit(self, audio_data: bytes, label: str, utterance_id: int, is_final: bool):
        """オーディオデータを文字起こしして結果をコールバックで通知"""
        transcribe_thread = threading.Thread(
            target=self._do_transcribe,
            args=(audio_data, label, utterance_id, is_final),
            daemon=True
        )
        transcribe_thread.start()

    def _do_transcribe(self, audio_data: bytes, label: str, utterance_id: int, is_final: bool):
        """文字起こし実行（ワーカースレッド）"""
        try:
            # WAVファイルに書き込み
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = "final" if is_final else "interim"
            filename = self.tmp_dir / f"{label}_{timestamp}_{utterance_id}_{suffix}.wav"
            self._write_wav(filename, audio_data)

            # 無音チェック
            if self._is_silent(audio_data):
                print(f"🔇 Skipping silent audio: {filename.name}")
                return

            if not self.transcription_service:
                return

            # asyncioループで実行
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
                        print(f"🚫 Filtered hallucination: {text}")
                        return

            if text:
                prefix = "[Speaker 🔊]" if label == "speaker" else "[Mic 🎤]"
                mode = "FINAL" if is_final else "INTERIM"
                print(f"\n{prefix} [{mode}] utt#{utterance_id}: {text}\n")

                if self.on_transcript:
                    try:
                        self.on_transcript(label, text, utterance_id, is_final)
                    except Exception as cb_err:
                        print(f"⚠️ Callback error: {cb_err}")

        except Exception as e:
            print(f"⚠️ Transcription error: {e}")

    def _write_wav(self, filename, pcm_data):
        """PCMデータをWAVファイルとして書き込む"""
        try:
            with wave.open(str(filename), 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(pcm_data)
        except Exception as e:
            print(f"❌ Failed to write WAV file {filename}: {e}")

    def _is_silent(self, pcm_data, threshold=500):
        """PCMデータが無音かどうかをチェック"""
        try:
            samples = array.array('h', pcm_data)
            if len(samples) == 0:
                return True
            sum_squares = sum(s * s for s in samples)
            rms = (sum_squares / len(samples)) ** 0.5
            return rms < threshold
        except Exception as e:
            print(f"⚠️ Failed to check silence: {e}")
            return False


def get_available_sinks():
    """利用可能なシンク（出力デバイス）のリストを返す"""
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
                sinks.append(parts[1])
        return sinks
    except:
        return []

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
    print("  [2] Recording + Transcription (VAD + Chunk)")

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
    print("\n" + "="*60)
    print("🎧 Audio Interceptor Started (VAD + Chunk Mode)")
    print("="*60)
    print("\n📝 Setup Instructions:")
    print(f"   1. Open your meeting app (Zoom, Discord, Meet, etc.)")
    print(f"   2. Set the app's SPEAKER/OUTPUT to:")
    print(f"      → Virtual_Speaker_Interceptor")
    print(f"   3. Keep your MICROPHONE as:")
    print(f"      → {interceptor.default_source or 'default microphone'}")
    print(f"\n💾 Recording:")
    print(f"   - Location: {interceptor.tmp_dir.absolute()}")
    print(f"   - Mode: {'VAD + Chunk Transcription' if interceptor.transcribe_enabled else 'Recording only'}")
    print(f"   - Interim interval: {CHUNK_SECONDS}s")
    print(f"   - Max utterance: {MAX_UTTERANCE_SECONDS}s")
    if interceptor.target_sink:
        print(f"   - Loopback: {interceptor.target_sink}")
    else:
        print(f"   - Loopback: Default System Output")
    print("\n⚠️  Press Ctrl+C to stop recording and cleanup")
    print("="*60 + "\n")

def main():
    # 引数から出力ディレクトリを取得
    tmp_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "./tmp"

    print("\n=== Audio Interceptor Setup (VAD + Chunk) ===")

    # モード選択
    transcribe_enabled = select_mode()

    # スピーカー選択
    target_sink = select_sink()

    # インターセプターを初期化
    interceptor = AudioInterceptor(tmp_dir, target_sink, transcribe_enabled)

    # シグナルハンドラを設定
    def shutdown_handler(sig, frame):
        print("\n\n⚠️  Shutdown signal received...")
        interceptor.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # セットアップ
        interceptor.setup()

        # インターセプション開始
        interceptor.start_intercepting()

        # 使い方を表示
        print_instructions(interceptor)

        # メインスレッドを維持
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
