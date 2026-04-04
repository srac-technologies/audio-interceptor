const fs = require('fs');
const path = require('path');
const os = require('os');
const { Logger } = require('../main/logger');

describe('Logger', () => {
  let tmpDir;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'logger-test-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  test('有効時にログファイルを作成する', () => {
    const logger = new Logger({ logDir: tmpDir, logFile: 'test.log', enabled: true });
    logger.info('test message');
    logger.close();

    const logPath = path.join(tmpDir, 'test.log');
    expect(fs.existsSync(logPath)).toBe(true);
    const content = fs.readFileSync(logPath, 'utf8');
    expect(content).toContain('[INFO]');
    expect(content).toContain('test message');
  });

  test('無効時にログファイルを作成しない', () => {
    const logger = new Logger({ logDir: tmpDir, logFile: 'test.log', enabled: false });
    logger.info('should not appear');
    logger.close();

    const logPath = path.join(tmpDir, 'test.log');
    expect(fs.existsSync(logPath)).toBe(false);
  });

  test('各レベルで書き込める', () => {
    const logger = new Logger({ logDir: tmpDir, logFile: 'test.log', enabled: true });
    logger.debug('debug msg');
    logger.info('info msg');
    logger.warn('warn msg');
    logger.error('error msg');
    logger.close();

    const content = fs.readFileSync(path.join(tmpDir, 'test.log'), 'utf8');
    expect(content).toContain('[DEBUG]');
    expect(content).toContain('[INFO]');
    expect(content).toContain('[WARN]');
    expect(content).toContain('[ERROR]');
  });

  test('オブジェクトをJSON化して書き込む', () => {
    const logger = new Logger({ logDir: tmpDir, logFile: 'test.log', enabled: true });
    logger.info('data:', { key: 'value' });
    logger.close();

    const content = fs.readFileSync(path.join(tmpDir, 'test.log'), 'utf8');
    expect(content).toContain('"key":"value"');
  });

  test('タイムスタンプ形式が正しい', () => {
    const logger = new Logger({ logDir: tmpDir, logFile: 'test.log', enabled: true });
    logger.info('timestamp check');
    logger.close();

    const content = fs.readFileSync(path.join(tmpDir, 'test.log'), 'utf8');
    // YYYY-MM-DD HH:MM:SS 形式
    expect(content).toMatch(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);
  });

  test('ログディレクトリが存在しない場合に作成する', () => {
    const nestedDir = path.join(tmpDir, 'nested', 'deep');
    const logger = new Logger({ logDir: nestedDir, logFile: 'test.log', enabled: true });
    logger.info('nested dir test');
    logger.close();

    expect(fs.existsSync(path.join(nestedDir, 'test.log'))).toBe(true);
  });
});
