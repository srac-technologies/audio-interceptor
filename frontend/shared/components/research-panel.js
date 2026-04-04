/**
 * ResearchPanel - リサーチ結果表示コンポーネント
 */
export class ResearchPanel {
  /**
   * @param {HTMLElement} container
   */
  constructor(container) {
    this.container = container;
    this.count = 0;
    this._onCountChange = null;
    this._showEmptyState();
  }

  onCountChange(handler) {
    this._onCountChange = handler;
  }

  addResearch(trigger, text, timestamp) {
    this._clearEmptyState();

    const item = document.createElement('div');
    item.className = 'ma-research-item';

    const header = document.createElement('div');
    header.className = 'ma-research-header';
    const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString('ja-JP') : new Date().toLocaleTimeString('ja-JP');
    header.innerHTML = `<span>${this._escapeHtml(trigger)}</span><span>${timeStr}</span>`;

    const content = document.createElement('div');
    content.className = 'ma-research-content';
    content.textContent = text;

    item.appendChild(header);
    item.appendChild(content);
    this.container.appendChild(item);

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

  _showEmptyState() {
    this.container.innerHTML = '<div class="ma-empty-state">リサーチ結果がここに表示されます</div>';
  }

  _clearEmptyState() {
    const empty = this.container.querySelector('.ma-empty-state');
    if (empty) empty.remove();
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}
