# ビルドガイド

## 概要
Meeting Assistant を配布可能なバイナリとしてビルドします。

## 前提条件

- Python 3.8+
- Node.js 18+
- npm または bun

## ビルド手順

### 1. Pythonバックエンドのビルド

```bash
cd backend
chmod +x build.sh
./build.sh
```

これにより `backend/dist/server` が作成されます。

### 2. Electronアプリのビルド

```bash
cd frontend
npm run build:linux  # Linux用
# または
npm run build       # 現在のプラットフォーム用
```

ビルド成果物は `frontend/dist/` に生成されます。

### 3. 生成されるファイル

- **AppImage**: `frontend/dist/Meeting Assistant-0.1.0.AppImage`
- **deb**: `frontend/dist/meeting-assistant_0.1.0_amd64.deb`

## 配布

生成された AppImage または deb ファイルを配布してください。

## 初回起動時の設定

アプリを初めて起動すると、設定ファイルが自動的に作成されます：

**設定ディレクトリ**: `~/.config/Meeting Assistant/config/`

### 必須設定

1. **OpenAI API キー**
   
   `.env` ファイルを編集：
   ```
   OPENAI_API_KEY=your-api-key-here
   ```

2. **Google Calendar（オプション）**
   
   ```
   GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account-key.json
   ```
   
   JSONキーファイルも同じディレクトリに配置してください。

## トラブルシューティング

### Pythonバックエンドのビルドエラー

PyInstallerが依存関係を検出できない場合：

```bash
pip install pyinstaller
pyinstaller --onefile --add-data "meeting_assistant.db:." server.py
```

### Electronビルドエラー

node_modulesを再インストール：

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

## 開発モードとの違い

| 項目 | 開発モード | ビルド版 |
|------|-----------|---------|
| Pythonバックエンド | `python3 server.py` | バイナリ実行 |
| 設定ファイル | `backend/.env` | `~/.config/Meeting Assistant/config/.env` |
| データベース | `backend/meeting_assistant.db` | 組み込み（初回コピー） |

## セキュリティ注意事項

**重要**: `.env` ファイルや認証情報はバイナリに含めないでください。
初回起動時にユーザーが設定する仕組みになっています。

もしビルド時に含める必要がある場合は、以下を実行：

```bash
# 自己責任で
cp backend/.env frontend/build/.env
```

ただし、**API キーや認証情報が平文で配布される**ため、推奨しません。
