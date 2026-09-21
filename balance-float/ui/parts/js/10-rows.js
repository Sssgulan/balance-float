
  /* ---------- 已接后台: 行排序 + 批量删除 ---------- */
  function idOrder() {
    return (S.accounts || []).map(function (a) { return a && a.id; }).filter(Boolean);
  }

  /* 顺序一变, /api/state 里的 accounts 与 stations 会有短暂的不同步(后台还没跑完一轮);
     两边都带 id 时按 id 对齐, 顺序以 accounts 为准, 避免列表被旧快照顶回去。 */
  function pairStations() {
    var accs = S.accounts || [], sts = S.stations || [];
    if (!accs.length || !sts.length) return;
    if (!accs.every(function (a) { return a && a.id; })) return;
    var byId = {};
    sts.forEach(function (st) { if (st && st.id && !byId[st.id]) byId[st.id] = st; });
    if (!Object.keys(byId).length) return;
    var out = accs.map(function (a) { return byId[a.id]; });
    if (out.some(function (x) { return !x; })) return;
    if (out.length === sts.length) S.stations = out;
  }
  /* 后端注入的进程级令牌：写操作 POST 必须带在 X-Api-Token 头里（meta 由本机服务返回页面时注入） */
  function apiToken() {
    var m = document.querySelector('meta[name="api-token"]');
    return (m && m.getAttribute("content")) || "";
  }
  function api(path, body, quiet) {
    var p = fetch("/api/" + path, { method: "POST",
      headers: { "Content-Type": "application/json", "X-Api-Token": apiToken() },
      body: JSON.stringify(body || {}) })
      .then(function (res) { return res.json(); })
      .catch(function () { return null; });
    if (!quiet) p.then(function () { setTimeout(fetchState, 400); });
    return p;
  }
  /* 按用户给定的顺序重排本地列表并落盘; 不按名称/余额做任何排序 */
  function saveOrder(ids) {
    var by = {}, stBy = {};
    S.accounts.forEach(function (a, k) { if (a && a.id) { by[a.id] = a; stBy[a.id] = S.stations[k]; } });
    S.accounts = ids.map(function (id) { return by[id]; }).filter(Boolean);
    S.stations = ids.map(function (id) { return stBy[id]; }).filter(Boolean);
    renderRows();
    api("account/reorder", { ids: ids });
  }
  function dropRow(target) {
    var src = dragIdx;
    dragIdx = -1;
    if (src < 0 || target < 0 || src === target || !dragMoved) { dragMoved = false; renderRows(); return; }
    dragMoved = false;
    var ids = idOrder();
    ids.splice(target, 0, ids.splice(src, 1)[0]);
    saveOrder(ids);
  }
  function setDelMode(on) {
    delMode = !!on;
    if (!delMode) sel = {};
    document.body.classList.toggle("is-deleting", delMode);
    $("btnDel").style.display = delMode ? "none" : "";
    $("btnOk").style.display = delMode ? "" : "none";
    renderRows();
  }
  function confirmDel() {
    var ids = Object.keys(sel).filter(function (k) { return sel[k]; });
    setDelMode(false);
    if (!ids.length) return;
    ids.forEach(function (id) { dead[id] = 1; API_STUBS.deleteAccount(id); });
    dead2drop();
    render();
    setTimeout(fetchState, 400);
  }
  /* 已删的行先从本地拿掉(后台还在拉数据时不会闪回来) */
  function dead2drop() {
    if (!Object.keys(dead).length) return;
    var keep = S.accounts.map(function (a, i) {
      return (a && a.id && dead[a.id]) ? -1 : i;
    }).filter(function (i) { return i >= 0; });
    S.accounts = keep.map(function (i) { return S.accounts[i]; });
    S.stations = keep.map(function (i) { return S.stations[i]; }).filter(Boolean);
  }
  function dropDead(live) {
    if (!Object.keys(dead).length) return;
    var on = {};
    (live || []).forEach(function (id) { if (id) on[id] = 1; });
    var pending = Object.keys(dead).some(function (id) { return on[id]; });
    if (pending) dead2drop();
    dead = {};
  }
  /* 拖拽用抓手按钮不用 HTML5 DnD: pywebview 内拖拽会被系统拖放拦截 */
  function bindRowDrag() {
    var list = $("rowList"), src = -1, over = -1;
    function mark() {
      Array.prototype.forEach.call(list.querySelectorAll("[data-row]"), function (el) {
        var on = Number(el.getAttribute("data-row")) === src || Number(el.getAttribute("data-row")) === over;
        el.style.boxShadow = on ? "0 0 0 2px rgba(0,113,227,0.45),0 4px 12px rgba(0,113,227,0.16)" : "";
      });
    }
    list.addEventListener("mousedown", function (e) {
      suppressClick = false;
      if (delMode || e.button !== 0) return;
      var grip = e.target.closest("[data-grip]"), row = e.target.closest("[data-row]");
      if (!grip || !row) return;
      e.preventDefault();
      src = Number(row.getAttribute("data-row")); over = src;
      API_STUBS.startRowDrag(src);
      mark();
      function move(ev) {
        var el = document.elementFromPoint(ev.clientX, ev.clientY);
        var r = el && el.closest ? el.closest("[data-row]") : null;
        if (!r) return;
        var k = Number(r.getAttribute("data-row"));
        if (k !== over) { over = k; if (k !== src) dragMoved = true; mark(); }
      }
      function up() {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
        suppressClick = true;
        dropRow(over);
        /* 松手点落在行外时 click 不会来, 兜底清掉, 免得吞掉下一次点击 */
        setTimeout(function () { suppressClick = false; }, 300);
      }
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
  }

  /* ================= 接入页: 账户配置 =================
     底部"添加"从展开态进入这里。页签与模板一致; NewAPI 先做透, 其余类型按
     后端同一张字段表给出可用表单。窗口尺寸仍由卡片内容决定(reportSize)。 */
  var PARTS = {
    newapi:   { title: "NewAPI \u914d\u7f6e",   types: ["newapi"] },
    official: { title: "\u5b98\u65b9\u63a5\u53e3\u914d\u7f6e",  types: ["deepseek", "moonshot", "zhipu"] },
    generic:  { title: "\u81ea\u5b9a\u4e49\u63a5\u53e3\u914d\u7f6e", types: ["generic"] },
    ccsw:     { title: "CC-SW \u914d\u7f6e",    types: ["ccsw"] },
    ocx:      { title: "OCX \u914d\u7f6e",      types: ["ocx"] }
  };
  var TYPE_LABEL = { newapi: "NewAPI", deepseek: "\u5b98\u65b9\u76f4\u8fde", moonshot: "\u5b98\u65b9\u76f4\u8fde",
                     zhipu: "\u5b98\u65b9\u76f4\u8fde", generic: "\u81ea\u5b9a\u4e49", ccsw: "CC-SW", ocx: "OCX" };
  /* 官方直连常用服务商: 图标用品牌色方块 + 首字母, 不引第三方 logo 资源 */
  var OFFICIAL = {
    deepseek: { name: "DeepSeek", color: "@color.deepseek", mark: "D" },
    moonshot: { name: "Kimi",     color: "@color.ink", mark: "K" },
    zhipu:    { name: "GLM",      color: "@color.glmAlt", mark: "G" }
  };
  function brandIcon(t) {
    var b = OFFICIAL[t] || { color: "@color.muted", mark: "?" };
    return '<span class="w-5 h-5 rounded-lg flex items-center justify-center font-bold text-[10px] text-white shrink-0" style="background:' + b.color + '">' + b.mark + '</span>';
  }
  /* 自定义页签: 一个文本框装整块 JSON, 键名与后端一致, 认不出的字段原样透传 */
  function blobCard(id) {
    return '<div class="rounded-2xl p-2 bg-white/70 border border-white/90 shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col gap-1">' +
      '<label class="text-[10px] font-semibold text-muted flex items-center justify-between gap-1" for="' + id + '">' +
      '<span class="flex items-center gap-1"><span class="material-symbols-outlined text-[12px]" style="color:@color.iris">code</span><span>配置（JSON 文本）</span></span>' +
      '<span class="text-[9px] text-muted truncate max-w-[160px]">键名以后端为准, 多的字段原样带上</span></label>' +
      '<textarea id="' + id + '" spellcheck="false" autocomplete="off" class="w-full h-[136px] bg-transparent border-0 p-0 pb-0.5 font-mono text-[11px] text-ink focus:ring-0 resize-none leading-snug"></textarea></div>';
  }
  function blobText(raw) {
    var out = {}, keys = ["name", "url", "api_key", "timeout", "unit", "divisor", "headers", "json_paths"];
    keys.forEach(function (k) { if (raw && raw[k] != null && raw[k] !== "") out[k] = raw[k]; });
    return JSON.stringify(out, null, 2);
  }
  function parseBlob(text) {
    var t = String(text == null ? "" : text).trim();
    if (!t) return {};
    try {
      var o = JSON.parse(t);
      return (o && typeof o === "object" && !Array.isArray(o)) ? o : {};
    } catch (e) {}
    /* 不是严格 JSON 也认: 去掉大括号后按行/逗号拆 key: value, 方便从别处直接粘过来 */
    var out = {};
    t.replace(/^\{|\}$/g, "").split(/[\n,]/).forEach(function (line) {
      var m = /^\s*"?([A-Za-z_][\w-]*)"?\s*[:=]\s*"?(.*?)"?\s*$/.exec(line);
      if (m && m[1]) out[m[1]] = m[2];
    });
    return out;
  }
  /* 字段表跟后端的 REQUIRED_FIELDS / providers 取值口径一致, 不出现后端没有的字段 */
  var FIELDS = {
    name:         { label: "\u540d\u79f0",       icon: "badge",       color: "@color.azure", req: true, ph: "\u4f8b\u5982 Moniker" },
    base_url:     { label: "\u8bf7\u6c42\u5730\u5740",   icon: "link",        color: "@color.accent", req: true, mono: true, ph: "https://your-site.com", hint: "\u7ad9\u70b9\u6839\u5730\u5740\uff0c\u4e0d\u5e26 /v1", per: { ocx: { label: "服务器连接", hint: "OCX 代理地址，例 http://127.0.0.1:10100" } } },
    access_token: { label: "\u8bbf\u95ee\u4ee4\u724c",   icon: "key",         color: "@color.iris", req: true, secret: true, hint: "\u4e2a\u4eba\u5b89\u5168\u8bbe\u7f6e\u91cc\u83b7\u53d6" },
    api_key:      { label: "API Key",    icon: "key",         color: "@color.iris", req: true, secret: true, mono: true, per: { ocx: { hint: "OCX 的 API 密钥，可留空" } } },
    user_id:      { label: "\u7528\u6237 ID",    icon: "person",      color: "@color.azure", mono: true, hint: "\u975e sk \u4ee4\u724c\u5fc5\u586b" },
    url:          { label: "\u8bf7\u6c42\u5730\u5740",   icon: "link",        color: "@color.accent", req: true, mono: true, ph: "https://your-site.com/api/usage", hint: "\u5b8c\u6574\u7684\u4f59\u989d\u67e5\u8be2 URL" },
    provider_id:  { label: "Provider ID", icon: "fingerprint", color: "@color.iris", req: true, mono: true, hint: "CC-SW \u8282\u70b9\u6807\u8bc6" },
    timeout:      { label: "\u8d85\u65f6\uff08\u79d2\uff09", icon: "schedule",    color: "@color.flame", step: true, min: 1, ph: "10" },
    divisor:      { label: "\u6362\u7b97\u500d\u6570",   icon: "calculate",   color: "@color.azure", num: true, ph: "500000", hint: "quota \u5355\u4ef7\uff0c\u7ad9\u70b9\u7ea7\u5e38\u91cf" },
    unit:         { label: "\u8ba1\u4ef7\u5355\u4f4d",   icon: "sell",        color: "@color.grass", ph: "CNY / USD" }
  };
  var FORMS = {
    newapi:   { types: ["newapi"], fields: ["name", "base_url", "access_token", "user_id"], extras: ["timeout", "divisor", "unit"] },
    official: { types: ["deepseek", "moonshot", "zhipu"], fields: ["name", "api_key"] },   /* 只填密钥, 地址走后端默认 */
    generic:  { types: ["generic"], fields: [] },   /* 表单是整块 JSON 文本, 字段名与后端一致 */
    ccsw:     { types: ["ccsw"], fields: ["name", "provider_id", "base_url"] },
    ocx:      { types: ["ocx"], fields: ["name", "base_url", "api_key"], opt: ["api_key"] }   /* 服务器连接必填; API 密钥可留空 */
  };
  var pageMode = "";        /* "" | list | form | settings */
  var cur = null;           /* 表单态: {id, type, raw, tab} */
  var pageRows = [];        /* /api/accounts 快照 */
  var pgMinutes = 5, pgSeconds = 10;
  var pgHidden = [];       /* CC-SW 隐藏名单: 删过的节点都在这儿, 不是没了 */
  var hidOpen = false;     /* 隐藏区展开态 */

  function fid(k) { return "pgF_" + k; }
  function tabOf() { return S.tab || "newapi"; }
  function part() { return PARTS[tabOf()] || PARTS.newapi; }
  function activeCard() { var w = $("pageWrap"); return (w && w.querySelector(".ios-glass-card")) || w; }
  function showMsg(t, ok) {
    var el = $("pageMsg"); if (!el) return;
    el.className = "flex-1 min-w-0 text-[10px] font-semibold truncate " + (ok ? "text-okText" : "text-danger");
    el.textContent = t || "";
  }
  /* 接入页沿用模板配置弹窗的尺寸: 宽 360 (模板实测 360x423)。高度钉在 420 不随内容长高,
     列表/表单/设置三态共用一个窗口大小, 装不下的内容由体内滚动; 只有屏幕放不下时才收窄压低。
     尺寸与收起/展开态无关, 窗口跟着这张卡片走。 */
  function fitPage() {
    paintWipe();   /* 页脚的批量删除跟着列表态显隐 */
    var el = activeCard(); if (!el || !S.page) return;
    var scr = window.screen || {};
    var availW = Number(scr.availWidth) || 1280, availH = Number(scr.availHeight) || 800;
    el.style.width = Math.max(280, Math.min(@size.pageW, availW - 40)) + "px";
    el.style.height = Math.max(260, Math.min(@size.pageH, availH - 80)) + "px";
    reportSize();
  }
  function setPage(on, tab) {
    S.page = !!on;
    if (S.page) {
      if (tab) S.tab = tab;
      setExpanded(false);
      pageMode = "list";
      cur = null;
      delMode = false; sel = {};   /* 接入页的批量删除与展开页共用同一份选中态, 进出都要清干净 */
      document.body.classList.add("is-page");
      if ($("pageFoot")) $("pageFoot").innerHTML = "";   /* 先清旧页脚, 免得闪一下上一次的气泡 */
      el_show("pageList", true); el_show("pageForm", false); el_show("pageExtras", false);
      $("pageTitle").textContent = part().title;
      paintTabs();
      showMsg("", true);
      loadAccts();
      fitPage();
    } else {
      delMode = false; sel = {};
      document.body.classList.remove("is-page", "is-deleting");
    }
    reportSize();
  }
  /* 页脚固定在列表下方(滚动区之外): 收纳"导入刷新"气泡与"一键删除" */
  function footShow(el, on) {
    /* 收起时也要保留 shrink-0: 只写 hidden 会让外层 flex 列的子项被算进布局,
       卡片高度平白多出一截, 列表底部跟着浮起来 */
    el.className = (on ? "flex" : "hidden") + " items-center gap-1.5 shrink-0";
  }
  function el_show(id, on) {
    var el = $(id); if (!el) return;
    if (id === "pageList") {
      var f = $("pageFoot");
      if (f) footShow(f, on && !!f.innerHTML.trim());
    }
    if (id === "pageFoot") { footShow(el, on && !!el.innerHTML.trim()); return; }
    var base = id === "pageList" || id === "pageForm" ? "flex-1 min-h-0 overflow-y-auto " : "";
    el.className = base + (on ? "flex flex-col " : "hidden flex-col ") + (id === "pageForm" ? "gap-2.5" : id === "pageExtras" ? "gap-2 pb-0.5" : "gap-1");
  }
  function paintTabs() {
    var box = $("pageTabs"); if (!box) return;
    Array.prototype.forEach.call(box.querySelectorAll("[data-kind]"), function (b) {
      var on = b.getAttribute("data-kind") === tabOf();
      b.className = "flex-1 py-1 px-1 rounded-lg text-[11px] transition-all text-center whitespace-nowrap " +
        (on ? "bg-white shadow-[0_1px_3px_rgba(0,0,0,0.08)] font-semibold text-ink"
            : "hover:bg-white/50 font-medium text-ink2 hover:text-ink");
    });
  }
  function paintBtns(list) {
    $("pageBtns").innerHTML = list.map(function (b) {
      var cls = b.primary
        ? "bg-accent hover:bg-accentHover text-white shadow-[0_4px_12px_@shadow.accentGlow]"
        : "bg-white/75 hover:bg-white text-ink border border-black/[0.06] shadow-xs";
      return '<button id="' + b.id + '" class="py-1.5 px-2.5 rounded-xl active:scale-[0.98] text-[11px] font-semibold transition-all flex items-center justify-center gap-1 ' + cls + '">' +
        '<span class="material-symbols-outlined text-[13px]">' + b.icon + '</span><span>' + b.label + '</span></button>';
    }).join("");
    list.forEach(function (b) { var el = $(b.id); if (el) el.addEventListener("click", b.fn); });
  }
  function loadAccts() {
    scanGlyphs();
    loadModels();
    loadHidden();
    return fetch("/api/accounts", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) { pageRows = Array.isArray(d) ? d : []; if (pageMode === "list") renderList(); fitPage(); })
      .catch(function () { pageRows = []; if (pageMode === "list") renderList(); fitPage(); });
  }
  /* 删掉的 CC-SW 只是进了隐藏名单: 后端把名单跟 cc-switch 库里现存的节点对回来,
     列表里就能点"展示"把它放回上面那一堆 */
  function loadHidden() {
    return fetch("/api/ccsw/hidden", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) { pgHidden = (d && d.hidden) || []; if (pageMode === "list") renderList(); fitPage(); })
      .catch(function () { pgHidden = []; });
  }
