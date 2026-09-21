
  /* ---------- 数据拉取 ---------- */
  function fetchState() {
    if (MODE !== "rt") return Promise.resolve();
    return fetch("/api/state", { cache: "no-store" })
      .then(function (res) { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function (data) {
        S.stations = Array.isArray(data.stations) ? data.stations.filter(Boolean) : [];
        S.accounts = Array.isArray(data.accounts) ? data.accounts : [];
        S.traffic = data.traffic || null;
        S.settings = data.settings || {};
        S.loading = !!data.loading;
        if (data.updated) S.lastUpdated = data.updated;
        pairStations();
        dropDead(S.accounts.map(function (a) { return a && a.id; }));
        render();
      })
      .catch(function () { S.loading = false; render(); });
  }
