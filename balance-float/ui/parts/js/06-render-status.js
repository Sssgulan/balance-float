
  /* ---------- 渲染: 徽章 / 指示灯 / 底部状态胶囊 ---------- */
  var PILL = {
    ok: "flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 shadow-xs select-none",
    err: "flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-danger/10 border border-danger/25 shadow-xs select-none",
    idle: "flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/[0.04] border border-black/[0.06] shadow-xs select-none"
  };
  var PILL_DOT = {
    ok: "w-1.5 h-1.5 rounded-full bg-ok animate-indicator-breathe inline-block shrink-0",
    err: "w-1.5 h-1.5 rounded-full bg-danger inline-block shrink-0",
    idle: "w-1.5 h-1.5 rounded-full bg-faint inline-block shrink-0"
  };
  var PILL_TXT = {
    ok: "font-label-sm text-[10px] text-okText font-semibold tracking-tight leading-none",
    err: "font-label-sm text-[10px] text-danger font-semibold tracking-tight leading-none",
    idle: "font-label-sm text-[10px] text-ink2 font-semibold tracking-tight leading-none"
  };
  function applyStatus() {
    var stations = S.stations || [];
    var okCount = stations.filter(function (s) { return s && s.ok; }).length;
    $("activeText").textContent = okCount + " 活跃";
    var state0 = (!stations.length) ? "idle" : (okCount === 0 ? "err" : "ok");
    var hdrBase = "w-1.5 h-1.5 rounded-full inline-block shrink-0 ";
    var hdrCls = state0 === "ok" ? hdrBase + "bg-ok animate-binary-blink-2s shadow-[0_0_4px_@shadow.okGlow]"
               : state0 === "err" ? hdrBase + "bg-danger shadow-[0_0_4px_@shadow.dangerGlow]"
               : hdrBase + "bg-faint";
    $("collapseDot").className = hdrCls;
    $("expandDot").className = hdrCls;
    var pill = $("statusPill"), text = $("statusText"), tr = S.traffic, k, msg;
    if (S.loading && !stations.length) { k = "idle"; msg = "正在连接"; }
    else if (!stations.length) { k = "idle"; msg = "无账户"; }
    else if (okCount === stations.length) {
      k = "ok";
      if (tr && tr.available && Number.isFinite(Number(tr.cost_usd))) {
        msg = "今日 $" + Number(tr.cost_usd).toFixed(2) + " · " + (tr.requests || 0) + "次";
      } else {
        msg = S.lastUpdated ? "更新 " + S.lastUpdated : "全部正常";
      }
    }
    else if (okCount === 0) { k = "err"; msg = "全部异常"; }
    else { k = "ok"; msg = okCount + "/" + stations.length + " 正常"; }
    pill.className = PILL[k]; $("statusDot").className = PILL_DOT[k];
    text.className = PILL_TXT[k]; text.textContent = msg;
  }
  function render() {
    if (MODE !== "rt") return;
    renderTiles(); if (dragIdx < 0) renderRows(); applyStatus(); reportSize();
  }
