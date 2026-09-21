
  /* ---------- 启动 ---------- */
  var readySent = false;
  function notifyReady() {
    var api = bridge();
    if (!api) return;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (readySent) return;
        readySent = true;
        if (typeof api.ready === "function") api.ready();
        reportSize();
      });
    });
  }
  function boot() {
    whenBridge(2500).then(function (api) {
      var forced = /(?:^|[?&])rt=1(?:&|$)/.test(location.search);
      if (!api && !forced) { MODE = "preview"; document.body.classList.add("preview"); return; }
      MODE = "rt";
      document.body.classList.add("rt", "is-collapsed");
      if (forced) document.title = "rt(sim)";
      bindChrome();
      bindResize();
      bindPage();
      render();
      fetchState();
      setInterval(fetchState, 30000);
      notifyReady();
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
