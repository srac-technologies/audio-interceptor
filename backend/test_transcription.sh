#!/bin/bash
# Transcription Service テストスクリプト

set -e

echo "🧪 Transcription Service Test"
echo "=============================="
echo ""

# 1. テスト用音声生成（5秒の日本語音声）
echo "📝 1. Generating test audio..."
TEST_AUDIO="test_audio.wav"

# ffmpegでテスト用のトーン音を生成（マイクがない環境でもテスト可能）
ffmpeg -f lavfi -i "sine=frequency=440:duration=3" -ar 16000 -ac 1 "$TEST_AUDIO" -y 2>/dev/null

echo "✅ Test audio generated: $TEST_AUDIO (3 sec, 440Hz tone)"
echo ""

# 2. Transcription Service初期化テスト
echo "📝 2. Testing service initialization..."
python3 -c "
from transcription import get_transcription_service
svc = get_transcription_service()
print(f'✅ Mode: {svc.mode}')
print(f'✅ Model: {svc.model_name}')
print(f'✅ Language: {svc.language}')
" 2>&1 | grep -v "Warning: You are sending unauthenticated"

echo ""

# 3. 文字起こしテスト
echo "📝 3. Testing transcription (this will take ~10-30 seconds)..."
echo "   Note: トーン音なので文字起こし結果は空または意味不明な文字列になります"
echo ""

python3 transcription.py "$TEST_AUDIO" 2>&1 | grep -v "Warning: You are sending unauthenticated"

echo ""
echo "=============================="
echo "✅ All tests completed!"
echo ""
echo "📋 Next Steps:"
echo "   1. 実際の音声ファイルでテスト:"
echo "      python3 transcription.py your_audio.wav"
echo ""
echo "   2. モード切り替えテスト (.envを編集):"
echo "      WHISPER_MODE=api  # OpenAI API使用"
echo "      WHISPER_MODE=local  # ローカルWhisper使用"
echo ""
echo "   3. モデル変更:"
echo "      WHISPER_MODEL=base  # 軽量"
echo "      WHISPER_MODEL=small  # バランス（推奨）"
echo "      WHISPER_MODEL=medium  # 高精度"
echo ""

# クリーンアップ
rm -f "$TEST_AUDIO"
