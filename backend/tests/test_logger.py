"""logger.py の単体テスト"""
import os
import logging
import pytest
from unittest.mock import patch
from pathlib import Path


class TestSetupLogging:
    def test_creates_log_directory(self, tmp_path):
        """ログディレクトリが作成される"""
        log_dir = str(tmp_path / "new_logs")
        with patch.dict(os.environ, {"LOG_DIR": log_dir, "LOG_ENABLED": "true"}):
            import importlib
            import logger as logger_mod
            logger_mod._initialized = False
            importlib.reload(logger_mod)
            logger_mod.setup_logging()

        assert os.path.exists(log_dir)

    def test_log_file_created(self, tmp_path):
        """ログファイルが作成される"""
        log_dir = str(tmp_path / "logs")
        with patch.dict(os.environ, {"LOG_DIR": log_dir, "LOG_ENABLED": "true", "LOG_LEVEL": "DEBUG"}):
            import importlib
            import logger as logger_mod
            logger_mod._initialized = False
            importlib.reload(logger_mod)
            logger_mod.setup_logging()

            test_logger = logging.getLogger("test_file_creation")
            test_logger.info("test message")

            # ハンドラをフラッシュ
            for h in logging.getLogger().handlers:
                h.flush()

        assert os.path.exists(os.path.join(log_dir, "backend.log"))

    def test_disabled_logging(self, tmp_path):
        """LOG_ENABLED=falseでログが無効化される"""
        log_dir = str(tmp_path / "logs")
        with patch.dict(os.environ, {"LOG_DIR": log_dir, "LOG_ENABLED": "false"}):
            import importlib
            import logger as logger_mod
            logger_mod._initialized = False
            importlib.reload(logger_mod)
            logger_mod.setup_logging()

            root = logging.getLogger()
            # CRITICAL以上でのみログ出力 = 実質無効
            assert root.level > logging.CRITICAL


class TestGetLogger:
    def test_returns_named_logger(self, tmp_path):
        """名前付きloggerを返す"""
        log_dir = str(tmp_path / "logs")
        with patch.dict(os.environ, {"LOG_DIR": log_dir, "LOG_ENABLED": "true"}):
            import importlib
            import logger as logger_mod
            logger_mod._initialized = False
            importlib.reload(logger_mod)
            log = logger_mod.get_logger("test_module")
            assert log.name == "test_module"
