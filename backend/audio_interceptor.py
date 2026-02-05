#!/usr/bin/env python3
"""
Audio Interceptor v3 - PulseAudio/PipeWire両対応
スピーカー出力とマイク入力をインターセプトして記録 + Whisper API文字起こし
"""

import os
import sys
import time
import wave
import signal
import subprocess
import threading
import json
import uuid
import urllib.request
import urllib.error
import array
from pathlib import Path
from datetime import datetime

# 設定
SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_SECONDS = 10
SAMPLE_WIDTH = 2  # 16-bit

class AudioInterceptor:
    def __init__(self, tmp_dir="./tmp", target_sink=None, transcribe_mode=False, on_transcript=None):
        self.virtual_sink_name = "virtual_speaker_interceptor"
        self.tmp_dir = Path(tmp_dir)
        self.running = True
        self.sink_module_id = None
        self.loopback_module_id = None
        self.threads = []
        self.default_source = None
        self.target_sink = target_sink
        self.transcribe_mode = transcribe_mode
        self.on_transcript = on_transcript
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        
        if self.transcribe_mode and not self.openai_api_key:
            print("⚠️  Warning: Transcribe mode enabled but OPENAI_API_KEY is not set.")
            print("   Falling back to recording only mode.")
            self.transcribe_mode = False
            
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
                "latency_msec=1"
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
            if self.transcribe_mode:
                print("   📝 Transcription: ENABLED (Whisper API)")
            else:
                print("   📝 Transcription: DISABLED")
            
        except Exception as e:
            print(f"❌ Setup failed: {e}")
            self.cleanup()
            sys.exit(1)
    
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
        print("\n🎙️  Starting audio interception...")
        
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
        
        print(f"💾 Saving 10-second chunks to: {self.tmp_dir.absolute()}")
    
    def record_audio_stream(self, source, label):
        """音声ストリームを10秒チャンクで録音"""
        chunk_index = 0
        
        while self.running:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = self.tmp_dir / f"{label}_{timestamp}_{chunk_index}.wav"
                
                print(f"⏺️  Recording {label} chunk {chunk_index}...")
                
                # parecで音声をキャプチャ
                chunk_size = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CHUNK_SECONDS
                
                process = subprocess.Popen([
                    "parec",
                    "--device", source,
                    "--format", "s16le",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", str(CHANNELS),
                    "--raw"
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                
                # 10秒分のデータを読み込む
                audio_data = b''
                bytes_read = 0
                
                while bytes_read < chunk_size and self.running:
                    chunk = process.stdout.read(min(8192, chunk_size - bytes_read))
                    if not chunk:
                        break
                    audio_data += chunk
                    bytes_read += len(chunk)
                
                # プロセスを終了
                process.terminate()
                try:
                    process.wait(timeout=1)
                except:
                    process.kill()
                
                if not self.running:
                    break
                
                # WAVファイルに書き込む
                if audio_data:
                    self.write_wav(filename, audio_data)
                    size_kb = len(audio_data) / 1024
                    print(f"✅ Saved {label} chunk {chunk_index}: {filename.name} ({size_kb:.1f} KB)")
                    
                    # 文字起こしモードならAPIに投げる
                    if self.transcribe_mode:
                        transcribe_thread = threading.Thread(
                            target=self.transcribe_audio,
                            args=(filename, label),
                            daemon=True
                        )
                        transcribe_thread.start()
                
                chunk_index += 1
                
            except Exception as e:
                if self.running:
                    print(f"❌ Error recording {label}: {e}")
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
            print(f"❌ Failed to write WAV file {filename}: {e}")

    def is_silent(self, filename, threshold=500):
        """音声ファイルが無音かどうかをチェック"""
        try:
            with wave.open(str(filename), 'rb') as wav_file:
                # サンプル数を取得
                n_frames = wav_file.getnframes()
                
                # 全フレームを読み込む
                frames = wav_file.readframes(n_frames)
                
                # 16-bit PCMデータをint16配列に変換
                samples = array.array('h', frames)
                
                # RMS（二乗平均平方根）を計算
                if len(samples) == 0:
                    return True
                
                sum_squares = sum(s * s for s in samples)
                rms = (sum_squares / len(samples)) ** 0.5
                
                # 閾値以下なら無音とみなす
                return rms < threshold
        except Exception as e:
            print(f"⚠️ Failed to check silence: {e}")
            return False
    
    def transcribe_audio(self, filename, label):
        """Whisper APIを使って文字起こし"""
        try:
            # 無音チェック
            if self.is_silent(filename):
                print(f"🔇 Skipping silent audio: {filename.name}")
                return
            
            boundary = uuid.uuid4().hex
            data = []
            
            # File part
            data.append(f'--{boundary}'.encode())
            data.append(f'Content-Disposition: form-data; name="file"; filename="{filename.name}"'.encode())
            data.append(b'Content-Type: audio/wav')
            data.append(b'')
            
            with open(filename, 'rb') as f:
                audio_bytes = f.read()
                data.append(audio_bytes)
            
            # Model part
            data.append(f'--{boundary}'.encode())
            data.append(b'Content-Disposition: form-data; name="model"')
            data.append(b'')
            data.append(b'whisper-1')
            
            # Language (optional, auto-detect is usually fine but 'ja' helps accuracy)
            data.append(f'--{boundary}'.encode())
            data.append(b'Content-Disposition: form-data; name="language"')
            data.append(b'')
            data.append(b'ja')
            
            # Prompt to improve accuracy and avoid hallucinations
            data.append(f'--{boundary}'.encode())
            data.append(b'Content-Disposition: form-data; name="prompt"')
            data.append(b'')
            data.append('会議の音声です。無音の場合は空文字を返してください。'.encode('utf-8'))

            # End marker
            data.append(f'--{boundary}--'.encode())
            data.append(b'')
            
            body = b'\r\n'.join(data)
            
            req = urllib.request.Request(
                "https://api.openai.com/v1/audio/transcriptions",
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Authorization": f"Bearer {self.openai_api_key}"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                text = result.get('text', '').strip()
                
                # 定型文フィルタリング（Whisperのハルシネーション対策）
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
                
                # 定型文が含まれていて、かつ短い場合はスキップ
                if text and len(text) < 50:
                    for phrase in hallucination_phrases:
                        if phrase in text:
                            print(f"🚫 Filtered hallucination: {text}")
                            return
                
                if text:
                    # ログに出力
                    prefix = "[Speaker 🔊]" if label == "speaker" else "[Mic 🎤]"
                    print(f"\n{prefix} {text}\n")
                    
                    # コールバックがあれば呼ぶ
                    if self.on_transcript:
                        try:
                            self.on_transcript(label, text)
                        except Exception as cb_err:
                            print(f"⚠️ Callback error: {cb_err}")
                    
        except urllib.error.HTTPError as e:
            print(f"⚠️ Transcription failed: HTTP {e.code} - {e.reason}")
        except Exception as e:
            print(f"⚠️ Transcription error: {e}")

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
    print("\n" + "="*60)
    print("🎧 Audio Interceptor Started")
    print("="*60)
    print("\n📝 Setup Instructions:")
    print(f"   1. Open your meeting app (Zoom, Discord, Meet, etc.)")
    print(f"   2. Set the app's SPEAKER/OUTPUT to:")
    print(f"      → Virtual_Speaker_Interceptor")
    print(f"   3. Keep your MICROPHONE as:")
    print(f"      → {interceptor.default_source or 'default microphone'}")
    print(f"\n💾 Recording:")
    print(f"   - Location: {interceptor.tmp_dir.absolute()}")
    print(f"   - Format: 10-second WAV chunks")
    print(f"   - Mode: {'Transcription + Recording' if interceptor.transcribe_mode else 'Recording only'}")
    if interceptor.target_sink:
        print(f"   - Loopback: {interceptor.target_sink}")
    else:
        print(f"   - Loopback: Default System Output")
    print("\n⚠️  Press Ctrl+C to stop recording and cleanup")
    print("="*60 + "\n")

def main():
    # 引数から出力ディレクトリを取得
    tmp_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "./tmp"
    
    print("\n=== Audio Interceptor Setup ===")
    
    # モード選択
    transcribe_mode = select_mode()
    
    # スピーカー選択
    target_sink = select_sink()
    
    # インターセプターを初期化
    interceptor = AudioInterceptor(tmp_dir, target_sink, transcribe_mode)
    
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
