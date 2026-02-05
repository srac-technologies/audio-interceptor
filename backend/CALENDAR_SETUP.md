# Google Calendar 連携セットアップ

## 概要
Google Calendar APIを使用して、会議開始時に自動的にカレンダーからタイトルを取得できます。

## 方法1: Service Account（推奨）

サーバー間認証で、ユーザーの承認なしに動作します。

### 手順

1. **Google Cloud Consoleでプロジェクトを作成**
   - https://console.cloud.google.com/
   - 新しいプロジェクトを作成

2. **Google Calendar APIを有効化**
   - 「APIとサービス」 > 「ライブラリ」
   - 「Google Calendar API」を検索して有効化

3. **Service Accountを作成**
   - 「APIとサービス」 > 「認証情報」
   - 「認証情報を作成」 > 「サービスアカウント」
   - 名前を入力（例: meeting-assistant）
   - 「作成して続行」をクリック
   - ロールは不要（スキップ）
   - 「完了」をクリック

4. **JSONキーファイルをダウンロード**
   - 作成されたサービスアカウントをクリック
   - 「キー」タブ > 「鍵を追加」 > 「新しい鍵を作成」
   - 「JSON」を選択してダウンロード
   - ファイルを安全な場所に保存（例: `~/credentials/meeting-assistant-sa.json`）

5. **カレンダーへのアクセス権を付与**
   - サービスアカウントのメールアドレスをコピー（例: `meeting-assistant@project-id.iam.gserviceaccount.com`）
   - Google Calendarを開く
   - 「設定」 > 「カレンダーの設定」 > 対象のカレンダー
   - 「特定のユーザーとの共有」
   - サービスアカウントのメールアドレスを追加
   - 権限: **「予定の表示（すべての予定の詳細）」**

6. **環境変数を設定**
   ```bash
   cd backend
   cp .env.example .env
   ```
   
   `.env` ファイルを編集：
   ```
   GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/your-service-account-key.json
   ```

7. **動作確認**
   バックエンドを再起動すると、以下のログが表示されます：
   ```
   ✅ Google Calendar service initialized (Service Account)
   ```

## テスト

会議を開始する際、タイトルが空欄の場合、自動的にカレンダーからイベントタイトルが取得されます。

- 現在時刻の前後30分以内のイベントを検索
- 進行中のイベントがあればそれを使用
- なければ次のイベントを使用

## トラブルシューティング

### 「No event found」エラー
- カレンダーに該当時刻のイベントがない
- サービスアカウントにカレンダーへのアクセス権がない

### 「Calendar API error: 403」
- カレンダーへの共有設定が正しくない
- サービスアカウントのメールアドレスを再確認

### サービスが初期化されない
- JSONキーファイルのパスが正しいか確認
- ファイルの読み取り権限があるか確認
