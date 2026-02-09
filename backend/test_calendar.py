#!/usr/bin/env python3
"""
Google Calendar APIのテストスクリプト
"""
import os
from dotenv import load_dotenv
from calendar_service import CalendarService
from database import get_settings

load_dotenv()

print("=" * 60)
print("Google Calendar API Test")
print("=" * 60)

# 1. 設定の確認
print("\n[1] 設定ファイルの確認")
service_account_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
print(f"  - GOOGLE_SERVICE_ACCOUNT_FILE: {service_account_file}")
print(f"  - ファイル存在: {os.path.exists(service_account_file) if service_account_file else 'N/A'}")

# 2. DBからカレンダーID取得
print("\n[2] データベース設定の確認")
settings = get_settings()
calendar_id = settings.get('calendar_id', 'primary')
print(f"  - calendar_id (DB): {calendar_id}")

# 3. CalendarServiceの初期化
print("\n[3] CalendarService初期化")
cal_service = CalendarService(service_account_file)

if not cal_service.service:
    print("  ❌ CalendarServiceの初期化に失敗")
    print("  考えられる原因:")
    print("    - サービスアカウントJSONファイルが正しくない")
    print("    - ファイルのパスが間違っている")
    exit(1)
else:
    print("  ✅ CalendarService初期化成功")

# 4. 現在のイベントを取得
print("\n[4] 現在のイベントを取得")
print(f"  カレンダーID: {calendar_id}")
try:
    event = cal_service.get_current_event(calendar_id=calendar_id, time_window_minutes=120)
    if event:
        print("  ✅ イベントが見つかりました:")
        print(f"    - タイトル: {event['summary']}")
        print(f"    - 開始: {event['start']}")
        print(f"    - 終了: {event['end']}")
    else:
        print("  ℹ️  前後2時間以内にイベントが見つかりませんでした")
except Exception as e:
    print(f"  ❌ エラーが発生しました: {e}")
    print("\n  考えられる原因:")
    print("    1. カレンダーIDが間違っている")
    print("       → 'primary'ではなく、共有されたカレンダーのメールアドレスを指定してください")
    print("       → 例: your-email@gmail.com")
    print("    2. サービスアカウントにカレンダーへのアクセス権限がない")
    print("       → Google Calendarで該当カレンダーを開き、")
    print("         サービスアカウントのメールアドレス（xxxxx@xxxxxx.iam.gserviceaccount.com）")
    print("         を「閲覧権限（予定の表示）」で共有してください")
    print("    3. Google Calendar APIが有効になっていない")
    print("       → https://console.cloud.google.com/apis/library/calendar-json.googleapis.com")

# 5. 今日のイベント一覧を取得
print("\n[5] 今日のイベント一覧を取得")
try:
    events = cal_service.get_events_today(calendar_id=calendar_id)
    if events:
        print(f"  ✅ {len(events)}件のイベントが見つかりました:")
        for i, event in enumerate(events[:5], 1):  # 最初の5件のみ表示
            print(f"    {i}. {event['summary']} ({event['start']})")
    else:
        print("  ℹ️  今日のイベントが見つかりませんでした")
except Exception as e:
    print(f"  ❌ エラー: {e}")

print("\n" + "=" * 60)
print("テスト完了")
print("=" * 60)
