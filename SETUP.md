# セットアップ & 動作確認ガイド

## 前提条件
- Linux (PulseAudio/PipeWire)
- Python 3.8以上
- Node.js 18以上（nix profileから利用）

## 完全な起動手順

### ステップ1: バックエンドをセットアップ（初回のみ）

```bash
cd ~/workspace/audio-interceptor/backend
./setup_venv.sh
```

### ステップ2: バックエンドを起動

**ターミナル1:**
```bash
cd ~/workspace/audio-interceptor/backend
./start_server.sh
```

起動ログに以下が表示されればOK:
```
🚀 Starting Meeting Assistant Backend Server...
   API: http://localhost:8000
   WebSocket: ws://localhost:8000/ws
   Docs: http://localhost:8000/docs

🎤 Audio Interceptor: Integrated
   Virtual Speaker: Virtual_Speaker_Interceptor
```

### ステップ3: フロントエンドを起動

**ターミナル2:**
```bash
cd ~/workspace/audio-interceptor/frontend
export PATH="/home/tan_t/.nix-profile/bin:$PATH"
npm start
```

Electronウィンドウが開きます。

### ステップ4: UIで録音開始

1. Electronウィンドウの「会議を開始」ボタンをクリック
2. バックエンドログに `🎙️  Recording started` と表示される
3. 仮想スピーカー `Virtual_Speaker_Interceptor` が作成される

### ステップ5: Web会議で確認

Google MeetやZoomのスピーカー設定を開き、`Virtual_Speaker_Interceptor` を選択。

### ステップ6: 録音停止

Electronウィンドウの「会議を終了」ボタンをクリック。

## トラブルシューティング

### エラー: "録音開始エラー: fetch failed"

**原因:** バックエンドが起動していない

**解決策:**
```bash
cd ~/workspace/audio-interceptor/backend
./start_server.sh
```

### エラー: "Failed to create virtual sink"

**原因:** PulseAudioが動作していない、または既に同名デバイスが存在

**解決策:**
```bash
# 既存デバイスをクリーンアップ
pactl list short modules | grep null
pactl unload-module <module-id>

# PulseAudio確認
pactl info
```

### Electronウィンドウが開かない

**原因:** npmまたはnodeがPATHにない

**解決策:**
```bash
export PATH="/home/tan_t/.nix-profile/bin:$PATH"
cd ~/workspace/audio-interceptor/frontend
npm start
```

## 動作確認チェックリスト

- [ ] バックエンドが起動している（`http://localhost:8000/status`にアクセス可能）
- [ ] Electronウィンドウが開いている
- [ ] 「会議を開始」ボタンをクリックできる
- [ ] ボタンクリック後、ステータスが「録音中」に変わる
- [ ] バックエンドログに「Recording started」と表示される
- [ ] Web会議アプリで `Virtual_Speaker_Interceptor` が選択できる
- [ ] 会議音声が `tmp/` ディレクトリに保存される

## 次のステップ

動作確認ができたら:
1. Whisper文字起こしを有効にする（環境変数 `OPENAI_API_KEY` をセット）
2. WebSocket接続でリアルタイム文字起こしをUIに表示
3. Google Calendar連携
4. 会議検知機能の実装
