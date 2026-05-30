chrome.runtime.onInstalled.addListener(()=>{console.log("Workforce IQ Dashboard installed")});chrome.action.onClicked.addListener(()=>{chrome.tabs.create({url:chrome.runtime.getURL("index.html")})});
