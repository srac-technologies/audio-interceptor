"""
ログシステム — ファイル + コンソール出力
開発時はファイルに書き込み、本番ビルドではオミット可能
"""
import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# 環境変数で制御: LOG_LEVEL, LOG_DIR, LOG_ENABLED
LOG_ENABLED = os.getenv("LOG_ENABLED", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if not getattr(sys, 'frozen', False) else "WARNING")
# パッケージ版: LOG_DIR環境変数 → MEETING_ASSISTANT_CONFIG_DIR/logs → スクリプト横/logs
_default_log_dir = str(Path(os.getenv('MEETING_ASSISTANT_CONFIG_DIR', str(Path(__file__).parent))) / "logs")
LOG_DIR = os.getenv("LOG_DIR", _default_log_dir)
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB
LOG_BACKUP_COUNT = 3

_initialized = False


def setup_logging():
    """ログシステムを初期化する（アプリ起動時に1回呼ぶ）"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    root_logger = logging.getLogger()

    if not LOG_ENABLED:
        root_logger.setLevel(logging.CRITICAL + 1)
        return

    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # コンソールハンドラ（常時）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ファイルハンドラ（開発時のみ、または LOG_ENABLED=true）
    try:
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "backend.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError as e:
        root_logger.warning(f"Failed to create log file handler: {e}")


def get_logger(name: str) -> logging.Logger:
    """名前付きloggerを取得する"""
    setup_logging()
    return logging.getLogger(name)
