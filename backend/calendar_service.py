import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

class CalendarService:
    def __init__(self, service_account_file: Optional[str] = None):
        self.service = None
        self.service_account_file = service_account_file or os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
        
        if self.service_account_file and os.path.exists(self.service_account_file):
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    self.service_account_file,
                    scopes=SCOPES
                )
                self.service = build('calendar', 'v3', credentials=credentials)
                logger.info("Google Calendar service initialized (Service Account)")
            except Exception as e:
                logger.warning("Failed to initialize Calendar service: %s", e)
    
    def get_current_event(self, calendar_id: str = 'primary', time_window_minutes: int = 30) -> Optional[Dict]:
        """現在時刻の前後N分以内のイベントを取得"""
        if not self.service:
            return None
        
        try:
            now = datetime.utcnow()
            time_min = (now - timedelta(minutes=time_window_minutes)).isoformat() + 'Z'
            time_max = (now + timedelta(minutes=time_window_minutes)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=10,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # 現在進行中または最も近いイベントを返す
            for event in events:
                start = event.get('start', {}).get('dateTime')
                end = event.get('end', {}).get('dateTime')
                
                if start and end:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    now_aware = datetime.now(start_dt.tzinfo)
                    
                    # 現在進行中
                    if start_dt <= now_aware <= end_dt:
                        return {
                            'id': event.get('id'),
                            'summary': event.get('summary', '無題のイベント'),
                            'start': start,
                            'end': end,
                            'description': event.get('description'),
                            'location': event.get('location'),
                            'attendees': [a.get('email') for a in event.get('attendees', [])]
                        }
            
            # 進行中がなければ最も近い未来のイベント
            if events:
                event = events[0]
                return {
                    'id': event.get('id'),
                    'summary': event.get('summary', '無題のイベント'),
                    'start': event.get('start', {}).get('dateTime'),
                    'end': event.get('end', {}).get('dateTime'),
                    'description': event.get('description'),
                    'location': event.get('location'),
                    'attendees': [a.get('email') for a in event.get('attendees', [])]
                }
            
            return None
            
        except HttpError as error:
            logger.error("Calendar API error: %s", error)
            return None
    
    def get_concurrent_events(self, calendar_id: str = 'primary', buffer_minutes: int = 15) -> List[Dict]:
        """現在時刻と重なるイベントをすべて取得（±buffer分のバッファ付き）"""
        if not self.service:
            return []

        try:
            now = datetime.utcnow()
            time_min = (now - timedelta(minutes=buffer_minutes)).isoformat() + 'Z'
            time_max = (now + timedelta(minutes=buffer_minutes)).isoformat() + 'Z'

            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=20,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            result = []

            for event in events:
                start = event.get('start', {}).get('dateTime')
                end = event.get('end', {}).get('dateTime')
                if start and end:
                    result.append({
                        'id': event.get('id'),
                        'summary': event.get('summary', '無題のイベント'),
                        'start': start,
                        'end': end,
                        'description': event.get('description'),
                        'location': event.get('location'),
                        'attendees': [a.get('email') for a in event.get('attendees', [])]
                    })

            return result

        except HttpError as error:
            logger.error("Calendar API error: %s", error)
            return []

    def get_events_today(self, calendar_id: str = 'primary') -> List[Dict]:
        """今日のイベント一覧を取得"""
        if not self.service:
            return []
        
        try:
            now = datetime.utcnow()
            time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=50,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return [{
                'id': event.get('id'),
                'summary': event.get('summary', '無題のイベント'),
                'start': event.get('start', {}).get('dateTime'),
                'end': event.get('end', {}).get('dateTime')
            } for event in events]
            
        except HttpError as error:
            logger.error("Calendar API error: %s", error)
            return []

# グローバルインスタンス
calendar_service = CalendarService()
