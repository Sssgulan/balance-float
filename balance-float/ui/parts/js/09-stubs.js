
  /* ---------- 预留接口: 暂不接后台 ---------- */
  /* 后续接入时, 只需把对应函数体换成 fetch("/api/...") 或 bridge 调用; 后端接口均已就绪 */
  var API_STUBS = {
    openAddModal: function () {},    /* 预留: 底部"添加" → 弹窗 + GET /api/accounts */
    openEditModal: function (i) {},  /* 预留: 点击行 → 编辑回填 */
    moveRow: function (i, d) {
      var ids = idOrder();
      var j = i + d;
      if (j < 0 || j >= ids.length) return;
      ids.splice(j, 0, ids.splice(i, 1)[0]);
      saveOrder(ids);
    },
    startRowDrag: function (i) { dragIdx = i; dragMoved = false; },
    testAccount: function () {},     /* 预留: POST /api/account/test */
    saveAccount: function () {},     /* 预留: POST /api/account/save */
    deleteAccount: function (id) { api("account/delete", { id: id }, true); },  /* 已接后台 */
    saveSettings: function () {},    /* 预留: POST /api/settings(刷新间隔) */
    ccswScan: function () {},        /* 预留: GET /api/ccsw/scan + POST /api/ccsw/import */
    ocxScan: function () {},         /* 预留: GET /api/ocx/scan + POST /api/ocx/import(_path) */
    setOpacity: function (a) {},     /* 预留: Bridge.set_opacity(0-255) */
    openConfigs: function () {}      /* 预留: Bridge.open_configs */
  };