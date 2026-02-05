const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const activeWin = require('active-win');

let mainWindow = null;
let pythonProcess = null;
let detectionInterval = null;
let lastDetectedApp = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  // 開発中は簡易HTMLをロード
  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  // DevTools を開く
  mainWindow.webContents.openDevTools();

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Pythonバックエンドを起動
function startPythonBackend() {
  const pythonScript = path.join(__dirname, '../../backend/server.py');
  
  pythonProcess = spawn('python3', [pythonScript]);

  pythonProcess.stdout.on('data', (data) => {
    console.log(`[Python] ${data}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`[Python Error] ${data}`);
  });

  pythonProcess.on('close', (code) => {
    console.log(`Python process exited with code ${code}`);
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

    const title = (window.title || '').toLowerCase();
    const owner = (window.owner?.name || '').toLowerCase();

    // デバッグ用（開発時）
    // console.log(`Active window: ${window.title} | Owner: ${owner}`);

    // 検知パターン
    const meetingPatterns = [
      { 
        name: 'Zoom', 
        check: (t, o) => o.includes('zoom') || t.includes('zoom meeting')
      },
      { 
        name: 'Google Meet', 
        check: (t, o) => {
          const isBrowser = ['chrome', 'edge', 'brave', 'firefox', 'chromium'].some(b => o.includes(b));
          const isMeet = t.includes('meet') && (t.includes('google meet') || t.includes('meet.google.com') || /meet\s*-\s*[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(t));
          return isBrowser && isMeet;
        }
      },
      { 
        name: 'Microsoft Teams', 
        check: (t, o) => o.includes('teams') || t.includes('microsoft teams') || t.includes('teams meeting')
      }
    ];

    for (const pattern of meetingPatterns) {
      if (pattern.check(title, owner)) {
        notifyMeetingDetected(pattern.name, window.title);
        return;
      }
    }

    // 検知されなくなったらリセット
    if (lastDetectedApp) {
      lastDetectedApp = null;
    }

  } catch (error) {
    // エラーは静かに無視（権限エラーなど）
    if (error.message && !error.message.includes('permission')) {
      console.error('Detection error:', error);
    }
  }
}

function notifyMeetingDetected(appName, windowTitle) {
  // 同じアプリを連続して通知しない
  if (lastDetectedApp === appName) return;
  
  lastDetectedApp = appName;
  console.log(`Meeting detected: ${appName}`);
  
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
  
  console.log('Starting meeting detection...');
  detectionInterval = setInterval(detectMeeting, 2000); // 2秒ごとにチェック
  detectMeeting(); // 即座に1回実行
}

function stopMeetingDetection() {
  if (detectionInterval) {
    clearInterval(detectionInterval);
    detectionInterval = null;
    console.log('Meeting detection stopped');
  }
}

app.whenReady().then(() => {
  createWindow();
  startPythonBackend();
  startMeetingDetection(); // 会議検知を開始

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopMeetingDetection();
  stopPythonBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
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
        transcribe_mode: options?.transcribe || false,
        meeting_type_id: options?.meeting_type_id || null,
        tmp_dir: './tmp'
      })
    });
    
    const result = await response.json();
    console.log('Recording started:', result);
    return result;
  } catch (error) {
    console.error('Failed to start recording:', error);
    return { success: false, message: error.message };
  }
});

ipcMain.handle('stop-recording', async () => {
  try {
    const response = await fetch('http://localhost:8000/recording/stop', {
      method: 'POST'
    });
    
    const result = await response.json();
    console.log('Recording stopped:', result);
    return result;
  } catch (error) {
    console.error('Failed to stop recording:', error);
    return { success: false, message: error.message };
  }
});
