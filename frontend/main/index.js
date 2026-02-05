const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow = null;
let pythonProcess = null;

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

app.whenReady().then(() => {
  createWindow();
  startPythonBackend();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopPythonBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
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
