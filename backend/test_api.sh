#!/bin/bash
# API動作確認スクリプト

BASE_URL="http://localhost:8000"

echo "🧪 Testing Meeting Assistant API..."
echo ""

# 1. ルートエンドポイント
echo "1️⃣  Testing root endpoint..."
curl -s "$BASE_URL/" | jq .
echo ""

# 2. ステータス確認
echo "2️⃣  Testing status endpoint..."
curl -s "$BASE_URL/status" | jq .
echo ""

# 3. 利用可能なシンク取得
echo "3️⃣  Getting available audio sinks..."
curl -s "$BASE_URL/sinks" | jq .
echo ""

# 4. 録音開始（文字起こしなし）
echo "4️⃣  Starting recording (without transcription)..."
curl -s -X POST "$BASE_URL/recording/start" \
  -H "Content-Type: application/json" \
  -d '{"transcribe_mode": false, "tmp_dir": "./tmp"}' | jq .
echo ""

# 5. ステータス確認（録音中）
echo "5️⃣  Checking status (should be recording)..."
sleep 2
curl -s "$BASE_URL/status" | jq .
echo ""

# 6. 録音停止
echo "6️⃣  Stopping recording..."
curl -s -X POST "$BASE_URL/recording/stop" | jq .
echo ""

# 7. 最終ステータス確認
echo "7️⃣  Final status check..."
curl -s "$BASE_URL/status" | jq .
echo ""

echo "✅ API test complete!"
