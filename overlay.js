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
  var GIF_CANVAS = { width: 834, height: 1112 };
  var GIF_BODY_BOUNDS = { left: 204, top: 59, width: 407, height: 1019 };
  var DEFAULT_GIF_GEOMETRY = {
    body: GIF_BODY_BOUNDS,
    clip: { left: 110, top: 56, width: 592, height: 1022 },
    durationMs: DEFAULT_DURATION
  };
  var GIF_GEOMETRIES = {
    "Fuming.gif": { clip: { left: 110, top: 56, width: 592, height: 1022 }, durationMs: 5040 },
    "## 收到消息｜惊喜反应 Surpris_2.gif": { clip: { left: 132, top: 21, width: 541, height: 1064 }, durationMs: 5040 },
    "01 开心（开心的蹦起来）--使用上传的_2.gif": { clip: { left: 54, top: 16, width: 711, height: 1062 }, durationMs: 5040 },
    "02 害羞（羞红脸 低下头）--使用上传_1.gif": { clip: { left: 184, top: 61, width: 446, height: 1018 }, durationMs: 5040 },
    "02 开心挥手 Wave_1.gif": { clip: { left: 72, top: 60, width: 590, height: 1019 }, durationMs: 5040 },
    "02AI思考｜AI处理中 Thinking-.gif": { clip: { left: 153, top: 59, width: 510, height: 1019 }, durationMs: 5040 },
    "03 生气.gif": { clip: { left: 110, top: 55, width: 598, height: 1023 }, durationMs: 5040 },
    "04 震惊（睁大眼睛）--使用上传的企鹅.gif": { clip: { left: 92, top: 58, width: 622, height: 1020 }, durationMs: 5040 },
    "05 哭（可爱哭泣表情，有蓝色泪水流下）.gif": { clip: { left: 113, top: 55, width: 573, height: 1024 }, durationMs: 5040 },
    "06 点赞（伸出手指点赞 说牛哇牛哇）-.gif": { clip: { left: 175, top: 57, width: 506, height: 1021 }, durationMs: 5040 },
    "07 鼓掌（双手鼓掌+点头）--使用上传.gif": { clip: { left: 89, top: 53, width: 625, height: 1025 }, durationMs: 5040 },
    "08 摔倒（互联网古早热梗 我倒）--使.gif": { clip: { left: 0, top: 52, width: 830, height: 1027 }, durationMs: 5040 },
    "09 钻出来（虚空传送门先出现 钻出）-.gif": { clip: { left: 0, top: 35, width: 817, height: 1044 }, durationMs: 5040 },
    "10 掉下来--使用上传的企鹅女孩图片作.gif": { clip: { left: 18, top: 0, width: 774, height: 1084 }, durationMs: 5040 },
    "11 挥手（有Hello的图标出现）--.gif": { clip: { left: 172, top: 55, width: 581, height: 1024 }, durationMs: 5040 },
    "12 Victory（耶 赢了 开心）-.gif": { clip: { left: 124, top: 52, width: 561, height: 1027 }, durationMs: 5040 },
    "13 失败（变黑、石化、裂开）--使用上.gif": { clip: { left: 204, top: 59, width: 407, height: 1019 }, durationMs: 5040 },
    "14 无语（流汗黄豆）--使用上传的企鹅.gif": { clip: { left: 184, top: 59, width: 442, height: 1019 }, durationMs: 5040 },
    "15 嘲笑（右手单指向 经典嘲笑）--使.gif": { clip: { left: 108, top: 57, width: 554, height: 1021 }, durationMs: 5040 },
    "16 比心（直接双手比心 有爱心标志）-.gif": { clip: { left: 125, top: 56, width: 621, height: 1026 }, durationMs: 5040 },
    "17 睡着（趴在地面 有zzz出现）--.gif": { clip: { left: 67, top: 56, width: 741, height: 1023 }, durationMs: 5040 },
    "18 惊恐（瞪大双眼 张大嘴）--使用上.gif": { clip: { left: 179, top: 39, width: 451, height: 1040 }, durationMs: 5040 },
    "19一直睡觉.gif": { clip: { left: 67, top: 180, width: 679, height: 866 }, durationMs: 2000 }
  };
  var GIF_TEST_URLS = Object.keys(GIF_GEOMETRIES).map(function (fileName) {
    return "/gifs/" + fileName;
  });
  var GIF_TEST_GAP_MS = 1000;

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

  function getGifFileName(url) {
    try {
      var path = new URL(url, window.location.href).pathname;
      return decodeURIComponent(path.substring(path.lastIndexOf("/") + 1));
    } catch (e) {
      var clean = String(url || "").split("?")[0].split("#")[0];
      return decodeURIComponent(clean.substring(clean.lastIndexOf("/") + 1));
    }
  }

  function getGifGeometry(url) {
    var fileName = getGifFileName(url);
    var override = GIF_GEOMETRIES[fileName] || {};
    return {
      body: override.body || DEFAULT_GIF_GEOMETRY.body,
      clip: override.clip || DEFAULT_GIF_GEOMETRY.clip,
      durationMs: override.durationMs || DEFAULT_GIF_GEOMETRY.durationMs,
      fileName: fileName
    };
  }

  function getCanvas() {
    return document.getElementById("canvas") || document.querySelector("canvas");
  }

  function getDeviceToScreen() {
    try {
      var delegate = window.LAppDelegate && window.LAppDelegate.getInstance && window.LAppDelegate.getInstance();
      var view = delegate && delegate.getView && delegate.getView();
      return view && view._deviceToScreen;
    } catch (e) {
      return null;
    }
  }

  function getLive2DModel() {
    try {
      var adapter = window.getLAppAdapter && window.getLAppAdapter();
      if (adapter && adapter.getModel) return adapter.getModel();
    } catch (e) {
      /* ignore */
    }

    try {
      var manager = window.LAppLive2DManager && window.LAppLive2DManager.getInstance && window.LAppLive2DManager.getInstance();
      if (manager && manager.getModel) return manager.getModel(0);
    } catch (e) {
      /* ignore */
    }

    return null;
  }

  function getVisibleModelRect(canvas) {
    var model = getLive2DModel();
    var d2s = getDeviceToScreen();
    var cubismModel = model && model._model;
    var modelMatrix = model && model._modelMatrix;
    if (!canvas || !cubismModel || !modelMatrix) {
      return null;
    }

    var deviceToCssScale = canvas.width / canvas.clientWidth || 1;
    var canInvertWithSdk = d2s && typeof d2s.invertTransformX === "function";
    var canvasDeviceWidth = canvas.width;
    var canvasDeviceHeight = canvas.height;

    function logicalToCss(logicalX, logicalY) {
      if (canInvertWithSdk) {
        return {
          x: d2s.invertTransformX(logicalX) / deviceToCssScale,
          y: d2s.invertTransformY(logicalY) / deviceToCssScale
        };
      }

      var screenSpan = canvasDeviceWidth > canvasDeviceHeight
        ? Math.abs((canvasDeviceWidth / canvasDeviceHeight) * 2)
        : 2;
      var basePixels = canvasDeviceWidth > canvasDeviceHeight
        ? canvasDeviceWidth
        : canvasDeviceHeight;

      return {
        x: (logicalX * basePixels / screenSpan + canvasDeviceWidth * 0.5) / deviceToCssScale,
        y: (-logicalY * basePixels / screenSpan + canvasDeviceHeight * 0.5) / deviceToCssScale
      };
    }

    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    var drawableCount = cubismModel.getDrawableCount ? cubismModel.getDrawableCount() : 0;

    for (var drawableIndex = 0; drawableIndex < drawableCount; drawableIndex += 1) {
      var isVisible = cubismModel.getDrawableDynamicFlagIsVisible && cubismModel.getDrawableDynamicFlagIsVisible(drawableIndex);
      var opacity = cubismModel.getDrawableOpacity ? cubismModel.getDrawableOpacity(drawableIndex) : 1;
      if (isVisible === false || opacity <= 0.01) continue;

      var vertices = cubismModel.getDrawableVertices && cubismModel.getDrawableVertices(drawableIndex);
      if (!vertices) continue;

      for (var vertexIndex = 0; vertexIndex < vertices.length; vertexIndex += 2) {
        var logicalX = modelMatrix.transformX(vertices[vertexIndex]);
        var logicalY = modelMatrix.transformY(vertices[vertexIndex + 1]);
        var cssPoint = logicalToCss(logicalX, logicalY);
        minX = Math.min(minX, cssPoint.x);
        minY = Math.min(minY, cssPoint.y);
        maxX = Math.max(maxX, cssPoint.x);
        maxY = Math.max(maxY, cssPoint.y);
      }
    }

    if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
    if (maxX <= minX || maxY <= minY) return null;

    var canvasRect = canvas.getBoundingClientRect();
    return {
      left: canvasRect.left + minX,
      top: canvasRect.top + minY,
      width: maxX - minX,
      height: maxY - minY
    };
  }

  function getFallbackModelRect(canvas) {
    var canvasRect = canvas ? canvas.getBoundingClientRect() : {
      left: 0,
      top: 0,
      width: window.innerWidth,
      height: window.innerHeight
    };
    var opts = window.__GIF_OVERLAY_OPTS__ || {};
    var height = opts.height || Math.round(canvasRect.height * (opts.heightRatio || 0.45));
    var width = height * (GIF_CANVAS.width / GIF_CANVAS.height) * (GIF_BODY_BOUNDS.width / GIF_CANVAS.width);
    return {
      left: canvasRect.left + (canvasRect.width - width) / 2,
      top: canvasRect.top + (canvasRect.height - height) / 2,
      width: width,
      height: height
    };
  }

  function createGifLayoutFromBodyRect(bodyRect, geometry) {
    var body = geometry.body;
    var clip = geometry.clip;
    var imageWidth = bodyRect.width * (GIF_CANVAS.width / body.width);
    var imageHeight = bodyRect.height * (GIF_CANVAS.height / body.height);
    var clipLeft = bodyRect.left - imageWidth * ((body.left - clip.left) / GIF_CANVAS.width);
    var clipTop = bodyRect.top - imageHeight * ((body.top - clip.top) / GIF_CANVAS.height);

    return {
      rect: {
        left: clipLeft,
        top: clipTop,
        width: imageWidth * (clip.width / GIF_CANVAS.width),
        height: imageHeight * (clip.height / GIF_CANVAS.height)
      },
      imageRect: {
        left: -imageWidth * (clip.left / GIF_CANVAS.width),
        top: -imageHeight * (clip.top / GIF_CANVAS.height),
        width: imageWidth,
        height: imageHeight
      }
    };
  }

  function playGif(url, durationMs) {
    if (playing || !url) return;
    playing = true;
    var resolved = resolveUrl(url);
    var geometry = getGifGeometry(resolved);

    var canvases = Array.prototype.slice.call(document.querySelectorAll("canvas"));
    var canvas = getCanvas();
    var bodyRect = getVisibleModelRect(canvas) || getFallbackModelRect(canvas);
    var opts = window.__GIF_OVERLAY_OPTS__ || {};
    var factor = Number(opts.sizeFactor || window.__GIF_SIZE_FACTOR__ || 1);
    bodyRect = {
      left: bodyRect.left + (bodyRect.width * (1 - factor)) / 2,
      top: bodyRect.top + (bodyRect.height * (1 - factor)) / 2,
      width: bodyRect.width * factor,
      height: bodyRect.height * factor
    };
    var layout = createGifLayoutFromBodyRect(bodyRect, geometry);
    console.log("[gif-overlay] model-aligned layout", {
      gif: geometry.fileName,
      bodyRect: bodyRect,
      overlayRect: layout.rect
    });

    var hidden = [];
    var canvasHidden = false;
    function restoreCanvases() {
      hidden.forEach(function (pair) {
        pair[0].style.visibility = pair[1] || "";
      });
      hidden = [];
      canvasHidden = false;
    }

    function hideCanvases() {
      if (canvasHidden) return;
      canvasHidden = true;
      canvases.forEach(function (c) {
        hidden.push([c, c.style.visibility]);
        c.style.visibility = "hidden";
      });
    }

    var box = document.createElement("div");
    box.id = OVERLAY_ID;
    box.style.cssText =
      "position:fixed;z-index:2147483647;pointer-events:none;background:transparent;" +
      "overflow:hidden;" +
      "left:" + layout.rect.left + "px;top:" + layout.rect.top + "px;" +
      "width:" + layout.rect.width + "px;height:" + layout.rect.height + "px;";

    var img = document.createElement("img");
    // Cache-bust so the GIF always restarts from frame 0.
    img.src = resolved + (resolved.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    img.style.cssText =
      "position:absolute;max-width:none;display:block;background:transparent;" +
      "left:" + layout.imageRect.left + "px;top:" + layout.imageRect.top + "px;" +
      "width:" + layout.imageRect.width + "px;height:" + layout.imageRect.height + "px;";
    img.onload = function () {
      requestAnimationFrame(hideCanvases);
    };
    img.onerror = function () {
      if (box.parentNode) box.parentNode.removeChild(box);
      playing = false;
    };
    box.appendChild(img);
    document.body.appendChild(box);

    setTimeout(function () {
      restoreCanvases();
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          if (box.parentNode) box.parentNode.removeChild(box);
        });
      });
      playing = false;
    }, durationMs || geometry.durationMs || DEFAULT_DURATION);
  }

  function playAllGifs() {
    var delay = 0;
    GIF_TEST_URLS.forEach(function (url) {
      var durationMs = getGifGeometry(url).durationMs;
      setTimeout(function () {
        playGif(url, durationMs);
      }, delay);
      delay += durationMs + GIF_TEST_GAP_MS;
    });
  }

  // Manual trigger (for testing / interaction): double-click anywhere plays all
  // action GIFs once with a 1s gap. Also serves as a diagnostic independent of
  // the AI path.
  document.addEventListener("dblclick", function () {
    console.log("[gif-overlay] dblclick -> playAllGifs");
    playAllGifs();
  });

  window.addEventListener("gif-overlay-play-all", playAllGifs);

  // Diagnostic hooks: call playAllGifs() or playStompGif() from the DevTools
  // console to test rendering directly.
  window.playAllGifs = playAllGifs;
  window.playStompGif = function () {
    playGif("/gifs/Fuming.gif", DEFAULT_DURATION);
  };
  console.log("[gif-overlay] loaded. Try playAllGifs() in the console.");

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
