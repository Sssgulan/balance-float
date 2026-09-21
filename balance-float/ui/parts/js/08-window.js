
  /* ---------- 已接后台: 状态切换与窗口控制 ---------- */
  function setExpanded(on) {
    S.expanded = !!on;
    document.body.classList.toggle("is-expanded", S.expanded);
    document.body.classList.toggle("is-collapsed", !S.expanded);
    reportSize();
  }
  function doRefresh() {
    var api = bridge();
    if (api && typeof api.refresh === "function") { try { api.refresh(); } catch (e) {} }
    fetchState();
    setTimeout(fetchState, 2500);
    setTimeout(fetchState, 6000);
  }
  function onBridge(fn) {
    return function () {
      var api = bridge();
      if (api && typeof api[fn] === "function") { try { api[fn](); } catch (e) {} }
    };
  }
  function bindChrome() {
    $("btnCExpand").addEventListener("click", function () { setExpanded(true); });
    $("btnECollapse").addEventListener("click", function () { setExpanded(false); });
    $("btnCRefresh").addEventListener("click", doRefresh);
    $("btnERefresh").addEventListener("click", doRefresh);
    $("btnCMin").addEventListener("click", onBridge("minimize"));
    $("btnEMin").addEventListener("click", onBridge("minimize"));
    $("btnCClose").addEventListener("click", onBridge("close"));
    $("btnEClose").addEventListener("click", onBridge("close"));
    bindDragBars();
    bindRowDrag();
  }
  function bindDragBars() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-drag]"), function (bar) {
      bar.addEventListener("mousedown", function (e) {
        if (e.button !== 0 || e.target.closest("button")) return;
        whenBridge(800).then(function (api) {
          if (!api || typeof api.get_pos !== "function" || typeof api.move_to !== "function") return;
          api.get_pos().then(function (start) {
            var sx = e.screenX, sy = e.screenY;
            var ox = (start && start.x) || 0, oy = (start && start.y) || 0;
            function move(ev) { api.move_to(ox + (ev.screenX - sx), oy + (ev.screenY - sy)); }
            function up() {
              window.removeEventListener("mousemove", move);
              window.removeEventListener("mouseup", up);
            }
            window.addEventListener("mousemove", move);
            window.addEventListener("mouseup", up);
          });
        });
      });
    });
  }
  function bindResize() {
    if (typeof ResizeObserver !== "undefined") {
      var ro = new ResizeObserver(function () { reportSize(); });
      /* 观察卡片本身: 上报的就是它, 盯包裹层会漏掉 Tailwind 异步生效后的宽度变化 */
      ["collapsedWrap", "expandedWrap", "pageWrap"].forEach(function (id) {
        var wrap = $(id);
        if (wrap) ro.observe(wrap.querySelector(".ios-glass-card") || wrap);
      });
    } else {
      window.addEventListener("resize", reportSize);
    }
  }
