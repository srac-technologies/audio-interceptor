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

if __name__ == "__main__":
    init_db()
