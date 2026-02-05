#!/bin/bash
# マイクから5秒録音して文字起こしテスト

echo "🎤 Recording 5 seconds from microphone..."
echo "   Please speak in Japanese!"
echo ""
echo "Starting in 3..."
sleep 1
echo "Starting in 2..."
sleep 1
echo "Starting in 1..."
sleep 1
echo "🔴 RECORDING... (5 seconds)"

OUTPUT_FILE="test_voice_$(date +%Y%m%d_%H%M%S).wav"

# パルスオーディオから5秒録音
parec --format=s16le --rate=16000 --channels=1 | \
  dd bs=32000 count=5 of="$OUTPUT_FILE" 2>/dev/null

echo "✅ Recording saved: $OUTPUT_FILE"
echo ""
echo "📝 Transcribing..."
python3 transcription.py "$OUTPUT_FILE" 2>&1 | grep -v "Warning: You are sending unauthenticated"

echo ""
echo "🎉 Test completed!"
echo "   Audio file: $OUTPUT_FILE"
