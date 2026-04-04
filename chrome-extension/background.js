// アクションボタンクリックでサイドパネルを開く
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
});

// サイドパネルをタブごとに有効化
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
