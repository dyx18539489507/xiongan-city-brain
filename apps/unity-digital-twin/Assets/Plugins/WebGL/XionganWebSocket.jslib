mergeInto(LibraryManager.library, {
  XionganWebSocketConnect: function (urlPtr, gameObjectPtr) {
    var url = UTF8ToString(urlPtr);
    var gameObject = UTF8ToString(gameObjectPtr);
    window.__xionganSockets = window.__xionganSockets || [];
    var id = window.__xionganSockets.length;
    var socket = new WebSocket(url);
    window.__xionganSockets.push(socket);
    socket.onopen = function () { SendMessage(gameObject, "OnWebSocketOpen", ""); };
    socket.onmessage = function (event) {
      if (typeof event.data === "string") SendMessage(gameObject, "OnWebSocketMessage", event.data);
    };
    socket.onerror = function () { SendMessage(gameObject, "OnWebSocketClosed", "websocket error"); };
    socket.onclose = function (event) { SendMessage(gameObject, "OnWebSocketClosed", String(event.code)); };
    return id;
  },

  XionganWebSocketClose: function (socketId) {
    var sockets = window.__xionganSockets || [];
    var socket = sockets[socketId];
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      socket.close(1000, "unity client stopped");
      sockets[socketId] = null;
    }
  },

  XionganDispatchBrowserEvent: function (payloadPtr) {
    var payload = UTF8ToString(payloadPtr);
    var detail;
    try { detail = JSON.parse(payload); } catch (_) { detail = { type: "unity-message", payload: payload }; }
    window.dispatchEvent(new CustomEvent("xiongan-unity-event", { detail: detail }));
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "xiongan-unity-event", detail: detail }, window.location.origin);
    }
  }
});
