import sqlite3
import os
from typing import List, Dict, Optional, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "meeting_assistant.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """データベースの初期化"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Meeting Types テーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS meeting_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Prompts テーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_type_id INTEGER NOT NULL,
        trigger_condition TEXT NOT NULL,
        action_prompt TEXT NOT NULL,
        FOREIGN KEY (meeting_type_id) REFERENCES meeting_types (id)
    )
    ''')

    # Sessions テーブル (履歴用)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_type_id INTEGER,
        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        end_time TIMESTAMP,
        title TEXT,
        FOREIGN KEY (meeting_type_id) REFERENCES meeting_types (id)
    )
    ''')

    # Transcripts テーブル (文字起こしログ)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transcripts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    ''')

    # Advices テーブル (アドバイスログ)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS advices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        trigger_condition TEXT,
        advice_text TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    ''')
    
    # 初期データ投入（データがない場合のみ）
    cursor.execute('SELECT count(*) FROM meeting_types')
    if cursor.fetchone()[0] == 0:
        seed_data(cursor)
        
    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {DB_PATH}")

def seed_data(cursor):
    """初期データの投入"""
    print("🌱 Seeding initial data...")
    
    # 1. 商談・セールス
    cursor.execute(
        'INSERT INTO meeting_types (name, description) VALUES (?, ?)',
        ('商談・セールス', '製品やサービスの提案、価格交渉、クロージング')
    )
    sales_id = cursor.lastrowid
    
    cursor.execute(
        'INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)',
        (sales_id, 
         '相手が価格や費用について懸念を示した場合（高い、予算がない等）', 
         '相手の予算懸念に対して、投資対効果（ROI）や長期的価値を強調する切り返しトークを3つ提案してください。簡潔に。')
    )
    cursor.execute(
        'INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)',
        (sales_id, 
         '相手が競合他社と比較している場合', 
         '競合と比較された際の差別化ポイント（サポートの手厚さ、導入のしやすさ等）を強調するアドバイスを提示してください。')
    )

    # 2. 定例進捗・報告
    cursor.execute(
        'INSERT INTO meeting_types (name, description) VALUES (?, ?)',
        ('定例進捗・報告', 'プロジェクトの進捗報告、課題共有、ネクストアクション確認')
    )
    teiji_id = cursor.lastrowid
    
    cursor.execute(
        'INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)',
        (teiji_id, 
         '議論が発散して結論が出ないまま時間が経過している場合', 
         '議論を収束させるためのファシリテーションの言葉を提案してください。「一度整理しましょう」「残りの時間で決めるべきことは...」など。')
    )
    
    # 3. 採用面接
    cursor.execute(
        'INSERT INTO meeting_types (name, description) VALUES (?, ?)',
        ('採用面接', '候補者への質問、スキル確認、カルチャーフィット確認')
    )
    hr_id = cursor.lastrowid
    
    cursor.execute(
        'INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)',
        (hr_id, 
         '候補者の回答が抽象的で具体的でない場合', 
         'より具体的なエピソードを引き出すための深掘り質問を提案してください。「具体的にはどのような状況でしたか？」「その時あなたはどう行動しましたか？」など。')
    )

# --- CRUD Operations ---

def get_meeting_types() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM meeting_types ORDER BY id')
    types = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return types

def get_prompts_for_type(type_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM prompts WHERE meeting_type_id = ?', (type_id,))
    prompts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return prompts

def create_meeting_type(name: str, description: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO meeting_types (name, description) VALUES (?, ?)', (name, description))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def delete_meeting_type(type_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    # 関連するプロンプトも削除
    cursor.execute('DELETE FROM prompts WHERE meeting_type_id = ?', (type_id,))
    cursor.execute('DELETE FROM meeting_types WHERE id = ?', (type_id,))
    conn.commit()
    conn.close()

def create_prompt(meeting_type_id: int, trigger_condition: str, action_prompt: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO prompts (meeting_type_id, trigger_condition, action_prompt) VALUES (?, ?, ?)',
        (meeting_type_id, trigger_condition, action_prompt)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def delete_prompt(prompt_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
    conn.commit()
    conn.close()

# --- History Operations ---

def create_session(meeting_type_id: Optional[int], title: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO sessions (meeting_type_id, title) VALUES (?, ?)',
        (meeting_type_id, title)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def end_session(session_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE sessions SET end_time = CURRENT_TIMESTAMP WHERE id = ?',
        (session_id,)
    )
    conn.commit()
    conn.close()

def add_transcript(session_id: int, source: str, text: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO transcripts (session_id, source, text) VALUES (?, ?, ?)',
        (session_id, source, text)
    )
    conn.commit()
    conn.close()

def add_advice(session_id: int, trigger: str, text: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO advices (session_id, trigger_condition, advice_text) VALUES (?, ?, ?)',
        (session_id, trigger, text)
    )
    conn.commit()
    conn.close()

def get_sessions() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, m.name as meeting_type_name 
        FROM sessions s
        LEFT JOIN meeting_types m ON s.meeting_type_id = m.id
        ORDER BY s.start_time DESC
    ''')
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
    session = dict(cursor.fetchone())
    
    # ログ（時系列順）
    cursor.execute('SELECT * FROM transcripts WHERE session_id = ? ORDER BY timestamp', (session_id,))
    transcripts = [dict(row) for row in cursor.fetchall()]
    
    # アドバイス
    cursor.execute('SELECT * FROM advices WHERE session_id = ? ORDER BY timestamp', (session_id,))
    advices = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "session": session,
        "transcripts": transcripts,
        "advices": advices
    }

if __name__ == "__main__":
    init_db()
