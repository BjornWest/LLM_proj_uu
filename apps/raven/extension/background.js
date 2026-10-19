chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true});
// Open once for the dedicated demo profile, on installation/startup.
chrome.runtime.onInstalled.addListener(() => {
  chrome.tabs.create({url: chrome.runtime.getURL('welcome.html')});
});
