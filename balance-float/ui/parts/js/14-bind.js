
  /* ---------- 绑定 ---------- */
  function bindPage() {
    var tabs = $("pageTabs");
    if (tabs) tabs.addEventListener("click", function (e) {
      var b = e.target.closest("[data-kind]"); if (!b) return;
      S.tab = b.getAttribute("data-kind");
      pageMode = "list"; cur = null;
      delMode = false; sel = {};
      el_show("pageList", true); el_show("pageForm", false); el_show("pageExtras", false);
      $("pageTitle").textContent = part().title;
      paintTabs(); showMsg("", true); renderList(); fitPage();
    });
    var list = $("pageList");
    if (list) list.addEventListener("click", function (e) {
      var hidT = e.target.closest("[data-hid-toggle]");
      if (hidT) { hidToggle(); return; }
      var hid = e.target.closest("[data-hid]");
      if (hid) { hidClick(hid.getAttribute("data-hid")); return; }
      var pick = e.target.closest("[data-pick]");
      if (pick) { togglePick(pick.getAttribute("data-pick")); return; }
      var imp = e.target.closest("[data-import]");
      if (imp) { doImport(imp.getAttribute("data-import")); return; }
      var md = e.target.closest("[data-model]");
      if (md) { openModel(md.getAttribute("data-model")); return; }
      var add = e.target.closest("[data-add]");
      if (add) { openForm(null, add.getAttribute("data-add")); return; }
      var acc = e.target.closest("[data-acc]");
      if (acc) {
        if (delMode) { togglePick(acc.getAttribute("data-acc")); return; }   /* 删除模式里点整行就是勾选 */
        var hit = pageRows.filter(function (a) { return a && a.id === acc.getAttribute("data-acc"); })[0];
        if (hit) openForm(hit, hit.type);
      }
    });
    if ($("pageClose")) $("pageClose").addEventListener("click", pageBack);
    var footBox = $("pageFoot");   /* 页脚内容随渲染重建, 用委托绑 */
    if (footBox) footBox.addEventListener("click", function (e) {
      /* "导入刷新"气泡也挂在页脚上, 委托要一并认它 —— 早先只认删除按钮,
         CC-SW/OCX 两个气泡点了完全没反应 */
      var imp = e.target.closest("[data-import]");
      if (imp) { doImport(imp.getAttribute("data-import")); return; }
      if (!e.target.closest("#pageWipe")) return;
      if (delMode) { confirmDelSel(); return; }
      setPageDel(true);
      showMsg("\u70b9\u6574\u884c\u6216\u884c\u5c3e\u5706\u5708\u9009\u4e2d, \u518d\u70b9\u4e0b\u65b9\u786e\u8ba4", true);
    });
    window.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && S.page) pageBack();
    });
    /* 窗口尺寸变了重新贴合内容(不是反过来) */
    window.addEventListener("resize", function () { if (S.page) fitPage(); });
    API_STUBS.openAddModal = function () { setPage(true, S.tab || "official"); };
    paintTabs();   /* 模板里空页签默认是选中态, 打开前先把状态抹平 */
    API_STUBS.openEditModal = function () { /* 行点击不开编辑: 统一在接入页改, 免得两处表单打架 */ };
    API_STUBS.testAccount = function () { if (pageMode === "form") submitAcc(true); };
    API_STUBS.saveAccount = function () { if (pageMode === "form") submitAcc(false); };
    API_STUBS.saveSettings = saveSettings;
  }
  window.BalanceFloat = { state: S, stubs: API_STUBS, refresh: fetchState, setExpanded: setExpanded };
  $("btnAdd").addEventListener("click", function () { API_STUBS.openAddModal(); });
  $("btnDel").addEventListener("click", function () { setDelMode(true); });
  $("btnOk").addEventListener("click", confirmDel);
  $("rowList").addEventListener("click", function (e) {
    if (suppressClick) { suppressClick = false; return; }
    var row = e.target.closest("[data-row]");
    if (!row) return;
    var i = Number(row.getAttribute("data-row"));
    if (delMode) {
      var rid = S.accounts[i] && S.accounts[i].id;
      if (!rid) return;
      sel[rid] = !sel[rid];
      renderRows();
      return;
    }
    var op = e.target.closest("[data-op]");
    if (op) { e.stopPropagation(); API_STUBS.moveRow(i, op.getAttribute("data-op") === "up" ? -1 : 1); return; }
    API_STUBS.openEditModal(i);
  });
