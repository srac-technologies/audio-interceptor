const { detectMeetingApp } = require('../main/meeting-detection');

describe('detectMeetingApp', () => {
  describe('Zoom検知', () => {
    test('ownerにzoomを含む場合', () => {
      const result = detectMeetingApp('Meeting', 'zoom.us');
      expect(result).toEqual({ name: 'Zoom' });
    });

    test('タイトルにzoom meetingを含む場合', () => {
      const result = detectMeetingApp('Zoom Meeting #123', 'some-app');
      expect(result).toEqual({ name: 'Zoom' });
    });

    test('Zoom無関係のウィンドウ', () => {
      const result = detectMeetingApp('My Document', 'vscode');
      expect(result).toBeNull();
    });
  });

  describe('Google Meet検知', () => {
    test('Chromeでgoogle meetを開いている場合', () => {
      const result = detectMeetingApp('Google Meet - abc-defg-hij', 'chrome');
      expect(result).toEqual({ name: 'Google Meet' });
    });

    test('Firefoxでmeet.google.comを開いている場合', () => {
      const result = detectMeetingApp('meet.google.com/abc-defg-hij', 'firefox');
      expect(result).toEqual({ name: 'Google Meet' });
    });

    test('ブラウザでないアプリでmeetを含む場合は検知しない', () => {
      const result = detectMeetingApp('Google Meet', 'notepad');
      expect(result).toBeNull();
    });

    test('Chromeだがmeet以外のページ', () => {
      const result = detectMeetingApp('GitHub - Pull Request', 'chrome');
      expect(result).toBeNull();
    });

    test('meet IDパターン (abc-defg-hij) での検知', () => {
      const result = detectMeetingApp('meet - abc-defg-hij', 'brave');
      expect(result).toEqual({ name: 'Google Meet' });
    });
  });

  describe('Microsoft Teams検知', () => {
    test('ownerにteamsを含む場合', () => {
      const result = detectMeetingApp('チーム会議', 'teams');
      expect(result).toEqual({ name: 'Microsoft Teams' });
    });

    test('タイトルにmicrosoft teamsを含む場合', () => {
      const result = detectMeetingApp('Microsoft Teams Meeting', 'electron');
      expect(result).toEqual({ name: 'Microsoft Teams' });
    });

    test('タイトルにteams meetingを含む場合', () => {
      const result = detectMeetingApp('Teams Meeting - 週次定例', 'app');
      expect(result).toEqual({ name: 'Microsoft Teams' });
    });
  });

  describe('エッジケース', () => {
    test('nullのタイトル', () => {
      const result = detectMeetingApp(null, 'chrome');
      expect(result).toBeNull();
    });

    test('nullのオーナー', () => {
      const result = detectMeetingApp('Google Meet', null);
      expect(result).toBeNull();
    });

    test('空文字列', () => {
      const result = detectMeetingApp('', '');
      expect(result).toBeNull();
    });

    test('大文字小文字の区別なし', () => {
      const result = detectMeetingApp('ZOOM MEETING', 'APP');
      expect(result).toEqual({ name: 'Zoom' });
    });
  });
});
