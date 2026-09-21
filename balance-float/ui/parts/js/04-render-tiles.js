
  /* ---------- 渲染: 收起磁贴(前 4 站) ---------- */
  /* 只有一行磁贴(1~2 个)时不再让这一行拉满卡片: tileGrid 平时是 flex-1 +
     items-stretch, 两行时每行自然高, 一行时那行会被撑到整块剩余高度, 磁贴
     看着被拉大一圈。这里把网格改成按内容高、卡片按实际内容收高, 底部跟着
     贴上去; 两行与空列表维持原样。 */
  function fitCollapsed(n) {
    var card = document.querySelector("#collapsedWrap .ios-glass-card");
    var grid = $("tileGrid");
    if (!card || !grid) return;
    var oneRow = n === 1 || n === 2;
    grid.style.flex = oneRow ? "0 0 auto" : "";
    /* 卡片按内容收边: 写 auto, 高度就是头栏 + 一行磁贴, 底部自然贴着最后一行;
       两行和空列表清掉内联值, 回到 class 里的固定高度。这里刻意不量像素再写回:
       卡片带 height 过渡动画, 量到的经常是动画中间值, 写回去反而把卡片钉高,
       窗口跟着高出, 底部就露出一条黑边。窗口尺寸由 ResizeObserver 跟着卡片走。 */
    card.style.height = oneRow ? "auto" : "";
  }
  function renderTiles() {
    var grid = $("tileGrid");
    var stations = S.stations.slice(0, 4);
    if (!stations.length) {
      grid.innerHTML = '<div class="col-span-2 flex items-center justify-center text-[10px] text-muted">暂无监控账户 · 打开 configs 添加</div>';
      fitCollapsed(0);
      return;
    }
    grid.innerHTML = stations.map(function (st) {
      var bal, balCls = "text-[10px] text-accent font-semibold tracking-tight",
          dotCls = "w-[5px] h-[5px] rounded-full bg-ok animate-dot-glow shrink-0 inline-block",
          lat = "";
      if (st.ok) {
        bal = fmtMoney(st.remaining, st.unit);
        if (Number(st.remaining) < 0) balCls = "text-[10px] text-danger font-semibold tracking-tight";
        if (Number.isFinite(Number(st.latency_ms))) lat = st.latency_ms + "ms";
      } else {
        bal = "错误";
        balCls = "text-[10px] text-danger font-semibold tracking-tight";
        dotCls = "w-[5px] h-[5px] rounded-full bg-danger shrink-0 inline-block";
      }
      var title = (st.name || "") + " · " + (st.ok ? bal : String(st.error || "查询失败"));
      return '<div class="px-2 py-1 bg-white/60 hover:bg-white/90 border border-white/80 shadow-[0_1px_3px_rgba(0,0,0,0.03)] transition-all flex flex-col justify-between rounded-xl" title="' + esc(title) + '">' +
        '<div class="flex items-center justify-between"><span class="text-[11px] text-ink font-semibold truncate leading-none">' + esc(st.name || "未命名") + '</span><span class="' + dotCls + '"></span></div>' +
        '<div class="flex items-center justify-between"><span class="' + balCls + '">' + esc(bal) + '</span>' +
        '<span class="font-mono text-[9px] text-ok font-medium">' + esc(lat) + '</span></div></div>';
    }).join("");
    fitCollapsed(stations.length);
  }
