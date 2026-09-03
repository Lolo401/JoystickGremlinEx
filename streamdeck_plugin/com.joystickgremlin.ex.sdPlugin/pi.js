let websocket = null;
let uuid = null;
let actionInfo = {};
let globalSettings = { host: "127.0.0.1", port: 9020 };
let saveTimer = null;

function connectElgatoStreamDeckSocket(inPort, inUUID, inRegisterEvent, inInfo, inActionInfo) {
  uuid = inUUID;
  try {
    actionInfo = JSON.parse(inActionInfo);
  } catch (e) {
    actionInfo = {};
  }

  websocket = new WebSocket("ws://127.0.0.1:" + inPort);
  websocket.onopen = function () {
    websocket.send(JSON.stringify({ event: inRegisterEvent, uuid: uuid }));
    websocket.send(JSON.stringify({ event: "getGlobalSettings", context: uuid }));
    requestStatus();
    loadSettings();
  };
  websocket.onmessage = function (evt) {
    const data = JSON.parse(evt.data);
    if (data.event === "didReceiveGlobalSettings") {
      globalSettings = Object.assign(
        { host: "127.0.0.1", port: 9020 },
        (data.payload && data.payload.settings) || {}
      );
    } else if (data.event === "sendToPropertyInspector" && data.payload) {
      if (data.payload.event === "connectionStatus") {
        setStatus(data.payload.connected, data.payload.host, data.payload.port);
      } else if (data.payload.event === "buttonId" && data.payload.buttonId != null) {
        const el = document.getElementById("buttonId");
        if (!el.value || el.value.trim() === "") {
          el.value = String(data.payload.buttonId);
        }
      }
    } else if (data.event === "didReceiveSettings") {
      applySettings(data.payload.settings || {});
    }
  };

  const buttonEl = document.getElementById("buttonId");
  buttonEl.addEventListener("change", function () { saveSettings(true); });
  buttonEl.addEventListener("input", function () { saveSettings(false); });
  document.getElementById("openConfig").addEventListener("click", function () {
    window.open("./config.html", "jgex-plugin-config");
  });
}

function uniqueDefaultId() {
  const ctx = String(uuid || "").replace(/[^a-zA-Z0-9]/g, "");
  const suffix = (ctx.slice(0, 6) || Math.random().toString(36).slice(2, 8)).toLowerCase();
  return "btn-" + suffix;
}

function normalizeButtonId(buttonId) {
  if (buttonId == null) return "";
  return String(buttonId).trim().replace(/[^A-Za-z0-9\-_.:]/g, "");
}

function loadSettings() {
  applySettings((actionInfo.payload && actionInfo.payload.settings) || {});
}

function applySettings(settings) {
  const el = document.getElementById("buttonId");
  const existing = normalizeButtonId(settings.buttonId);
  if (existing) {
    el.value = existing;
    return;
  }
  if (!el.value || !normalizeButtonId(el.value)) {
    el.value = uniqueDefaultId();
    saveSettings(true);
  }
}

function currentSettings() {
  let buttonId = normalizeButtonId(document.getElementById("buttonId").value);
  if (!buttonId) buttonId = uniqueDefaultId();
  return { buttonId: buttonId };
}

function saveSettings(immediate) {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  const run = function () {
    const settings = currentSettings();
    document.getElementById("buttonId").value = settings.buttonId;
    websocket.send(JSON.stringify({
      event: "setSettings",
      context: uuid,
      payload: settings
    }));
    websocket.send(JSON.stringify({
      event: "sendToPlugin",
      context: uuid,
      action: actionUUID(),
      payload: {
        event: "settingsChanged",
        settings: settings
      }
    }));
  };
  if (immediate) run();
  else saveTimer = setTimeout(run, 250);
}

function actionUUID() {
  return actionInfo.action || "com.joystickgremlin.ex.button";
}

function requestStatus() {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
  websocket.send(JSON.stringify({
    event: "sendToPlugin",
    context: uuid,
    action: actionUUID(),
    payload: { event: "getStatus" }
  }));
}

function setStatus(connected, host, port) {
  const el = document.getElementById("status");
  if (connected) {
    el.textContent = "Connected to JG Ex";
    el.className = "sdpi-item-value ok";
  } else {
    el.textContent = "JG Ex not running / bridge offline";
    el.className = "sdpi-item-value err";
  }
  if (host) globalSettings.host = host;
  if (port) globalSettings.port = port;
}

window.getGlobalSettings = function () {
  return Object.assign({}, globalSettings);
};

window.sendGlobalSettingsToInspector = function (settings) {
  globalSettings = Object.assign({ host: "127.0.0.1", port: 9020 }, settings || {});
  if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
  websocket.send(JSON.stringify({
    event: "setGlobalSettings",
    context: uuid,
    payload: globalSettings
  }));
  websocket.send(JSON.stringify({
    event: "sendToPlugin",
    context: uuid,
    action: actionUUID(),
    payload: {
      event: "setBridge",
      host: globalSettings.host,
      port: globalSettings.port
    }
  }));
  setTimeout(requestStatus, 400);
};
