
  /* ---------- 列表态 ---------- */
  /* 列表里的"新增"入口: 官方选块之外的页签共用一份外形 */
  function addRow(types) {
    return types.map(function (t) {
      var full = types.length === 1;
      return '<button class="' + (full ? "w-full" : "flex-1") + ' py-1.5 rounded-xl border border-dashed border-black/[0.12] hover:border-accent/60 hover:bg-blue-50/40 text-[11px] font-semibold text-ink2 hover:text-accent transition-all flex items-center justify-center gap-1" data-add="' + t + '">' +
        '<span class="material-symbols-outlined text-[14px]">add</span><span>新增 ' + esc(TYPE_LABEL[t] || t) + '</span></button>';
    }).join("");
  }
  function renderList() {
    var types = part().types;
    var rows = pageRows.filter(function (a) { return a && types.indexOf(a.type) >= 0; });
    var html = rows.map(function (a) {
      var picked = !!(delMode && a.id && sel[a.id]);
      var chip = a.enabled === false
        ? '<span class="px-1 py-0.5 rounded-full bg-black/[0.05] text-[9px] text-ink2 font-semibold shrink-0">\u5df2\u505c\u7528</span>' : "";
      return '<div class="group/row rounded-xl px-2.5 bg-white/65 hover:bg-white/95 border border-white/80 shadow-[0_1px_3px_rgba(0,0,0,0.03)] transition-all flex items-center justify-between gap-1.5 py-1 cursor-pointer" data-acc="' + esc(a.id) + '"' + (picked ? ' style="box-shadow:inset 0 0 0 1.5px rgba(255,59,48,0.5);background:rgba(255,59,48,0.06);"' : '') + '>' +
        '<div class="flex items-center gap-1.5 min-w-0">' +
        '<div class="w-5 h-5 rounded-lg bg-blue-50/90 border border-blue-100/70 flex items-center justify-center text-accent shrink-0"><span class="material-symbols-outlined text-[13px]">cloud</span></div>' +
        '<div class="min-w-0"><div class="font-body-sm text-body-sm text-ink font-semibold leading-tight truncate">' + esc(a.name || "\u672a\u547d\u540d") + '</div>' +
        '<div class="font-label-sm text-label-sm text-muted truncate">' + esc(TYPE_LABEL[a.type] || a.type) + (a.base_url ? " \u00b7 " + esc(a.base_url) : "") + '</div></div></div>' +
        '<div class="flex items-center gap-1 shrink-0">' + chip +
        /* 勾选圈只在删除模式露脸, 与展开页一样: 先点下面的一键删除, 再逐行勾选 */
        (delMode ? '<span class="material-symbols-outlined text-[14px] ' + (picked ? "text-danger" : "text-muted") + ' cursor-pointer transition-colors" data-pick="' + esc(a.id) + '" title="\u9009\u4e2d\u5220\u9664">' + (picked ? "check_circle" : "radio_button_unchecked") + '</span>' : '') +
        '</div></div>';
    }).join("");
    var hidden = (tabOf() === "ccsw") ? hiddenGroup() : "";
    var imp = (tabOf() === "ccsw" || tabOf() === "ocx");   /* 页脚的"导入刷新"气泡: CC-SW 与 OCX */
    var adds = "", grp = "", inline = "";
    if (tabOf() === "official") {
      adds = '<div class="flex items-center gap-1.5 shrink-0 pb-0.5">' + Object.keys(OFFICIAL).map(function (t) {
        return '<button class="flex-1 py-1 px-1 rounded-xl border border-black/[0.12] hover:border-accent/60 hover:bg-blue-50/40 text-[11px] font-semibold text-ink transition-all flex items-center justify-center gap-1" data-add="' + t + '">' +
          brandIcon(t) + '<span>' + OFFICIAL[t].name + '</span></button>';
      }).join("") + '</div>';
      grp = modelGroups();
    } else if (imp) {
      adds = '<button class="flex-1 min-w-0 py-1.5 rounded-xl bg-accent hover:bg-accentHover text-white shadow-[0_4px_12px_@shadow.accentGlow] active:scale-[0.98] text-[11px] font-semibold transition-all flex items-center justify-center gap-1" data-import="' + tabOf() + '">' +
        '<span class="material-symbols-outlined text-[14px]">download</span><span>导入刷新</span></button>';
      if (tabOf() === "ocx") inline = addRow(types);   /* OCX 除了一键导入刷新, 列表里还要能手填服务器连接与 API */
    } else {
      adds = addRow(types);
    }
    /* 官方选块与"新增"是列表内容, 跟着列表一起滚 */
    $("pageList").innerHTML = (rows.length ? html
        : (tabOf() === "official" ? "" : '<div class="flex-1 flex items-center justify-center text-[10px] text-muted py-3">\u8fd8\u6ca1\u6709\u8fd9\u4e00\u7c7b\u8d26\u6237</div>'))
      + (imp ? inline : adds) + hidden + grp;
    /* 气泡和"一键删除"挂页脚: 在滚动区之外, 列表滚到哪它们都钉在最下方 */
    var bub = (imp && !delMode) ? adds : "";   /* 气泡只在 CC-SW/OCX 列表里 */
    var foot = delMode ? "" : bub + wipeBtn(!!bub);   /* 与气泡并排时收窄, 单独一行时占满 */
    var fbox = $("pageFoot");
    if (fbox) { fbox.innerHTML = foot; footShow(fbox, !!foot); }
    paintBtns(delMode
      ? [{ id: "pgBack3", icon: "close", label: "\u53d6\u6d88", fn: function () { wipeOff(); } },
         { id: "pgDelOk", icon: "delete", label: "\u5220\u9664\u5df2\u9009", primary: true, fn: confirmDelSel }]
      : [{ id: "pgSet", icon: "tune", label: "\u8bbe\u7f6e", fn: openSettings },
         { id: "pgReload", icon: "sync", label: "\u5237\u65b0", fn: function () { loadAccts(); setTimeout(fetchState, 300); } }]);
    paintWipe();
  }
  /* ---------- CC-SW 隐藏区 ----------
     删过的节点没被销毁, 只是记进了后端隐藏名单。这里只放一个折叠头:
     展开后按名字列出来, 每条右边一个"展示", 点了就撤销标记、回到上面的列表。
     按钮就两个, 后端"隐藏"后紧接着 loadAccts 重扫, 不用另开接口。 */
  function showBtn(pid) {
    return '<button class="px-1.5 py-0.5 rounded-lg border border-black/[0.08] bg-white/80 hover:bg-blue-50/60 text-[10px] font-semibold text-ink2 hover:text-accent active:scale-[0.97] transition-all flex items-center gap-0.5 shrink-0" data-hid="' + esc(pid) + '" title="展示">' +
      '<span class="material-symbols-outlined text-[12px]">visibility</span><span>展示</span></button>';
  }
  function hiddenGroup() {
    var n = pgHidden.length;
    var head = '<div class="flex items-center gap-1 px-0.5 pt-1 pb-0.5 shrink-0 cursor-pointer" data-hid-toggle="1">' +
      '<span class="material-symbols-outlined text-[13px] text-muted">' + (hidOpen ? "expand_more" : "chevron_right") + '</span>' +
      '<span class="text-[10px] font-semibold text-muted">隐藏</span>' +
      '<span class="text-[9px] text-muted">' + (n ? n : 0) + ' 项</span></div>';
    if (!hidOpen) return head;
    if (!n) return head + '<div class="text-[10px] text-muted px-1 pb-1">没有隐藏项</div>';
    return head + pgHidden.map(function (h) {
      return '<div class="group/row rounded-xl px-2.5 bg-white/50 border border-white/70 flex items-center justify-between gap-1.5 py-1 shrink-0">' +
        '<div class="min-w-0"><div class="font-body-sm text-body-sm text-ink2 font-semibold leading-tight truncate">' + esc(h.name || h.provider_id) + '</div>' +
        '<div class="font-label-sm text-label-sm text-muted truncate">' + esc(h.base_url || "") + '</div></div>' +
        showBtn(h.provider_id) + '</div>';
    }).join("");
  }

  /* ---------- 官方页签: 标配选块(DeepSeek/Kimi/GLM) + 后端驱动的主流模型清单 ----------
     标准字段的标题/顺序/取值全在 configs/official/models.json, 页面只负责铺成
     "标题行 + 输入行"; 你想加字段或加模型, 改那个 json 就行, 这里不动。 */
  var MODELS = { fields: {}, models: [] };
  var MODELS_CATS = ["官方直连", "团队/企业版", "聚合平台", "云厂商", "其他"];
  function mField(k) { return (MODELS.fields && MODELS.fields[k]) || { title: k, hint: "", icon: "key" }; }
  function mModel(key) { return (MODELS.models || []).filter(function (m) { return m && m.key === key; })[0] || null; }
  function mCatOf(m) {
    var c = (m && m.category) || "";   /* 分类随便填: 只归到上面五类, 认不出的进"其他" */
    return MODELS_CATS.indexOf(c) >= 0 ? c : "其他";
  }
  function mColor(key) {
    var h = 0, s = String(key || "");
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return ["@color.accent", "@color.iris", "@color.grass", "@color.flame", "@color.azure"][h % 5];
  }
  function mGroup(key) {
    var t = String(mField(key).title || key).replace(/[\s\/]+.*$/, "");   /* "百炼 / 通义" 这类取前段 */
    return '<span class="w-5 h-5 rounded-lg flex items-center justify-center font-bold text-[10px] text-white shrink-0" style="background:' + mColor(key) + '">' + esc(t.charAt(0) || "?") + '</span>';
  }
  function loadModels() {
    return fetch("/api/official/models", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.models) MODELS = d;
        if (tabOf() === "official" && pageMode === "list") renderList();
        fitPage();
      })
      .catch(function () { MODELS = { fields: {}, models: [] }; });
  }
  function modelRow(m) {
    var n = Object.keys(m.fields || {}).length;   /* 这个模型声明了几个标准字段(不含名称) */
    return '<div class="group/row rounded-xl px-2.5 bg-white/65 hover:bg-white/95 border border-white/80 shadow-[0_1px_3px_rgba(0,0,0,0.03)] transition-all flex items-center justify-between gap-1.5 py-1 cursor-pointer shrink-0" data-model="' + esc(m.key) + '">' +
      '<div class="flex items-center gap-1.5 min-w-0">' + mGroup(m.key) +
      '<span class="font-body-sm text-body-sm text-ink font-semibold leading-tight truncate">' + esc(m.name || m.key) + '</span></div>' +
      '<div class="flex items-center gap-1 text-[9px] text-muted shrink-0">' + (n ? n + " 项" : "未配置") +
      '<span class="material-symbols-outlined text-[13px] text-muted group-hover/row:text-accent transition-colors">chevron_right</span></div></div>';
  }
  function modelGroups() {
    var ms = MODELS.models || [];
    if (!ms.length) return '<div class="flex items-center justify-center text-[10px] text-muted py-3">后端还没有模型清单 (configs/official/models.json)</div>';
    return MODELS_CATS.map(function (c) {   /* 分组顺序固定, 不按余额/名称重排 */
      var sub = ms.filter(function (m) { return mCatOf(m) === c; });
      if (!sub.length) return "";
      return '<div class="text-[9px] font-semibold text-muted px-0.5 pt-1 shrink-0">' + esc(c) + '</div>' + sub.map(modelRow).join("");
    }).join("");
  }
  /* 标题行(标准字段名) + 输入行(留空待填), 一一对应后端 json 里的字段顺序 */
  function modelCard(k, value) {
    var f = mField(k), title = f.title || k;
    var hint = f.hint ? '<span class="text-[9px] text-muted truncate max-w-[150px]">' + esc(f.hint) + '</span>' : '';
    return '<div class="rounded-2xl p-2 bg-white/70 border border-white/90 shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col gap-1">' +
      '<label class="text-[10px] font-semibold text-muted flex items-center justify-between gap-1" for="' + fid(k) + '">' +
      '<span class="flex items-center gap-1"><span class="material-symbols-outlined text-[12px] text-azure">' + esc(f.icon || "key") + '</span><span>' + esc(title) + '</span></span>' + hint + '</label>' +
      '<input id="' + fid(k) + '" autocomplete="off" spellcheck="false" class="w-full bg-transparent border-0 border-b border-black/[0.08] focus:border-accent focus:ring-0 p-0 pb-0.5 font-mono text-[12px] text-ink" type="text" placeholder="待填写" value="' + esc(value == null ? "" : value) + '"></div>';
  }
  function openModel(key) {
    var m = mModel(key); if (!m) return;
    pageMode = "form";
    cur = { id: "", type: "official", tab: "official", model: key, raw: m.fields || {} };
    var ks = Object.keys(m.fields || {});
    $("pageFields").innerHTML = ks.map(function (k) { return modelCard(k, m.fields[k]); }).join("");
    $("pageExtras").innerHTML = "";
    el_show("pageList", false); el_show("pageForm", true); el_show("pageExtras", false);
    $("pageTitle").textContent = m.name || key;
    $("pageSection").textContent = "标准字段";
    $("pageHint").textContent = "字段表在 configs/official/models.json";
    showMsg(ks.length ? "" : "这个模型在后端没有声明字段", false);
    paintBtns([
      { id: "pgBack2", icon: "arrow_back", label: "返回", fn: backToList },
      { id: "pgSaveM", icon: "save", label: "保存", primary: true, fn: function () { saveModel(); } }
    ]);
    fitPage();
  }
  function saveModel() {
    var m = mModel(cur && cur.model); if (!m) return;
    var out = {};
    Object.keys(m.fields || {}).forEach(function (k) { var el = $(fid(k)); if (el) out[k] = el.value; });
    api("official/models/save", { key: m.key, fields: out }, true).then(function (r) {
      if (!r || !r.ok) { showMsg("保存失败: " + ((r && r.error) || "未知错误"), false); return; }
      m.fields = out;
      showMsg("已保存 · " + (m.name || m.key), true);
    });
  }
