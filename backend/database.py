import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

# パッケージ版: MEETING_ASSISTANT_CONFIG_DIR にDB保存、開発時: スクリプト横
_config_dir = os.getenv('MEETING_ASSISTANT_CONFIG_DIR', os.path.dirname(__file__))
DB_PATH = os.path.join(_config_dir, 'meeting_assistant.db')

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
    }
    
    for key, value in default_settings.items():
        cursor.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', (key, value))

    # 初期マスタデータの投入（データがない場合のみ）
    cursor.execute('SELECT count(*) FROM meeting_types')
    if cursor.fetchone()[0] == 0:
        seed_data(cursor)

    conn.commit()
    conn.close()
    print("✅ Database initialized")

def seed_data(cursor):
    """初期データの投入"""
    print("🌱 Seeding initial data...")
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

if __name__ == "__main__":
    init_db()
