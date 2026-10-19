document.querySelector('#open').onclick = async () => {
  const win = await chrome.windows.getCurrent();
  await chrome.sidePanel.open({windowId: win.id});
};
