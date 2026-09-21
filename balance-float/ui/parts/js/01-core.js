
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  var MODE = null; /* rt = 悬浮窗运行时, preview = 浏览器预览(展示设计稿原样) */
  var S = { expanded: false, page: false, tab: "official", stations: [], accounts: [], traffic: null, settings: {}, loading: true, lastUpdated: "" };
  /* 展开列表的行状态: 拖拽排序 / 批量删除 */
  var delMode = false;   /* 减号进入的选定删除模式 */
  var sel = {};          /* 已勾选的账户 id */
  var dead = {};         /* 已删除, 但后台可能还回传一次的 id */
  var dragIdx = -1;      /* 正在拖拽的行下标, -1 为未拖拽 */
  var dragMoved = false;
  var suppressClick = false;
