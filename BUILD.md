# ビルドガイド

## 概要
Meeting Assistant を配布可能なバイナリとしてビルドします。

## 前提条件

- Python 3.8+
- Node.js 18+
- npm または bun

## ⚠️ 重要: クロスプラットフォームビルドの制約

**PyInstallerの制約**: Pythonバックエンドは**各プラットフォーム上でビルドする必要があります**。

| ビルド環境 | 生成されるバイナリ |
|-----------|------------------|
| Linux | Linux バイナリのみ |
| macOS | macOS バイナリのみ |
| Windows | Windows .exe のみ |

つまり、全プラットフォーム向けにビルドするには、各OS上でビルド作業が必要です。

## プラットフォーム別ビルド手順

### Linux用ビルド（Linux上で実行）

```bash
# 1. Pythonバックエンド
cd backend
./build.sh

# 2. Electronアプリ
cd ../frontend
npm run build:linux
```

**成果物**:
- `frontend/dist/Meeting Assistant-0.1.0.AppImage`
- `frontend/dist/meeting-assistant_0.1.0_amd64.deb`

### macOS用ビルド（macOS上で実行）

```bash
# 1. Pythonバックエンド
cd backend
./build-macos.sh

# 2. Electronアプリ
cd ../frontend
npm run build:mac
```

**成果物**:
- `frontend/dist/Meeting Assistant-0.1.0.dmg`
- `frontend/dist/Meeting Assistant-0.1.0-mac.zip`

### Windows用ビルド（Windows上で実行）

```bash
# 1. Pythonバックエンド（PowerShellまたはコマンドプロンプト）
cd backend
python -m venv venv
venv\Scripts\activate
pip install pyinstaller
pyinstaller --onefile --name server.exe server.py

# 2. Electronアプリ
cd ..\frontend
npm run build:win
```

**成果物**:
- `frontend/dist/Meeting Assistant Setup 0.1.0.exe`
- `frontend/dist/Meeting Assistant 0.1.0.exe` (portable)

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

## CI/CDでの自動ビルド（推奨）

全プラットフォーム向けのビルドを自動化するには、GitHub Actionsなどを使用します。

**例: GitHub Actions（`.github/workflows/build.yml`）**

```yaml
name: Build

on: [push, pull_request]

jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Linux
        run: |
          cd backend && ./build.sh
          cd ../frontend && npm install && npm run build:linux

  build-mac:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build macOS
        run: |
          cd backend && ./build-macos.sh
          cd ../frontend && npm install && npm run build:mac

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Windows
        run: |
          cd backend && ./build-windows.sh
          cd ../frontend && npm install && npm run build:win
```

## セキュリティ注意事項

**重要**: `.env` ファイルや認証情報はバイナリに含めないでください。
初回起動時にユーザーが設定する仕組みになっています。

もしビルド時に含める必要がある場合は、以下を実行：

```bash
# 自己責任で
cp backend/.env frontend/build/.env
```

ただし、**API キーや認証情報が平文で配布される**ため、推奨しません。
