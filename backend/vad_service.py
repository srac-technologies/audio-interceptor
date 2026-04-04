#!/usr/bin/env python3
"""
VAD Service - Voice Activity Detection using webrtcvad
発言区間の検出を行い、チャンクベース文字起こしとVADベース文字起こしを統合する
"""

import struct
import webrtcvad


class VADService:
    """webrtcvadベースの音声区間検出"""

    def __init__(self, sample_rate=48000, frame_duration_ms=30, aggressiveness=2,
                 speech_pad_ms=600, min_speech_ms=500):
        """
        Args:
            sample_rate: サンプルレート (8000, 16000, 32000, 48000)
            frame_duration_ms: フレーム長 (10, 20, 30ms)
            aggressiveness: VAD感度 (0-3, 3=最も積極的にフィルタ)
            speech_pad_ms: 発言終了判定の無音パディング
            min_speech_ms: 最小発言長（これより短い発言は無視）
        """
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)  # samples per frame
        self.frame_bytes = self.frame_size * 2  # 16-bit mono = 2 bytes per sample

        self.vad = webrtcvad.Vad(aggressiveness)

        # 発言終了判定: speech_pad_ms 分の無音フレームが続いたら終了
        self.silence_threshold = int(speech_pad_ms / frame_duration_ms)
        self.min_speech_frames = int(min_speech_ms / frame_duration_ms)

        # 状態
        self.is_speaking = False
        self.silence_frames = 0
        self.speech_frames = 0

    def process_frame(self, mono_pcm: bytes) -> dict:
        """
        1フレーム分のモノラルPCMデータを処理

        Args:
            mono_pcm: 16-bit mono PCMデータ (frame_bytes bytes)

        Returns:
            {
                "is_speech": bool,
                "event": "speech_start" | "speech_end" | None,
                "speech_duration_ms": int
            }
        """
        is_speech = self.vad.is_speech(mono_pcm, self.sample_rate)
        event = None

        if is_speech:
            self.speech_frames += 1
            self.silence_frames = 0

            if not self.is_speaking:
                self.is_speaking = True
                event = "speech_start"
        else:
            if self.is_speaking:
                self.silence_frames += 1

                if self.silence_frames >= self.silence_threshold:
                    # 十分な無音 → 発言終了
                    if self.speech_frames >= self.min_speech_frames:
                        event = "speech_end"
                    # 短すぎる発言は無視してリセット
                    self.is_speaking = False
                    self.speech_frames = 0
                    self.silence_frames = 0

        return {
            "is_speech": is_speech,
            "event": event,
            "speech_duration_ms": self.speech_frames * self.frame_duration_ms
        }

    def force_end(self):
        """強制的に発言終了を判定（最大発言長超過時に使用）"""
        if self.is_speaking and self.speech_frames >= self.min_speech_frames:
            self.is_speaking = False
            self.speech_frames = 0
            self.silence_frames = 0
            return True
        self.is_speaking = False
        self.speech_frames = 0
        self.silence_frames = 0
        return False

    def reset(self):
        """状態をリセット"""
        self.is_speaking = False
        self.silence_frames = 0
        self.speech_frames = 0


def stereo_to_mono(stereo_pcm: bytes) -> bytes:
    """ステレオPCM(16bit)をモノラルに変換（左右チャンネルの平均）"""
    n_samples = len(stereo_pcm) // 2
    samples = struct.unpack(f'<{n_samples}h', stereo_pcm)
    mono = []
    for i in range(0, len(samples), 2):
        if i + 1 < len(samples):
            avg = (samples[i] + samples[i + 1]) // 2
        else:
            avg = samples[i]
        mono.append(avg)
    return struct.pack(f'<{len(mono)}h', *mono)
