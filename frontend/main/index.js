const { app, BrowserWindow, ipcMain, Notification, Tray, Menu, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const activeWin = require('active-win');
const { detectMeetingApp } = require('./meeting-detection');
const { getLogger } = require('./logger');

const log = getLogger({
  logDir: app.isPackaged
    ? path.join(app.getPath('userData'), 'logs')
    : path.join(__dirname, '../../logs'),
  enabled: (process.env.LOG_ENABLED || 'true').toLowerCase() === 'true',
});

let mainWindow = null;
let pythonProcess = null;
let detectionInterval = null;
let lastDetectedApp = null;
let tray = null;

// 初回起動時の設定セットアップ
function setupConfigDirectory() {
  if (!app.isPackaged) return; // 開発モードではスキップ
  
  const configDir = path.join(app.getPath('userData'), 'config');
  
  // 設定ディレクトリが存在しない場合は作成
  if (!fs.existsSync(configDir)) {
    fs.mkdirSync(configDir, { recursive: true });
    log.info('[Setup] Created config directory:', configDir);
    
    // .env.example をコピー
    const examplePath = path.join(process.resourcesPath, 'backend', '.env.example');
    const envPath = path.join(configDir, '.env');
    
    if (fs.existsSync(examplePath)) {
      fs.copyFileSync(examplePath, envPath);
      log.info('[Setup] Created .env file from example');
    }

    // セットアップガイドをコピー
    const setupGuideSrc = path.join(process.resourcesPath, 'backend', 'CONFIG_README.txt');
    const setupGuideDst = path.join(configDir, 'CONFIG_README.txt');
    if (fs.existsSync(setupGuideSrc) && !fs.existsSync(setupGuideDst)) {
      fs.copyFileSync(setupGuideSrc, setupGuideDst);
      log.info('[Setup] Copied CONFIG_README.txt');
    }

    // 初回起動の通知
    dialog.showMessageBox({
      type: 'info',
      title: 'Meeting Assistant - 初回セットアップ',
      message: '設定ファイルを作成しました',
      detail: `設定フォルダ: ${configDir}\n\n1. .env ファイルに OpenAI API キーを設定\n2. Google Calendar を使う場合は creds.json を配置\n\n詳細は CONFIG_README.txt を参照してください。`,
      buttons: ['OK', '設定フォルダを開く']
    }).then(result => {
      if (result.response === 1) {
        require('electron').shell.openPath(configDir);
      }
    });
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    frame: false, // ツールバー非表示
    transparent: true, // 背景透過有効
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  // 開発中は簡易HTMLをロード
  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  // renderer processのconsole出力をログファイルにキャプチャ
  log.captureRenderer(mainWindow.webContents);

  // DevTools は開発時のみ（環境変数で制御）
  if (process.env.NODE_ENV === 'development') {
    // mainWindow.webContents.openDevTools();
  }

  // ウィンドウを閉じたときの処理（最小化してトレイへ）
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
      
      // 初回のみ通知を表示
      if (!tray.hasShownHideNotification) {
        const notification = new Notification({
          title: 'Meeting Assistant',
          body: 'バックグラウンドで実行中です。トレイアイコンから操作できます。'
        });
        notification.show();
        tray.hasShownHideNotification = true;
      }
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createTray() {
  // トレイアイコンを作成（アイコンがない場合は空文字列でもOK）
  // 本番では適切なアイコンファイルを使用
  const iconPath = path.join(__dirname, '../renderer/tray-icon.png');
  
  // アイコンが存在しない場合はデフォルトを使用
  try {
    tray = new Tray(iconPath);
  } catch (error) {
    // フォールバック: nativeImageで小さいアイコンを生成
    const { nativeImage } = require('electron');
    const icon = nativeImage.createEmpty();
    tray = new Tray(icon);
  }
  
  tray.setToolTip('Meeting Assistant');
  tray.hasShownHideNotification = false;

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '表示',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      }
    },
    {
      label: '録音中...',
      id: 'recording-status',
      enabled: false,
      visible: false
    },
    { type: 'separator' },
    {
      label: '終了',
      click: () => {
        app.isQuitting = true;
        app.quit();
      }
    }
  ]);

  tray.setContextMenu(contextMenu);

  // トレイアイコンをクリックしたらウィンドウを表示
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

// Pythonバックエンドを起動
function startPythonBackend() {
  let pythonExecutable;
  let pythonArgs = [];
  
  // 開発モードか本番モードかを判定
  if (app.isPackaged) {
    // 本番モード: パッケージされたバックエンドを使用
    const resourcesPath = process.resourcesPath;
    pythonExecutable = path.join(resourcesPath, 'backend', 'server');
    log.info('[Backend] Using packaged backend:', pythonExecutable);
  } else {
    // 開発モード: venv内のPythonを優先して使用
    const backendDir = path.join(__dirname, '../../backend');
    const venvPython = path.join(backendDir, 'venv/bin/python3');
    
    if (fs.existsSync(venvPython)) {
      pythonExecutable = venvPython;
      log.info('[Backend] Using venv Python:', venvPython);
    } else {
      pythonExecutable = 'python3';
      log.info('[Backend] Using system Python (venv not found)');
    }
    
    pythonArgs = [path.join(backendDir, 'server.py')];
  }
  
  const configDir = app.isPackaged
    ? path.join(app.getPath('userData'), 'config')
    : path.join(__dirname, '../../backend');
  const logDir = app.isPackaged
    ? path.join(app.getPath('userData'), 'logs')
    : path.join(__dirname, '../../logs');

  pythonProcess = spawn(pythonExecutable, pythonArgs, {
    env: {
      ...process.env,
      // 本番モードでは設定ファイルをユーザーディレクトリから読み込む
      MEETING_ASSISTANT_CONFIG_DIR: configDir,
      LOG_DIR: logDir
    }
  });

  pythonProcess.stdout.on('data', (data) => {
    log.info(`[Python] ${data}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    log.error(`[Python Error] ${data}`);
  });

  pythonProcess.on('close', (code) => {
    log.info(`Python process exited with code ${code}`);
  });
}

// Pythonバックエンドを停止
function stopPythonBackend() {
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
}

// 会議検知ロジック
async function detectMeeting() {
  try {
    const window = await activeWin();
    if (!window) return;

    const result = detectMeetingApp(window.title, window.owner?.name);
    if (result) {
      notifyMeetingDetected(result.name, window.title);
      return;
    }

    // 検知されなくなったらリセット
    if (lastDetectedApp) {
      lastDetectedApp = null;
    }

  } catch (error) {
    // エラーは静かに無視（JSON parse エラー、権限エラーなど）
    // active-win の Linux での既知の問題: 空のJSONや不正なJSONが返されることがある
    const errorMsg = error.message || '';
    const isKnownError = errorMsg.includes('permission') || 
                         errorMsg.includes('JSON') || 
                         errorMsg.includes('Unexpected');
    
    if (!isKnownError) {
      log.error('Detection error:', error.message);
    }
    // 既知のエラーは無視して処理を継続
  }
}

function notifyMeetingDetected(appName, windowTitle) {
  // 同じアプリを連続して通知しない
  if (lastDetectedApp === appName) return;
  
  lastDetectedApp = appName;
  log.info(`Meeting detected: ${appName}`);
  
  // システム通知を表示
  if (Notification.isSupported()) {
    const notification = new Notification({
      title: '🎯 会議が検出されました',
      body: `${appName} の会議が開始されました。録音を開始しますか？`,
      icon: path.join(__dirname, '../renderer/icon.png'), // アイコンがあれば
      urgency: 'normal',
      timeoutType: 'default'
    });
    
    notification.on('click', () => {
      // 通知をクリックしたらウィンドウをフォーカス
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.focus();
      }
    });
    
    notification.show();
  }
  
  // Electron UI内の通知バナーも表示
  if (mainWindow) {
    mainWindow.webContents.send('meeting-detected', {
      app: appName,
      title: windowTitle
    });
  }
}

// 検知の開始・停止
function startMeetingDetection() {
  if (detectionInterval) return;
  
  log.info('Starting meeting detection...');
  detectionInterval = setInterval(detectMeeting, 2000); // 2秒ごとにチェック
  detectMeeting(); // 即座に1回実行
}

function stopMeetingDetection() {
  if (detectionInterval) {
    clearInterval(detectionInterval);
    detectionInterval = null;
    log.info('Meeting detection stopped');
  }
}

app.whenReady().then(() => {
  setupConfigDirectory(); // 初回セットアップ
  createTray();
  createWindow();
  startPythonBackend();
  startMeetingDetection(); // 会議検知を開始

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    } else if (mainWindow) {
      mainWindow.show();
    }
  });
});

app.on('window-all-closed', () => {
  // macOS以外でもウィンドウが全て閉じてもアプリは終了しない（トレイに常駐）
  // 明示的に終了ボタンを押したときのみ終了
  if (app.isQuitting) {
    stopMeetingDetection();
    stopPythonBackend();
    app.quit();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  stopMeetingDetection();
  stopPythonBackend();
});

// IPC handlers
ipcMain.handle('start-recording', async (event, options) => {
  try {
    const response = await fetch('http://localhost:8000/recording/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcribe_enabled: options?.transcribe_enabled || false,
        meeting_type_id: options?.meeting_type_id || null,
        title: options?.title || '無題の会議',
        tmp_dir: './tmp'
      })
    });
    
    const result = await response.json();
    log.info('Recording started:', JSON.stringify(result));
    return result;
  } catch (error) {
    log.error('Failed to start recording:', error.message);
    return { success: false, message: error.message };
  }
});

ipcMain.handle('stop-recording', async () => {
  try {
    const response = await fetch('http://localhost:8000/recording/stop', {
      method: 'POST'
    });
    
    const result = await response.json();
    log.info('Recording stopped:', JSON.stringify(result));
    return result;
  } catch (error) {
    log.error('Failed to stop recording:', error.message);
    return { success: false, message: error.message };
  }
});
