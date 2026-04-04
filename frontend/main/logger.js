/**
 * ログシステム — Electron main/renderer process 両対応
 * - ファイルに書き込み（logs/frontend.log）
 * - 開発時有効、本番ビルドでは環境変数 LOG_ENABLED=false でオミット
 * - renderer processのconsole出力もキャプチャ
 */

const fs = require('fs');
const path = require('path');

const MAX_LOG_SIZE = 5 * 1024 * 1024; // 5MB
const MAX_BACKUP_COUNT = 3;

class Logger {
  constructor(options = {}) {
    this.enabled = options.enabled !== undefined
      ? options.enabled
      : (process.env.LOG_ENABLED || 'true').toLowerCase() === 'true';
    this.logDir = options.logDir || path.join(__dirname, '../../logs');
    this.logFile = options.logFile || 'frontend.log';
    if (this.enabled) {
      this._ensureLogDir();
      this._rotateIfNeeded();
    }
  }

  _ensureLogDir() {
    try {
      fs.mkdirSync(this.logDir, { recursive: true });
    } catch (e) {
      // ignore
    }
  }

  _logPath() {
    return path.join(this.logDir, this.logFile);
  }

  _rotateIfNeeded() {
    const logPath = this._logPath();
    try {
      if (!fs.existsSync(logPath)) return;
      const stat = fs.statSync(logPath);
      if (stat.size < MAX_LOG_SIZE) return;

      // ローテーション
      for (let i = MAX_BACKUP_COUNT - 1; i >= 1; i--) {
        const src = `${logPath}.${i}`;
        const dst = `${logPath}.${i + 1}`;
        if (fs.existsSync(src)) fs.renameSync(src, dst);
      }
      fs.renameSync(logPath, `${logPath}.1`);
    } catch (e) {
      // ignore rotation errors
    }
  }

  _write(level, ...args) {
    if (!this.enabled) return;
    const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const message = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
    const line = `${timestamp} [${level}] ${message}\n`;

    try {
      fs.appendFileSync(this._logPath(), line, 'utf8');
    } catch (e) {
      // ignore write errors
    }
  }

  debug(...args) { this._write('DEBUG', ...args); }
  info(...args) { this._write('INFO', ...args); }
  warn(...args) { this._write('WARN', ...args); }
  error(...args) { this._write('ERROR', ...args); }

  /**
   * renderer processのconsole出力をキャプチャするためのElectron設定
   * mainWindowのwebContentsに対して呼ぶ
   */
  captureRenderer(webContents) {
    if (!this.enabled || !webContents) return;

    webContents.on('console-message', (_event, level, message, line, sourceId) => {
      const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'];
      const levelStr = levels[level] || 'INFO';
      const source = sourceId ? path.basename(sourceId) : 'renderer';
      this._write(levelStr, `[${source}:${line}]`, message);
    });
  }

  close() {
    // sync write なので特にcleanupは不要
  }
}

// シングルトンインスタンス
let _instance = null;

function getLogger(options) {
  if (!_instance) {
    _instance = new Logger(options);
  }
  return _instance;
}

module.exports = { Logger, getLogger };
