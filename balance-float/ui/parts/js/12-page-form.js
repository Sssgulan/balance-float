
  /* ---------- 表单态 ---------- */
  function fieldCard(k, value, optional) {
    var f = FIELDS[k], id = fid(k), val = value == null ? "" : String(value);
    var per = (f.per && f.per[tabOf()]) || {};   /* 页签级改写: 同一个 key 在不同页签可以换标题/提示 */
    var title = per.label || f.label;
    var label = '<span class="flex items-center gap-1"><span class="material-symbols-outlined text-[12px]" style="color:' + f.color + '">' + f.icon + '</span><span>' + title + '</span>' +
      (f.req && !optional ? '<span class="text-danger">*</span>' : '') + '</span>';
    var hintTxt = per.hint != null ? per.hint : f.hint;
    var hint = hintTxt ? '<span class="text-[9px] text-muted truncate max-w-[150px]">' + hintTxt + '</span>' : '';
    var body;
    if (f.step) {
      body = '<div class="flex items-center justify-between mt-0.5">' +
        '<button type="button" class="w-5 h-5 rounded-full bg-black/[0.04] hover:bg-black/[0.08] active:scale-90 flex items-center justify-center text-ink font-bold text-[12px] leading-none transition-all" data-step="-1" data-for="' + id + '">\u2212</button>' +
        '<input id="' + id + '" class="w-16 bg-transparent border-0 p-0 text-center font-mono text-[12px] font-bold text-ink focus:ring-0" type="number" min="' + (f.min || 1) + '" value="' + esc(val) + '" placeholder="' + (f.ph || "") + '">' +
        '<button type="button" class="w-5 h-5 rounded-full bg-black/[0.04] hover:bg-black/[0.08] active:scale-90 flex items-center justify-center text-ink font-bold text-[12px] leading-none transition-all" data-step="1" data-for="' + id + '">+</button></div>';
    } else {
      body = '<input id="' + id + '" autocomplete="off" spellcheck="false" class="w-full bg-transparent border-0 border-b border-black/[0.08] focus:border-accent focus:ring-0 p-0 pb-0.5 ' +
        (f.mono ? 'font-mono ' : '') + 'text-[12px] text-ink" type="' + (f.num ? "number" : "text") + '" value="' + esc(val) + '" placeholder="' + (f.ph || "") + '"></div>';
    }
    return '<div class="rounded-2xl p-2 bg-white/70 border border-white/90 shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col gap-1">' +
      '<label class="text-[10px] font-semibold text-muted flex items-center justify-between gap-1" for="' + id + '">' + label + hint + '</label>' + body + '</div>';
  }
  function formKeys() {
    var fm = FORMS[tabOf()] || FORMS.newapi;
    return fm.fields.concat(fm.extras || []).filter(function (k) { return fm.fields.indexOf(k) >= 0 || fm.extras.indexOf(k) >= 0; });
  }
  function openForm(acc, type) {
    var fm = FORMS[tabOf()] || FORMS.newapi;
    cur = { id: (acc && acc.id) || "", type: (acc && acc.type) || type || fm.types[0], raw: acc || {}, tab: tabOf() };
    pageMode = "form";
    if (OFFICIAL[cur.type] && !cur.id) cur.raw = { name: OFFICIAL[cur.type].name };
    if (cur.type === "ocx" && !cur.id) cur.raw = { name: "OpenCodex" };   /* OCX 手填: 名称给个默认 */   /* 官方块: 名称跟着选中项预填 */
    $("pageSection").textContent = "\u51ed\u8bc1\u914d\u7f6e";
    $("pageHint").textContent = "\u7559\u7a7a\u5219\u81ea\u52a8\u4f7f\u7528\u4f9b\u5e94\u5546\u914d\u7f6e";
    var raw = cur.raw || {};
    var extras = fm.extras || [];
    if (tabOf() === "generic") {
      $("pageHint").textContent = "整块 JSON 交给后端, 字段名以后端为准";
      $("pageFields").innerHTML = blobCard("pgBlob");
      $("pgBlob").value = blobText(raw);
      $("pageExtras").innerHTML = "";
      el_show("pageList", false); el_show("pageForm", true); el_show("pageExtras", false);
    } else {
      var opt = fm.opt || [];   /* 该页签里的可选字段: 有值就填, 留空不拦 */
      $("pageFields").innerHTML = fm.fields.map(function (k) { return fieldCard(k, raw[k], opt.indexOf(k) >= 0); }).join("");
      $("pageExtras").innerHTML = extras.map(function (k) { return fieldCard(k, raw[k] == null ? (k === "divisor" ? "500000" : k === "unit" ? "CNY" : "") : raw[k]); }).join("");
      el_show("pageList", false); el_show("pageForm", true); el_show("pageExtras", extras.length > 0);
    }
    $("pageTitle").textContent = (cur.id ? "\u7f16\u8f91" : "\u65b0\u589e") + " " + (TYPE_LABEL[cur.type] || cur.type);
    showMsg("", true);
    paintBtns([
      { id: "pgBack2", icon: "arrow_back", label: "\u8fd4\u56de", fn: backToList },
      { id: "pgTest", icon: "network_check", label: "\u6d4b\u8bd5\u8fde\u63a5", fn: function () { submitAcc(true); } },
      { id: "pgSave", icon: "check_circle", label: "\u4fdd\u5b58\u5e76\u542f\u7528", primary: true, fn: function () { submitAcc(false); } }
    ]);
    bindSteps();
    fitPage();
  }
  function bindSteps() {
    Array.prototype.forEach.call(document.querySelectorAll("#pageForm [data-step]"), function (b) {
      b.addEventListener("click", function () {
        var el = $(b.getAttribute("data-for")); if (!el) return;
        var v = parseInt(el.value, 10); if (!isFinite(v)) v = 10;
        el.value = Math.max(1, v + parseInt(b.getAttribute("data-step"), 10));
      });
    });
  }
  function readForm() {
    if (pageMode === "form" && cur && cur.model) return {};   /* 模型清单: 字段直接落后端 json, 不走账户 */
    if (tabOf() === "generic") return parseBlob(($("pgBlob") || {}).value);   /* 自定义: 整块 JSON */
    var v = {};
    formKeys().forEach(function (k) { var el = $(fid(k)); if (el) v[k] = String(el.value == null ? "" : el.value).trim(); });
    return v;
  }
  function buildPayload() {
    var out = {}, raw = cur.raw || {};
    for (var k in raw) { if (k !== "file") out[k] = raw[k]; }
    out.type = cur.type;
    if (cur.id) out.id = cur.id;
    var v = readForm();
    for (var k2 in v) {
      if (v[k2] === "") {
        if (FIELDS[k2] && FIELDS[k2].secret) continue;   /* 掩码/留空 = 未改, 后端回填库里原值 */
        if (k2 === "timeout" || k2 === "divisor" || k2 === "unit") { delete out[k2]; continue; }
      }
      out[k2] = v[k2];
    }
    return out;
  }
  function submitAcc(testOnly) {
    var payload = buildPayload();
    if (testOnly) {
      showMsg("\u6b63\u5728\u6d4b\u8bd5\u2026", true);
      api("account/test", { account: payload }, true).then(function (r) {
        if (r && r.ok) { showMsg("\u8fde\u63a5\u6b63\u5e38" + (r.remaining == null ? "" : " \u00b7 \u4f59\u989d " + r.remaining + (r.unit || "")), true); }
        else { showMsg("\u5931\u8d25: " + ((r && r.error) || "\u672a\u77e5\u9519\u8bef"), false); }
      });
      return;
    }
    api("account/save", { account: payload }, true).then(function (r) {
      if (!r || !r.ok) { showMsg("\u4fdd\u5b58\u5931\u8d25: " + ((r && r.error) || "\u672a\u77e5\u9519\u8bef"), false); return; }
      backToList();
      showMsg((r.action === "updated" ? "\u5df2\u66f4\u65b0" : "\u5df2\u65b0\u589e") + " \u00b7 " + (payload.name || ""), true);
      loadAccts();
      setTimeout(fetchState, 300);
    });
  }
  /* 列表态批量删除: 与展开页同一套交互(点页脚按钮进入 -> 逐行勾选 -> 确认), 不再弹系统确认框 */
  function paintWipe() {
    /* 外形与显隐都由页脚渲染负责, 这里只同步标题 */
    var b = $("pageWipe"); if (!b) return;
    b.title = delMode ? "\u5220\u9664\u5df2\u9009" : "\u4e00\u952e\u5220\u9664";
    if (pageMode !== "list") b.style.display = "none";
  }
  function setPageDel(on) {
    delMode = !!on;
    if (!delMode) sel = {};
    document.body.classList.toggle("is-deleting", delMode);
    renderList();
  }
  function wipeOff() { setPageDel(false); }
  /* 页脚上的"一键删除": 与展开页的减号同一套交互, 列表滚动不影响它 */
  function wipeBtn(compact) {
    return '<button id="pageWipe" class="' + (compact ? "w-9 shrink-0" : "flex-1") + ' py-1.5 rounded-xl border border-black/[0.10] bg-white/75 hover:bg-dangerWash hover:border-danger/40 text-ink2 hover:text-danger active:scale-[0.98] text-[11px] font-semibold transition-all flex items-center justify-center gap-1" title="一键删除">' +
      '<span class="material-symbols-outlined text-[14px]">delete_sweep</span></button>';
  }
  function togglePick(id) {
    if (!id) return;
    delMode = true;   /* 直接点圆圈也进删除模式 */
    sel[id] = !sel[id];
    document.body.classList.add("is-deleting");
    renderList();
  }
  function confirmDelSel() {
    var ids = Object.keys(sel).filter(function (k) { return sel[k]; });
    if (!ids.length) { showMsg("\u5148\u70b9\u884c尾\u5706\u5708\u9009中\u8981\u5220\u7684\u8d26\u6237", false); return; }
    showMsg("\u6b63\u5728\u5220\u9664 " + ids.length + " \u4e2a\u2026", true);
    /* 一次请求删一批: 后端在同一个临界区里删完再落盘, 并发多条会互相覆盖 */
    api("account/delete", { ids: ids }, true).then(function (r) {
      var n = 0;
      if (r && r.results) { Object.keys(r.results).forEach(function (k) { if (r.results[k].ok) n++; }); }
      wipeOff();
      showMsg("\u5df2\u5220\u9664 " + n + (n < ids.length ? " \u00b7 \u5931\u8d25 " + (ids.length - n) : ""), n === ids.length);
      loadAccts(); setTimeout(fetchState, 300);
    });
  }
  /* 隐藏区: 头点一下开合; 项上点"展示"先撤销后端隐藏标记, 再点名把它拉回列表。
     顺序不能颠倒: import 不带 provider_ids 时后端仍按隐藏名单跳过。 */
  function hidToggle() { hidOpen = !hidOpen; renderList(); fitPage(); }
  function hidClick(pid) {
    if (!pid) return;
    showMsg("正在展示…", true);
    api("ccsw/update", { provider_id: pid, ignored: false }, true).then(function (r) {
      if (!r || !r.ok) { showMsg("操作失败: " + ((r && r.error) || "未知错误"), false); return null; }
      return api("ccsw/import", { provider_ids: [pid] }, true);
    }).then(function () { return loadAccts(); })
      .then(function () { showMsg("已展示", true); setTimeout(fetchState, 300); })
      .catch(function () { showMsg("操作失败", false); });
  }
  /* 导入刷新: 直接对接已有接口  /* 导入刷新: 直接对接已有接口, 先扫一遍再导, 结果写页脚状态行 */
  function doImport(kind) {
    if (kind === "ccsw") {
      showMsg("正在扫描 CC-Switch…", true);
      fetch("/api/ccsw/scan", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (s) {
          if (!s || !s.available) { showMsg("未找到 cc-switch.db, 请先开 CC Switch", false); return null; }
          return api("ccsw/import", {}, true).then(function (r) {
            if (!r || !r.ok) { showMsg("导入失败: " + ((r && r.error) || "未知错误"), false); return; }
            /* 什么都没变时得说清原因: 被删过的节点按删除名单不再自动回来,
               只说"已导入 0"看着就像按钮没生效 */
            var msg;
            if (!r.imported && !r.updated) {
              var ig = (r.ignored || []).length;
              msg = "没有新节点" + (ig ? " · " + ig + " 个在删除名单里, 不会自动恢复" : " · 源里也没有可导入项");
            } else {
              msg = "已导入 " + r.imported + " · 更新 " + r.updated;
            }
            showMsg(msg, true);
            loadAccts(); setTimeout(fetchState, 300);
          });
        })
        .catch(function () { showMsg("CC-Switch 扫描失败", false); });
      return;
    }
    showMsg("正在扫描 OpenCodex…", true);
    api("ocx/import", { probe: false }, true).then(function (r) {
      if (!r || !r.ok) { showMsg("导入失败: " + ((r && r.error) || "未检测到配置"), false); return; }
      showMsg((r.action === "updated" ? "已更新 " : "已导入 ") + (r.base_url || "") + " · " + (r.count || 0) + " 节点", true);
      loadAccts(); setTimeout(fetchState, 300);
    });
  }
  /* 右上角返回: 列表态退回展开态(不是收起态); 表单/设置态只退一层回列表, 与底部"返回"同义 */
  function pageBack() {
    if (pageMode === "form" || pageMode === "settings") { backToList(); return; }
    setPage(false);
    setExpanded(true);
  }
  function backToList() {
    pageMode = "list"; cur = null;
    delMode = false; sel = {};
    el_show("pageList", true); el_show("pageForm", false); el_show("pageExtras", false);
    $("pageTitle").textContent = part().title;
    showMsg("", true);
    renderList();
    fitPage();
  }
