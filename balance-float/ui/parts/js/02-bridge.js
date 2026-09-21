
  /* ---------- pywebview 桥 ---------- */
  function bridge() { return (window.pywebview && window.pywebview.api) || null; }
  function whenBridge(timeoutMs) {
    return new Promise(function (resolve) {
      var t0 = Date.now();
      (function poll() {
        var api = bridge();
        if (api) return resolve(api);
        if (Date.now() - t0 > (timeoutMs || 3000)) return resolve(null);
        setTimeout(poll, 40);
      })();
    });
  }
  /* 接入页也是窗口状态之一: 尺寸上报取它, 否则窗口会停在收起态的 212x114 */
  function activeWrap() { return $(S.page ? "pageWrap" : (S.expanded ? "expandedWrap" : "collapsedWrap")); }
  function reportSize() {
    if (MODE !== "rt") return;
    var api = bridge(); var wrap = activeWrap();
    /* 只量真实卡片: 包裹层是块级元素, 宽度会撑满视口, 上报它等于把窗口宽度自引用成当前视口宽 */
    var el = (wrap && wrap.querySelector(".ios-glass-card")) || wrap;
    if (!api || !el || !el.offsetWidth || typeof api.resize !== "function") return;
    /* 连同卡片的圆角半径一起上报: 原生层据此把窗口裁剪成卡片本身的圆角形状 */
    var radius = 0;
    try { radius = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0; } catch (e) {}
    api.resize(Math.ceil(el.offsetWidth), Math.ceil(el.offsetHeight), radius);
  }
