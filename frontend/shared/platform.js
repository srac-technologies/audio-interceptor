/**
 * PlatformAdapter - プラットフォーム差異を吸収するインターフェース
 *
 * Electron / Chrome Extension それぞれが実装を提供する。
 * UI コンポーネントは必ずこのアダプタ経由でプラットフォーム機能にアクセスする。
 */

/** @type {PlatformAdapter|null} */
let _adapter = null;

/**
 * @typedef {Object} PlatformAdapter
 * @property {'electron'|'chrome-extension'|'web'} type
 * @property {(options: Object) => Promise<Object>} startRecording
 * @property {() => Promise<Object>} stopRecording
 * @property {(title: string, body: string) => void} showNotification
 * @property {() => boolean} supportsDrag - ウィンドウドラッグをサポートするか
 * @property {() => boolean} supportsFileSystem - ファイルシステムアクセスをサポートするか
 * @property {(event: string, handler: Function) => void} onPlatformEvent
 */

export function setPlatformAdapter(adapter) {
  _adapter = adapter;
}

export function getPlatformAdapter() {
  if (!_adapter) {
    throw new Error('PlatformAdapter が未設定です。setPlatformAdapter() を先に呼んでください。');
  }
  return _adapter;
}
