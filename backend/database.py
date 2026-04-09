import sqlite3
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'meeting_assistant.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # セッションテーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_type_id INTEGER,
        title TEXT,
        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        end_time TIMESTAMP,
        summary TEXT,
        FOREIGN KEY (meeting_type_id) REFERENCES meeting_types (id)
    )
    ''')
    
    # 既存のsessionsテーブルにsummaryカラムがない場合のマイグレーション
    try:
        cursor.execute('ALTER TABLE sessions ADD COLUMN summary TEXT')
    except sqlite3.OperationalError:
        pass # すでに存在する

    # トランスクリプトテーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transcripts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source TEXT,
        text TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    ''')

    # アドバイステーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS advices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        trigger_condition TEXT,
        advice_text TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    ''')

    # 会議種別マスタ
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS meeting_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        description TEXT
    )
    ''')

    # プロンプトマスタ
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_type_id INTEGER,
        trigger_condition TEXT,
        action_prompt TEXT,
        FOREIGN KEY (meeting_type_id) REFERENCES meeting_types (id)
    )
    ''')
    
    # アプリケーション設定テーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    # リサーチソース管理テーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS research_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 5,
        timeout REAL DEFAULT 5.0,
        config TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    # source_type: "builtin" | "custom_api" | "shell_command"
    # config: JSON文字列 (APIキー、エンドポイント、ヘッダー、コマンド等)

    # 組み込みソースの初期データ投入
    cursor.execute('SELECT count(*) FROM research_sources')
    if cursor.fetchone()[0] == 0:
        builtin_sources = [
            ('LLM', 'builtin', 1, 1, 5.0, '{"description": "OpenAI GPT-4o-miniによる即答"}'),
            ('BraveSearch', 'builtin', 0, 2, 3.0, '{"description": "Brave Search APIによるWeb検索", "env_key": "BRAVE_API_KEY"}'),
            ('Tavily', 'builtin', 0, 2, 5.0, '{"description": "Tavily AI検索API", "env_key": "TAVILY_API_KEY"}'),
            ('Perplexity', 'builtin', 0, 2, 8.0, '{"description": "Perplexity APIによるAI検索", "env_key": "PERPLEXITY_API_KEY"}'),
            ('GoogleSearch', 'builtin', 0, 3, 5.0, '{"description": "Google Custom Search API", "env_key": "GOOGLE_CSE_API_KEY", "cx_env_key": "GOOGLE_CSE_CX"}'),
            ('LightPanda', 'builtin', 0, 3, 10.0, '{"description": "LightPanda agentic browser", "env_key": "LIGHTPANDA_API_KEY"}'),
            ('LimitlessAPI', 'builtin', 0, 4, 5.0, '{"description": "Limitless APIによる文脈検索", "env_key": "LIMITLESS_API_KEY"}'),
            ('gogCLI', 'builtin', 0, 5, 10.0, '{"description": "gog CLIによる検索"}'),
        ]
        for name, stype, enabled, priority, timeout, config in builtin_sources:
            cursor.execute(
                'INSERT INTO research_sources (name, source_type, enabled, priority, timeout, config) VALUES (?, ?, ?, ?, ?, ?)',
                (name, stype, enabled, priority, timeout, config)
            )
    
    # 初期設定の投入
    default_settings = {
        'auto_summary_enabled': 'true',
        'summary_prompt': '以下の会議の議事録を作成してください。\n\n# 要件\n- 重要な決定事項\n- 次のアクションアイテム\n- 議論の要約\nをMarkdown形式でまとめてください。',
        'save_dir': str(Path.home() / "Documents" / "MeetingLogs"),
        'calendar_id': 'primary',
        'ner_prompt': '会話から固有名詞（人名、企業名、製品名、技術名など）を抽出してください。\n\nJSON形式で以下のように出力してください：\n{"entities": ["entity1", "entity2", ...]}',
        'slack_bot_token': '',
        'slack_channel': '',
        'research_enabled': 'false',
        'research_method': 'llm',  # llm, hybrid
        'research_buffer_size': '2',  # バッファサイズ（発言数）
        'research_target_sources': 'speaker',  # speaker, mic, both
        'research_transcription_refinement': 'false',  # 文字起こし精度向上
        # 文字起こしエンジン設定
        'transcription_engine': 'faster-whisper',  # faster-whisper, openai-whisper, google-speech, kotoba-whisper, azure-speech
        'transcription_model': 'small',  # エンジン固有のモデル名
        'transcription_language': 'ja',  # ja, en, auto
        # 精度向上LLMプロバイダ設定
        'refinement_provider': 'openai',  # openai, claude, gemini, ollama
        'refinement_model': '',  # プロバイダ固有のモデル名（空=デフォルト）
        # 専門用語辞書
        'custom_dictionary': '',  # 改行区切りの用語リスト
        # APIキー（UIから設定。.envファイル不要）
        'openai_api_key': '',
        'anthropic_api_key': '',
        'google_ai_api_key': '',
        'google_application_credentials': '',  # Google Cloud 認証ファイルパス
        'google_service_account_file': '',  # Google Calendar サービスアカウントファイル
        'azure_speech_key': '',
        'azure_speech_region': '',
        'brave_api_key': '',
        'tavily_api_key': '',
        'perplexity_api_key': '',
        'google_cse_api_key': '',
        'google_cse_cx': '',
        'lightpanda_api_key': '',
        'limitless_api_key': '',
    }
    
    for key, value in default_settings.items():
        cursor.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', (key, value))

    # 初期マスタデータの投入（データがない場合のみ）
    cursor.execute('SELECT count(*) FROM meeting_types')
    if cursor.fetchone()[0] == 0:
        seed_data(cursor)

    conn.commit()
    conn.close()
    logger.info("Database initialized: %s", DB_PATH)

def seed_data(cursor):
    """初期データの投入"""
    logger.info("Seeding initial data...")
    # 1. 商談・セールス
    cursor.execute('INSERT INTO meeting_types (name, description) VALUES (?, ?)', ('商談・セールス', '製品やサービスの提案、価格交渉'))
    sales_id = cursor.lastrowid
    cursor.execute('INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)', (sales_id, '価格への懸念', 'ROIを強調する提案をしてください'))

    # 2. 定例進捗
    cursor.execute('INSERT INTO meeting_types (name, description) VALUES (?, ?)', ('定例進捗', '進捗報告、課題共有'))

# --- Session Management ---

def create_session(meeting_type_id: Optional[int], title: str = "Untitled") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO sessions (meeting_type_id, title) VALUES (?, ?)',
        (meeting_type_id, title)
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def end_session(session_id: int):
    conn = get_db_connection()
    conn.execute(
        'UPDATE sessions SET end_time = CURRENT_TIMESTAMP WHERE id = ?',
        (session_id,)
    )
    conn.commit()
    conn.close()

def add_transcript(session_id: int, source: str, text: str):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO transcripts (session_id, source, text) VALUES (?, ?, ?)',
        (session_id, source, text)
    )
    conn.commit()
    conn.close()

def add_advice(session_id: int, trigger: str, advice: str):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO advices (session_id, trigger_condition, advice_text) VALUES (?, ?, ?)',
        (session_id, trigger, advice)
    )
    conn.commit()
    conn.close()

# --- Master Data Management ---

def get_meeting_types() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM meeting_types')
    types = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return types

def create_meeting_type(name: str, description: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO meeting_types (name, description) VALUES (?, ?)', (name, description))
        new_id = cursor.lastrowid
        conn.commit()
        return new_id
    except sqlite3.IntegrityError:
        return -1
    finally:
        conn.close()

def delete_meeting_type(type_id: int):
    conn = get_db_connection()
    conn.execute('DELETE FROM prompts WHERE meeting_type_id = ?', (type_id,))
    conn.execute('DELETE FROM meeting_types WHERE id = ?', (type_id,))
    conn.commit()
    conn.close()

def get_prompts_for_type(meeting_type_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM prompts WHERE meeting_type_id = ?', (meeting_type_id,))
    prompts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return prompts

def create_prompt(meeting_type_id: int, trigger: str, action: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)',
        (meeting_type_id, trigger, action)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def delete_prompt(prompt_id: int):
    conn = get_db_connection()
    conn.execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
    conn.commit()
    conn.close()

# --- History & Analytics ---

def get_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, m.name as meeting_type_name 
        FROM sessions s 
        LEFT JOIN meeting_types m ON s.meeting_type_id = m.id
        ORDER BY s.start_time DESC LIMIT ?
    ''', (limit,))
    sessions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return sessions

def get_session_details(session_id: int) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # セッション情報
    cursor.execute('''
        SELECT s.*, m.name as meeting_type_name 
        FROM sessions s 
        LEFT JOIN meeting_types m ON s.meeting_type_id = m.id
        WHERE s.id = ?
    ''', (session_id,))
    session = cursor.fetchone()
    
    if not session:
        conn.close()
        return None
        
    # 文字起こし
    cursor.execute('SELECT * FROM transcripts WHERE session_id = ? ORDER BY timestamp', (session_id,))
    transcripts = [dict(row) for row in cursor.fetchall()]
    
    # アドバイス
    cursor.execute('SELECT * FROM advices WHERE session_id = ? ORDER BY timestamp', (session_id,))
    advices = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "session": dict(session),
        "transcripts": transcripts,
        "advices": advices
    }

def update_session_title(session_id: int, new_title: str):
    """セッションのタイトルを更新"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE sessions SET title = ? WHERE id = ?', (new_title, session_id))
    conn.commit()
    conn.close()

# --- Settings & Summary ---

def get_settings() -> Dict[str, str]:
    """全設定を取得"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM app_settings')
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    conn.close()
    return settings

def update_setting(key: str, value: str):
    """設定を更新"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def save_summary(session_id: int, summary_text: str):
    """セッションにサマリーを保存"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE sessions SET summary = ? WHERE id = ?', (summary_text, session_id))
    conn.commit()
    conn.close()

# --- Research Source Management ---

def get_research_sources(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """リサーチソース一覧を取得"""
    conn = get_db_connection()
    cursor = conn.cursor()
    if enabled_only:
        cursor.execute('SELECT * FROM research_sources WHERE enabled = 1 ORDER BY priority')
    else:
        cursor.execute('SELECT * FROM research_sources ORDER BY priority')
    sources = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return sources

def get_research_source(source_id: int) -> Optional[Dict[str, Any]]:
    """リサーチソースを1件取得"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM research_sources WHERE id = ?', (source_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_research_source(name: str, source_type: str, priority: int = 5,
                           timeout: float = 5.0, config: str = '{}') -> int:
    """リサーチソースを追加"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO research_sources (name, source_type, enabled, priority, timeout, config) VALUES (?, ?, 1, ?, ?, ?)',
        (name, source_type, priority, timeout, config)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def update_research_source(source_id: int, **kwargs):
    """リサーチソースを更新（キーワード引数で指定されたフィールドのみ更新）"""
    allowed_fields = {'name', 'source_type', 'enabled', 'priority', 'timeout', 'config'}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [source_id]
    cursor.execute(f'UPDATE research_sources SET {set_clause} WHERE id = ?', values)
    conn.commit()
    conn.close()

def delete_research_source(source_id: int):
    """リサーチソースを削除"""
    conn = get_db_connection()
    conn.execute('DELETE FROM research_sources WHERE id = ?', (source_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
