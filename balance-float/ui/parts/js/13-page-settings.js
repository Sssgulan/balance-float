
  /* ---------- 设置态: 模板里的两个步进器 ---------- */
  function openSettings() {
    pageMode = "settings"; cur = null;
    var s = S.settings || {};
    pgMinutes = Math.max(1, Number(s.refresh_minutes) || Math.max(1, Math.round((Number(s.refresh_seconds) || 60) / 60)));
    pgSeconds = Math.max(1, Number(s.timeout) || 10);
    $("pageTitle").textContent = "\u8f6e\u8be2\u8bbe\u7f6e";
    $("pageSection").textContent = "\u5168\u5c40\u8bbe\u7f6e";
    $("pageHint").textContent = "";
    $("pageFields").innerHTML =
      stepCard("pgM", "\u81ea\u52a8\u67e5\u8be2\u95f4\u9694\uff08\u5206\u949f\uff09", pgMinutes) +
      stepCard("pgS", "\u8d85\u65f6\u65f6\u95f4\uff08\u79d2\uff09", pgSeconds);
    el_show("pageList", false); el_show("pageForm", true); el_show("pageExtras", false);
    paintBtns([
      { id: "pgBack3", icon: "arrow_back", label: "\u8fd4\u56de", fn: backToList },
      { id: "pgSave2", icon: "check_circle", label: "\u4fdd\u5b58", primary: true, fn: saveSettings }
    ]);
    bindSteps();
    fitPage();
  }
  function stepCard(id, label, value) {
    return '<div class="rounded-2xl p-2 bg-white/70 border border-white/90 shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col gap-1">' +
      '<span class="text-[10px] font-semibold text-muted truncate">' + label + '</span>' +
      '<div class="flex items-center justify-between mt-0.5">' +
      '<button type="button" class="w-5 h-5 rounded-full bg-black/[0.04] hover:bg-black/[0.08] active:scale-90 flex items-center justify-center text-ink font-bold text-[12px] leading-none transition-all" data-step="-1" data-for="' + id + '">\u2212</button>' +
      '<input id="' + id + '" class="w-16 bg-transparent border-0 p-0 text-center font-mono text-[12px] font-bold text-ink focus:ring-0" type="number" min="1" value="' + value + '">' +
      '<button type="button" class="w-5 h-5 rounded-full bg-black/[0.04] hover:bg-black/[0.08] active:scale-90 flex items-center justify-center text-ink font-bold text-[12px] leading-none transition-all" data-step="1" data-for="' + id + '">+</button></div></div>';
  }
  function saveSettings() {
    var m = parseInt(($("pgM") || {}).value, 10), s = parseInt(($("pgS") || {}).value, 10);
    if (!isFinite(m) || m <= 0 || !isFinite(s) || s <= 0) { showMsg("\u8bf7\u586b\u6b63\u6574\u6570", false); return; }
    api("settings", { refresh_minutes: m, timeout: s }, true).then(function (r) {
      if (r && r.ok) { showMsg("\u5df2\u4fdd\u5b58 \u00b7 \u95f4\u9694 " + m + " \u5206\u949f", true); fetchState(); }
      else { showMsg("\u4fdd\u5b58\u5931\u8d25: " + ((r && r.error) || "\u672a\u77e5\u9519\u8bef"), false); }
    });
  }
  var GLYPHS = ["cloud", "delete", "add", "tune", "sync", "close", "arrow_back", "arrow_forward", "check_circle", "network_check", "download", "code", "save", "chevron_right", "group", "fingerprint", "delete_sweep", "delete_forever", "radio_button_unchecked", "visibility", "expand_more"];
  var scanTag = null;
  function scanGlyphs() {
    if (MODE !== "preview") return;
    if (!scanTag) { scanTag = document.createElement("span"); scanTag.className = "hidden"; document.body.appendChild(scanTag); }
    scanTag.textContent = GLYPHS.join(" ");
  }