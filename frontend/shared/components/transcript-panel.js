/**
 * TranscriptPanel - 文字起こし表示コンポーネント
 *
 * バブル表示(Electron)とコンパクト表示(Chrome Extension)の両方に対応。
 */
export class TranscriptPanel {
  /**
   * @param {HTMLElement} container
   * @param {Object} [options]
   * @param {'bubble'|'compact'} [options.displayMode='bubble']
   */
  constructor(container, options = {}) {
    this.container = container;
    this.displayMode = options.displayMode || 'bubble';
    this.count = 0;
    this._onCountChange = null;
    this._showEmptyState();
  }

  onCountChange(handler) {
    this._onCountChange = handler;
  }

  addTranscript(source, text) {
    this._clearEmptyState();

    if (this.displayMode === 'bubble') {
      this._addBubble(source, text);
    } else {
      this._addCompact(source, text);
    }

    this.count++;
    if (this._onCountChange) this._onCountChange(this.count);
    this.container.scrollTop = this.container.scrollHeight;
  }

  clear() {
    this.container.innerHTML = '';
    this.count = 0;
    if (this._onCountChange) this._onCountChange(this.count);
    this._showEmptyState();
  }

  _addBubble(source, text) {
    const bubble = document.createElement('div');
    bubble.className = `ma-transcript-bubble ${source}`;

    const label = document.createElement('div');
    label.className = `ma-bubble-label ${source}`;
    label.textContent = source === 'speaker' ? 'Speaker' : 'Mic';

    const content = document.createElement('div');
    content.textContent = text;

    bubble.appendChild(label);
    bubble.appendChild(content);
    this.container.appendChild(bubble);
  }

  _addCompact(source, text) {
    const entry = document.createElement('div');
    entry.className = 'ma-transcript-entry';
    const sourceSpan = document.createElement('span');
    sourceSpan.className = 'source';
    sourceSpan.textContent = `[${source}]`;
    const textSpan = document.createElement('span');
    textSpan.className = 'text';
    textSpan.textContent = ` ${text}`;
    entry.appendChild(sourceSpan);
    entry.appendChild(textSpan);
    this.container.appendChild(entry);
  }

  _showEmptyState() {
    this.container.innerHTML = '<div class="ma-empty-state">文字起こしがここに表示されます</div>';
  }

  _clearEmptyState() {
    const empty = this.container.querySelector('.ma-empty-state');
    if (empty) empty.remove();
  }
}
