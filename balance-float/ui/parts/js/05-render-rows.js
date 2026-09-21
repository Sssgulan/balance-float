
  /* ---------- 渲染: 展开行列表 ---------- */
  function renderRows() {
    var list = $("rowList");
    if (!S.stations.length) {
      list.innerHTML = '<div class="flex-1 flex items-center justify-center text-[10px] text-muted">暂无监控账户 · 点击底部“添加”配置节点</div>';
      return;
    }
    list.innerHTML = S.stations.map(function (st, i) {
      var acc = S.accounts[i] || {};
      var a = accentOf(acc, i);
      var rowId = acc.id || "";
      var picked = !!(delMode && rowId && sel[rowId]);
      /* 删除模式下把拖拽手柄换成勾选框: 位置不变, 不改行高 */
      var grip = delMode
        ? '<span class="w-4 h-4 rounded-full border flex items-center justify-center shrink-0 transition-all ' + (picked ? 'bg-danger border-danger text-white' : 'bg-white/70 border-black/15 text-transparent') + '"><span class="material-symbols-outlined text-[11px] leading-none">check</span></span>'
        : '<div class="flex items-center opacity-40 group-hover/row:opacity-100 transition-opacity"><span data-grip class="material-symbols-outlined text-[13px] text-muted ' + a.grip + ' cursor-grab active:cursor-grabbing leading-none" title="拖动排序">drag_indicator</span></div>';
      var neg = st.ok && Number(st.remaining) < 0;
      var bal = st.ok ? fmtMoney(st.remaining, st.unit) : String(st.error || "查询失败").slice(0, 18);
      var balCls = "font-label-md text-label-md font-bold tracking-tight " + (st.ok && !neg ? "text-ink" : "text-danger");
      var tr = trafficOf(st), detail;
      if (tr && Number.isFinite(Number(tr.cost_usd))) {
        detail = "今日 $" + Number(tr.cost_usd).toFixed(2) + ' <span class="text-muted">(' + fmtTok(tr.tokens) + ')</span>';
      } else if (st.ok && Number.isFinite(Number(st.used))) {
        detail = "已用 " + fmtMoney(st.used, st.unit);
      } else if (st.ok && st.updated) {
        detail = "更新 " + st.updated;
      } else {
        detail = "查询失败";
      }
      var bar = (st.ok && !neg)
        ? '<div class="h-full bg-gradient-to-r ' + a.grad + ' rounded-full" style="width: ' + pctOf(st) + '%;"></div>'
        : '<div class="h-full bg-gradient-to-r from-danger to-dangerLight rounded-full opacity-40" style="width: 100%;"></div>';
      var rowStyle = (i === dragIdx ? 'box-shadow:0 0 0 2px rgba(0,113,227,0.45),0 4px 12px rgba(0,113,227,0.16);' : '')
        + (picked ? 'box-shadow:inset 0 0 0 1.5px rgba(255,59,48,0.5);background:rgba(255,59,48,0.06);' : '');
      return '<div class="group/row rounded-xl px-2.5 bg-white/65 hover:bg-white/95 border border-white/80 ' + a.hover + ' shadow-[0_1px_3px_rgba(0,0,0,0.03)] transition-all duration-150 flex flex-col shrink-0 cursor-pointer py-0.5 gap-px" style="' + rowStyle + '" data-row="' + i + '">' +
        '<div class="flex items-center justify-between"><div class="flex items-center gap-1.5">' +
        '<div class="w-5 h-5 rounded-lg ' + a.chip + ' flex items-center justify-center shadow-xs"><span class="material-symbols-outlined text-[13px]">' + rowIconOf(acc, st.name, a) + '</span></div>' +
        '<span class="font-body-sm text-body-sm text-ink font-semibold leading-tight">' + esc(st.name || "未命名") + '</span></div>' +
        '<div class="flex items-center gap-1.5"><span class="' + balCls + '">' + esc(bal) + '</span>' +
        grip + '</div></div>' +
        '<div class="flex items-center justify-between text-ink2 font-label-sm text-label-sm pl-6.5"><div class="flex items-center gap-1 truncate">' +
        '<span class="text-muted">' + esc(typeLabelOf(st, i)) + '</span><span class="text-black/20">•</span><span>' + detail + '</span></div>' +
        '<div class="flex items-center gap-1 shrink-0 ml-1"><div class="flex items-center opacity-0 group-hover/row:opacity-100 transition-opacity -mr-0.5">' +
        '<button class="w-3.5 h-3.5 rounded hover:bg-black/[0.05] text-muted hover:text-ink flex items-center justify-center transition-colors" title="上移" data-op="up"><span class="material-symbols-outlined text-[11px] leading-none">keyboard_arrow_up</span></button>' +
        '<button class="w-3.5 h-3.5 rounded hover:bg-black/[0.05] text-muted hover:text-ink flex items-center justify-center transition-colors" title="下移" data-op="down"><span class="material-symbols-outlined text-[11px] leading-none">keyboard_arrow_down</span></button>' +
        '</div></div></div>' +
        '<div class="w-full h-[2.5px] rounded-full bg-black/[0.05] overflow-hidden">' + bar + '</div></div>';
    }).join("");
  }
