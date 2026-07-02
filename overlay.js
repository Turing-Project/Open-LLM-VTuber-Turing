/*
 * GIF action overlay for Open-LLM-VTuber.
 *
 * Injected into the frontend index.html by the backend (FrontendStaticFiles).
 * It sniffs the WebSocket messages the React app receives; when a message of
 * type "audio" carries `actions.gif`, it temporarily hides the Live2D canvas,
 * plays the GIF over the model area, then restores the Live2D after the GIF's
 * duration. This lets the AI trigger a full-body action animation (e.g. an
 * exasperated foot-stomp) that Live2D itself can't do.
 *
 * No React source changes / no rebuild required.
 */
(function () {
  "use strict";

  var OVERLAY_ID = "__gif_action_overlay__";
  var DEFAULT_DURATION = 5040; // ms; Fuming.gif single loop (63 frames). Overridable via actions.gif_duration_ms
  var playing = false;

  // In the browser client the page is same-origin as the backend, so relative
  // GIF URLs ("/gifs/x.gif") work directly. In the Electron pet the page is a
  // local file, so window.__GIF_BASE__ is set to the backend origin and we
  // prepend it to root-relative URLs.
  function resolveUrl(u) {
    if (u && u.charAt(0) === "/" && window.__GIF_BASE__) {
      return window.__GIF_BASE__ + u;
    }
    return u;
  }

  function playGif(url, durationMs) {
    if (playing || !url) return;
    playing = true;

    var canvases = Array.prototype.slice.call(document.querySelectorAll("canvas"));

    // Hide the Live2D canvas(es) so only the GIF shows while it plays.
    var hidden = [];
    canvases.forEach(function (c) {
      hidden.push([c, c.style.visibility]);
      c.style.visibility = "hidden";
    });

    // Fixed placement at the bottom-right corner. The GIF is sized by height
    // (aspect ratio preserved) to roughly match the on-screen model. Tune at
    // runtime with:  window.__GIF_OVERLAY_OPTS__ = { height: 520, margin: 0 }
    var opts = window.__GIF_OVERLAY_OPTS__ || {};
    var h = opts.height || Math.round(window.innerHeight * (opts.heightRatio || 0.45));
    var margin = opts.margin != null ? opts.margin : 0;

    var box = document.createElement("div");
    box.id = OVERLAY_ID;
    box.style.cssText =
      "position:fixed;z-index:2147483647;pointer-events:none;background:transparent;" +
      "right:" + margin + "px;bottom:" + margin + "px;height:" + h + "px;";

    var img = document.createElement("img");
    // Cache-bust so the GIF always restarts from frame 0.
    var resolved = resolveUrl(url);
    img.src = resolved + (resolved.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    img.style.cssText = "height:100%;width:auto;display:block;";
    box.appendChild(img);
    document.body.appendChild(box);

    setTimeout(function () {
      if (box.parentNode) box.parentNode.removeChild(box);
      hidden.forEach(function (pair) {
        pair[0].style.visibility = pair[1] || "";
      });
      playing = false;
    }, durationMs || DEFAULT_DURATION);
  }

  // Manual trigger (for testing / interaction): double-click anywhere plays
  // the action GIF. Also serves as a diagnostic independent of the AI path.
  document.addEventListener("dblclick", function () {
    console.log("[gif-overlay] dblclick -> playGif");
    playGif("/gifs/Fuming.gif", DEFAULT_DURATION);
  });

  // Diagnostic hooks: call playStompGif() from the DevTools console to test
  // rendering directly (bypasses click-through / WebSocket path entirely).
  window.playStompGif = function () {
    playGif("/gifs/Fuming.gif", DEFAULT_DURATION);
  };
  console.log("[gif-overlay] loaded. Try playStompGif() in the console.");

  function handleMessage(data) {
    try {
      var msg = typeof data === "string" ? JSON.parse(data) : data;
      if (msg && msg.type === "audio" && msg.actions && msg.actions.gif) {
        playGif(msg.actions.gif, msg.actions.gif_duration_ms);
      }
    } catch (e) {
      /* non-JSON / binary frame -> ignore */
    }
  }

  // Monkey-patch WebSocket so we can observe messages the React app receives.
  // Runs as a classic <script> in <head>, before the deferred module script,
  // so the patch is in place before the app opens its connection.
  var NativeWS = window.WebSocket;
  if (NativeWS && !NativeWS.__gifPatched) {
    var Patched = function (url, protocols) {
      var ws =
        protocols !== undefined ? new NativeWS(url, protocols) : new NativeWS(url);
      ws.addEventListener("message", function (ev) {
        handleMessage(ev.data);
      });
      return ws;
    };
    Patched.prototype = NativeWS.prototype;
    Patched.CONNECTING = NativeWS.CONNECTING;
    Patched.OPEN = NativeWS.OPEN;
    Patched.CLOSING = NativeWS.CLOSING;
    Patched.CLOSED = NativeWS.CLOSED;
    Patched.__gifPatched = true;
    window.WebSocket = Patched;
  }
})();
