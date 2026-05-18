const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lumenDesktop', {
  platform: process.platform,
  minimize: () => ipcRenderer.invoke('lumen-window-minimize'),
  toggleMaximize: () => ipcRenderer.invoke('lumen-window-toggle-maximize'),
  close: () => ipcRenderer.invoke('lumen-window-close'),
  onWindowState: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('lumen-window-state', listener);
    return () => ipcRenderer.removeListener('lumen-window-state', listener);
  },
  onServerExit: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('lumen-server-exit', listener);
    return () => ipcRenderer.removeListener('lumen-server-exit', listener);
  },
});
