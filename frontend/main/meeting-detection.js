/**
 * 会議検知ロジック（テスタブルな純粋関数として抽出）
 */

const meetingPatterns = [
  {
    name: 'Zoom',
    check: (t, o) => o.includes('zoom') || t.includes('zoom meeting'),
  },
  {
    name: 'Google Meet',
    check: (t, o) => {
      const isBrowser = ['chrome', 'edge', 'brave', 'firefox', 'chromium'].some(
        (b) => o.includes(b)
      );
      const isMeet =
        t.includes('meet') &&
        (t.includes('google meet') ||
          t.includes('meet.google.com') ||
          /meet\s*-\s*[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(t));
      return isBrowser && isMeet;
    },
  },
  {
    name: 'Microsoft Teams',
    check: (t, o) =>
      o.includes('teams') ||
      t.includes('microsoft teams') ||
      t.includes('teams meeting'),
  },
];

/**
 * ウィンドウ情報から会議アプリを検知する
 * @param {string} title - ウィンドウタイトル
 * @param {string} ownerName - ウィンドウオーナー名
 * @returns {{ name: string } | null} 検出された会議アプリ、またはnull
 */
function detectMeetingApp(title, ownerName) {
  const t = (title || '').toLowerCase();
  const o = (ownerName || '').toLowerCase();

  for (const pattern of meetingPatterns) {
    if (pattern.check(t, o)) {
      return { name: pattern.name };
    }
  }
  return null;
}

module.exports = { detectMeetingApp, meetingPatterns };
