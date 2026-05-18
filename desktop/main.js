const { app, BrowserWindow, Menu, dialog, shell, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
const { spawn } = require('child_process');

let mainWindow = null;
let serverProcess = null;
let serverPort = null;

const DEFAULT_DESKTOP_PORT = 38492;
const DESKTOP_PORT = Number.parseInt(process.env.LUMEN_DESKTOP_PORT || String(DEFAULT_DESKTOP_PORT), 10);

// Keep Electron's browser storage in one stable location for both `npm run desktop`
// and packaged builds.  The app also uses a stable localhost port below so
// browser localStorage keeps the same origin across launches.
app.setName('Lumen AI Chat');
app.setPath('userData', path.join(app.getPath('appData'), 'Lumen AI Chat'));

function appRoot() {
  return app.isPackaged ? app.getAppPath() : path.resolve(__dirname, '..');
}

function appIconPath() {
  const root = appRoot();
  const assets = path.join(root, 'desktop', 'assets');

  if (process.platform === 'win32') {
    return path.join(assets, 'icon.ico');
  }
  return path.join(assets, 'icon.png');
}


function useCustomTitleBar() {
  return process.platform === 'win32' || process.platform === 'linux';
}

function desktopAssetPath(fileName) {
  return path.join(appRoot(), 'desktop', fileName);
}

function sendWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send('lumen-window-state', {
    maximized: mainWindow.isMaximized(),
    fullscreen: mainWindow.isFullScreen(),
  });
}

async function installDesktopChrome() {
  if (!useCustomTitleBar() || !mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  const cssPath = desktopAssetPath('titlebar.css');
  const jsPath = desktopAssetPath('titlebar.js');

  try {
    await mainWindow.webContents.insertCSS(fs.readFileSync(cssPath, 'utf8'));
    await mainWindow.webContents.executeJavaScript(fs.readFileSync(jsPath, 'utf8'));
  } catch (error) {
    console.error('[desktop] Failed to install custom title bar:', error);
  }
}

function bundledPython(root) {
  const candidates = process.platform === 'win32'
    ? [
        path.join(root, '.venv', 'Scripts', 'python.exe'),
        path.join(root, 'venv', 'Scripts', 'python.exe'),
      ]
    : [
        path.join(root, '.venv', 'bin', 'python3'),
        path.join(root, '.venv', 'bin', 'python'),
        path.join(root, 'venv', 'bin', 'python3'),
        path.join(root, 'venv', 'bin', 'python'),
      ];

  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function pythonCommand(root) {
  return process.env.LUMEN_PYTHON || bundledPython(root) || (process.platform === 'win32' ? 'python' : 'python3');
}

function canUsePort(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(port, '127.0.0.1', () => {
      server.close(() => resolve(true));
    });
  });
}

async function desktopPort() {
  if (Number.isInteger(DESKTOP_PORT) && DESKTOP_PORT > 0 && await canUsePort(DESKTOP_PORT)) {
    return DESKTOP_PORT;
  }

  throw new Error(
    `Port ${Number.isInteger(DESKTOP_PORT) ? DESKTOP_PORT : DEFAULT_DESKTOP_PORT} is already in use. `
    + 'Close the other Lumen instance or set LUMEN_DESKTOP_PORT to a stable free port.'
  );
}

function waitForHealth(port, timeoutMs = 30000) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: 1000 }, (res) => {
        res.resume();
        if (res.statusCode === 200) {
          resolve();
          return;
        }
        retry();
      });

      req.on('error', retry);
      req.on('timeout', () => {
        req.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error('The local Lumen server did not become ready.'));
        return;
      }
      setTimeout(check, 250);
    };

    check();
  });
}

async function startFlaskServer() {
  const root = appRoot();
  const port = await desktopPort();
  const python = pythonCommand(root);
  const code = [
    'from app import create_app',
    `create_app().run(debug=False, host="127.0.0.1", port=${port}, threaded=True, use_reloader=False)`,
  ].join('; ');

  serverPort = port;
  serverProcess = spawn(python, ['-c', code], {
    cwd: root,
    env: {
      ...process.env,
      LUMEN_DESKTOP: '1',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  serverProcess.stdout.on('data', (data) => process.stdout.write(`[flask] ${data}`));
  serverProcess.stderr.on('data', (data) => process.stderr.write(`[flask] ${data}`));
  serverProcess.on('exit', (code, signal) => {
    serverProcess = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('lumen-server-exit', { code, signal });
    }
  });

  await waitForHealth(port);
  return `http://127.0.0.1:${port}`;
}

function createWindow(url) {
  Menu.setApplicationMenu(null);

  const customTitleBar = useCustomTitleBar();

  mainWindow = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 960,
    minHeight: 680,
    title: 'Lumen AI Chat',
    show: false,
    frame: !customTitleBar,
    backgroundColor: '#0f172a',
    icon: appIconPath(),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(({ url: targetUrl }) => {
    shell.openExternal(targetUrl);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('did-finish-load', async () => {
    await installDesktopChrome();
    sendWindowState();
  });
  mainWindow.on('maximize', sendWindowState);
  mainWindow.on('unmaximize', sendWindowState);
  mainWindow.on('enter-full-screen', sendWindowState);
  mainWindow.on('leave-full-screen', sendWindowState);

  mainWindow.loadURL(url);
}

async function boot() {
  try {
    const url = await startFlaskServer();
    createWindow(url);
  } catch (error) {
    await dialog.showMessageBox({
      type: 'error',
      title: 'Lumen AI Chat failed to start',
      message: 'The desktop app could not start the local Flask server.',
      detail: `${error.message}\n\nMake sure Python is installed and run: pip install -r requirements.txt`,
    });
    app.quit();
  }
}

function stopFlaskServer() {
  if (!serverProcess) {
    return;
  }
  const child = serverProcess;
  serverProcess = null;
  child.kill(process.platform === 'win32' ? undefined : 'SIGTERM');
}


ipcMain.handle('lumen-window-minimize', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.minimize();
  }
});

ipcMain.handle('lumen-window-toggle-maximize', () => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
  sendWindowState();
});

ipcMain.handle('lumen-window-close', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.close();
  }
});

app.whenReady().then(boot);

app.on('window-all-closed', () => {
  stopFlaskServer();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', stopFlaskServer);

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0 && serverPort) {
    createWindow(`http://127.0.0.1:${serverPort}`);
  }
});
