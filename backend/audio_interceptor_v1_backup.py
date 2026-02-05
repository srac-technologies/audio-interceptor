#!/usr/bin/env python3
"""
Audio Interceptor - Web会議音声インターセプター
マイクとスピーカーの入出力を仮想デバイス経由でキャプチャし、WAVファイルに保存
"""

import os
import sys
import time
import wave
import signal
import struct
import subprocess
import threading
from pathlib import Path
from datetime import datetime

# 設定
SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_SECONDS = 10
SAMPLE_WIDTH = 2  # 16-bit

class AudioInterceptor:
    def __init__(self, tmp_dir="./tmp"):
        self.virtual_sink_name = "virtual_speaker_interceptor"
        self.virtual_source_name = "virtual_mic_interceptor"
        self.tmp_dir = Path(tmp_dir)
        self.running = True
        self.sink_module_id = None
        self.source_module_id = None
        self.threads = []
        
    def setup(self):
        """仮想オーディオデバイスをセットアップ"""
        print("Setting up virtual audio devices...")
        
        try:
            # 仮想スピーカー（null sink）を作成
            result = subprocess.run([
                "pactl", "load-module", "module-null-sink",
                f"sink_name={self.virtual_sink_name}",
                f"sink_properties=device.description='Virtual_Speaker_Interceptor'"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.sink_module_id = result.stdout.strip()
                print(f"Created virtual speaker: {self.virtual_sink_name} (module {self.sink_module_id})")
            else:
                raise Exception(f"Failed to create virtual sink: {result.stderr}")
            
            # 仮想マイク（null source）を作成
            result = subprocess.run([
                "pactl", "load-module", "module-null-source",
                f"source_name={self.virtual_source_name}",
                f"source_properties=device.description='Virtual_Mic_Interceptor'"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.source_module_id = result.stdout.strip()
                print(f"Created virtual microphone: {self.virtual_source_name} (module {self.source_module_id})")
            else:
                raise Exception(f"Failed to create virtual source: {result.stderr}")
                
        except Exception as e:
            print(f"Setup failed: {e}")
            self.cleanup()
            sys.exit(1)
    
    def cleanup(self):
        """仮想オーディオデバイスをクリーンアップ"""
        print("\nCleaning up virtual audio devices...")
        self.running = False
        
        # スレッドの終了を待つ
        for thread in self.threads:
            thread.join(timeout=2)
        
        # モジュールをアンロード
        if self.sink_module_id:
            subprocess.run(["pactl", "unload-module", self.sink_module_id], 
                         stderr=subprocess.DEVNULL)
        
        if self.source_module_id:
            subprocess.run(["pactl", "unload-module", self.source_module_id],
                         stderr=subprocess.DEVNULL)
        
        print("Cleanup complete")
    
    def start_intercepting(self):
        """音声インターセプションを開始"""
        print("Starting audio interception...")
        
        # 出力ディレクトリを作成
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        
        # スピーカー出力を録音（相手の声）
        speaker_thread = threading.Thread(
            target=self.record_audio_stream,
            args=(f"{self.virtual_sink_name}.monitor", "speaker"),
            daemon=True
        )
        speaker_thread.start()
        self.threads.append(speaker_thread)
        
        # マイク入力を録音（自分の声）
        mic_thread = threading.Thread(
            target=self.record_audio_stream,
            args=(self.virtual_source_name, "mic"),
            daemon=True
        )
        mic_thread.start()
        self.threads.append(mic_thread)
        
        print(f"Audio interception started. Saving 10-second chunks to: {self.tmp_dir}")
    
    def record_audio_stream(self, source, label):
        """音声ストリームを10秒チャンクで録音"""
        chunk_index = 0
        
        while self.running:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = self.tmp_dir / f"{label}_{timestamp}_{chunk_index}.wav"
                
                print(f"Recording {label} chunk {chunk_index} to: {filename}")
                
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
                audio_data = process.stdout.read(chunk_size)
                
                # プロセスを終了
                process.terminate()
                process.wait(timeout=1)
                
                if not self.running:
                    break
                
                # WAVファイルに書き込む
                if audio_data:
                    self.write_wav(filename, audio_data)
                    print(f"Saved {label} chunk {chunk_index}: {filename} ({len(audio_data)} bytes)")
                
                chunk_index += 1
                
            except Exception as e:
                if self.running:
                    print(f"Error recording {label}: {e}")
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
            print(f"Failed to write WAV file {filename}: {e}")

def signal_handler(sig, frame):
    """シグナルハンドラ"""
    print("\nShutdown signal received...")
    sys.exit(0)

def main():
    # 引数から出力ディレクトリを取得
    tmp_dir = sys.argv[1] if len(sys.argv) > 1 else "./tmp"
    
    # インターセプターを初期化
    interceptor = AudioInterceptor(tmp_dir)
    
    # シグナルハンドラを設定
    signal.signal(signal.SIGINT, lambda s, f: interceptor.cleanup() or sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: interceptor.cleanup() or sys.exit(0))
    
    try:
        # セットアップ
        interceptor.setup()
        
        # インターセプション開始
        interceptor.start_intercepting()
        
        # 使い方を表示
        print("\n=== Audio Interceptor Started ===")
        print("1. Set your meeting app's speaker to: Virtual_Speaker_Interceptor")
        print("2. Set your meeting app's microphone to: Virtual_Mic_Interceptor")
        print(f"3. Audio will be saved in 10-second chunks to: {tmp_dir}")
        print("\nPress Ctrl+C to stop...\n")
        
        # メインスレッドを維持
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        pass
    finally:
        interceptor.cleanup()

if __name__ == "__main__":
    main()
