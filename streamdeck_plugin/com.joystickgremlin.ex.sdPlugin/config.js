const globalSettings = (window.opener && window.opener.getGlobalSettings)
  ? window.opener.getGlobalSettings()
  : { host: "127.0.0.1", port: 9020 };

document.getElementById("host").value = globalSettings.host || "127.0.0.1";
document.getElementById("port").value = globalSettings.port || 9020;

document.getElementById("save").onclick = function () {
  const next = {
    host: document.getElementById("host").value || "127.0.0.1",
    port: parseInt(document.getElementById("port").value, 10) || 9020
  };
  if (window.opener && window.opener.sendGlobalSettingsToInspector) {
    window.opener.sendGlobalSettingsToInspector(next);
  }
  window.close();
};
