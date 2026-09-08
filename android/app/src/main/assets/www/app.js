/* ============================================================
   校园网助手 Android 检测版 — 前端逻辑
   与桌面版同款协议：Kotlin 经 window.__onEvent(obj) 推事件，
   JS 经 window.AndroidBridge.* 调用原生（demo 模式下用假桥接）。
   ============================================================ */
"use strict";

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

/* ---------------- 图标（内联 SVG，Android 无 Segoe 图标字体） ---------------- */
const ICONS = {
  gauge:  '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 3.5"/>',
  key:    '<circle cx="8" cy="14" r="4"/><path d="M11 11l8-8"/><path d="M16.5 5.5L19 8"/><path d="M14 8l2.5 2.5"/>',
  lifebuoy:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M5.7 5.7l3.5 3.5"/><path d="M14.8 14.8l3.5 3.5"/><path d="M18.3 5.7l-3.5 3.5"/><path d="M9.2 14.8l-3.5 3.5"/>',
  gear:   '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8v3M12 18.2v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2.8 12h3M18.2 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  globe:  '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>',
  wifi:   '<path d="M3.5 9.5a13 13 0 0 1 17 0"/><path d="M6.5 13a9 9 0 0 1 11 0"/><path d="M9.5 16.4a5 5 0 0 1 5 0"/><circle cx="12" cy="19" r="1" fill="currentColor"/>',
  signal: '<path d="M4 20h2v-4H4z"/><path d="M9 20h2v-8H9z"/><path d="M14 20h2v-12h-2z"/><path d="M19 20h2V4h-2z"/>',
  lan:    '<rect x="4" y="4" width="16" height="6" rx="1.5"/><rect x="4" y="14" width="16" height="6" rx="1.5"/><path d="M8 7h.01M8 17h.01"/>',
  cloud:  '<path d="M7 18a4.5 4.5 0 0 1-.4-9A5.5 5.5 0 0 1 17.2 9.6A3.8 3.8 0 0 1 17 18z"/>',
  shield: '<path d="M12 3l7 3v5c0 4.4-3 8.2-7 9.5C8 19.2 5 15.4 5 11V6z"/><path d="M9 11.5l2 2 4-4"/>',
  domain: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17"/><path d="M7 14h4M7 16.5h7"/>',
  proxy:  '<path d="M4 7h5l3.5 10H20"/><path d="M4 17h5"/><path d="M17 4.5L20 7l-3 2.5"/><path d="M17 14.5L20 17l-3 2.5"/>',
  tag:    '<path d="M4 4h7l9 9-7 7-9-9z"/><circle cx="8.5" cy="8.5" r="1.4"/>',
  alert:  '<path d="M12 4L2.8 19.5h18.4z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
  info:   '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
  check:  '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
  x:      '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  warn:   '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V13"/><path d="M12 16.5h.01"/>',
  minus:  '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
  log:    '<path d="M5 4h11a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z"/><path d="M8.5 8.5h6M8.5 12h6M8.5 15.5h4"/>',
  chev:   '<path d="M6 9l6 6 6-6"/>',
  refresh:'<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 3.5V8h-4.5"/>',
  external:'<path d="M14 4h6v6"/><path d="M20 4L10.5 13.5"/><path d="M19 14v5a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 19V7a1.5 1.5 0 0 1 1.5-1.5H10"/>'
};
function svg(name) {
  const p = ICONS[name] || ICONS.info;
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + p + '</svg>';
}
function hydrateIcons(root) {
  (root || document).querySelectorAll(".ficon[data-icon]").forEach(el => {
    el.innerHTML = svg(el.dataset.icon);
  });
}

/* ---------------- 默认配置（与 Kotlin ConfigStore.defaults 一致） ---------------- */
const DEFAULTS = {
  gateway: "192.168.254.17",
  status_url: "http://192.168.254.17/drcom/chkstatus",
  login_url: "http://192.168.254.17/drcom/login",
  portal_url: "http://192.168.254.17/",
  public_test_host: "223.5.5.5",
  test_domain: "www.baidu.com",
  carrier: "cmcc",
  wifi_keyword: "DORM",
  ping_count: 2,
  ping_timeout: 2,
  last_account: "",
  saved_password: "",
  remember_password: false
};

const STATE = {
  busy: false,
  cfg: Object.assign({}, DEFAULTS),
  demo: !window.AndroidBridge,
  report: null,
  checks: {},          // key -> {key,title,status,detail}
  order: [],           // 卡片展示顺序
  pendingLoginReqId: 0
};

/* ---------------- 桥接 ---------------- */
function B() { return window.AndroidBridge; }

/* 演示模式（PC Chrome 打开时），模拟全部桥接与事件 */
function installDemoApi() {
  document.body.classList.add("demo");
  const titles = {
    connection: "网络连接", wifi: "校园 WiFi", signal: "WiFi 信号强度", intranet: "校园网内网", external: "外网连通",
    auth: "校园网认证", dns: "域名解析", proxy: "系统代理", linklocal: "IP 获取状态"
  };
  const demoChecks = [
    { key: "connection", status: "ok",   detail: "已连接（WiFi）；223.5.5.5 可达（连通，延迟 12.8ms）" },
    { key: "wifi",       status: "ok",   detail: "已连接校园网 SSID：DORM-503（含关键字 DORM，网关可达）" },
    { key: "signal",     status: "ok",   detail: "信号良好（-52 dBm），连接的是附近 AP" },
    { key: "intranet",   status: "ok",   detail: "网关 192.168.254.17 连通，延迟 2.3ms" },
    { key: "external",   status: "ok",   detail: "互联网可达（223.5.5.5 连通，延迟 12.8ms）" },
    { key: "auth",       status: "ok",   detail: "已认证（2023123456@cmcc）" },
    { key: "dns",        status: "ok",   detail: "www.baidu.com 解析正常 → 110.242.68.4" },
    { key: "proxy",      status: "ok",   detail: "未检测到代理/VPN" },
    { key: "linklocal",  status: "ok",   detail: "本机 IPv4：192.168.254.103" }
  ];
  const fire = (t, ms) => setTimeout(() => window.__onEvent(t), ms);
  window.AndroidBridge = {
    runDetection() {
      fire({ type: "busy", running: true }, 0);
      fire({ type: "log", text: "开始网络诊断…" }, 0);
      fire({ type: "checksInit", checks: demoChecks.map(c => ({ key: c.key, title: titles[c.key], status: "wait", detail: "检测中…" })) }, 60);
      demoChecks.forEach((c, i) =>
        fire({ type: "checkDone", check: Object.assign({ title: titles[c.key] }, c) }, 260 + i * 240));
      fire({
        type: "done",
        report: {
          ok: true, state: "ok", summary: "一切正常，校园网认证有效",
          non_campus: false, no_ip: false, cellular_hijack: false, gateway_reachable: true, fail_count: 0, warn_count: 0,
          gateway: "192.168.254.17",
          checks: demoChecks.map(c => Object.assign({ title: titles[c.key] }, c))
        }
      }, 260 + demoChecks.length * 240 + 200);
      fire({ type: "busy", running: false }, 260 + demoChecks.length * 240 + 210);
    },
    login(account, carrier, password) {
      setTimeout(() => {
        window.__onEvent({ type: "log", text: "正在通过中国移动线路登录…（演示数据）" });
        window.__onEvent({ type: "loginResult", reqId: 1, ok: true, message: "登录成功", account, carrier });
      }, 900);
      return 1;
    },
    checkAuthStatus() {
      setTimeout(() => window.__onEvent({
        type: "authStatus", reqId: 2, reachable: true, online: true,
        account: "2023123456", carrier: "cmcc", message: ""
      }), 600);
      return 2;
    },
    getConfig() { return JSON.stringify(STATE.cfg); },
    saveConfig(json) { try { STATE.cfg = JSON.parse(json); } catch (e) {} return true; },
    openExternal(url) { console.log("openExternal", url); },
    openSystemSettings(t) { console.log("openSystemSettings", t); },
    getAppInfo() {
      return JSON.stringify({ version: "demo", apiLevel: 0, androidVersion: "Chrome", model: navigator.platform });
    }
  };
}

/* ---------------- 工具 ---------------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}
function now() {
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}
function logLine(text) {
  const box = $("#log");
  const div = document.createElement("div");
  div.textContent = "[" + now() + "] " + text;
  box.appendChild(div);
  while (box.children.length > 200) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}
function isDemo() { return STATE.demo; }

/* ---------------- Hero 状态区 ---------------- */
const HERO = {
  init:      { icon: "gauge",   cls: "",          title: "开始诊断" },
  busy:      { icon: "gauge",   cls: "",          title: "正在诊断…" },
  ok:        { icon: "check",   cls: "ok",        title: "一切正常" },
  bad:       { icon: "warn",    cls: "bad",       title: "发现问题" },
  unauth:    { icon: "key",     cls: "unauth",    title: "校园网未认证" },
  noncampus: { icon: "alert",   cls: "noncampus", title: "非校园网环境" },
  nonet:     { icon: "alert",   cls: "nonet",     title: "无网络连接" },
  noip:      { icon: "alert",   cls: "noip",      title: "未获取到 IP" }
};
function setHero(state, sub) {
  const h = HERO[state] || HERO.init;
  const hero = $("#hero");
  hero.className = "hero " + (STATE.busy ? "" : h.cls);
  $("#hero-glyph").innerHTML = svg(h.icon);
  $("#hero-title").textContent = state === "busy" ? "正在诊断…" : (h.title === "发现问题" && STATE.report ? "发现 " + STATE.report.fail_count + " 个问题" : h.title);
  $("#hero-sub").innerHTML = sub || "";
  $("#progress").classList.toggle("show", state === "busy");
  $("#btn-detect").disabled = STATE.busy;
  $("#btn-detect").innerHTML = svg("refresh") + (STATE.busy ? "检测中…" : "一键检测");
}

/* ---------------- 检测卡片 ---------------- */
const CHECK_ICONS = {
  connection: "globe", wifi: "wifi", signal: "signal", intranet: "lan", external: "cloud",
  auth: "shield", dns: "domain", proxy: "proxy", linklocal: "tag"
};
const PILL_TEXT = { ok: "通过", fail: "异常", warn: "提醒", skip: "跳过", wait: "检测中" };

function renderChecks() {
  const box = $("#checks");
  const keys = STATE.order.length ? STATE.order : Object.keys(STATE.checks);
  box.innerHTML = keys.map(k => {
    const c = STATE.checks[k];
    if (!c) return "";
    return '<div class="card ' + esc(c.status) + '">'
      + '<div class="top"><span class="ficon" data-icon="' + (CHECK_ICONS[c.key] || "info") + '"></span>'
      + '<span class="title">' + esc(c.title) + '</span></div>'
      + '<span class="pill ' + esc(c.status) + '">' + (PILL_TEXT[c.status] || c.status) + '</span>'
      + '<div class="detail">' + esc(c.detail) + '</div>'
      + '</div>';
  }).join("");
  hydrateIcons(box);
}

/* ---------------- 事件分发（Kotlin → JS） ---------------- */
window.__onEvent = function (ev) {
  try { handleEvent(ev); } catch (e) {
    logLine("事件处理异常：" + e.message);
  }
};

function handleEvent(ev) {
  switch (ev.type) {
    case "busy": {
      STATE.busy = !!ev.running;
      if (STATE.busy) {
        setHero("busy", "正在逐项检测网络状态，请稍候…");
      } else if (STATE.report) {
        applyReport(STATE.report);
      }
      updateLoginAvailability();
      break;
    }
    case "checksInit": {
      STATE.checks = {};
      STATE.order = [];
      (ev.checks || []).forEach(c => {
        STATE.checks[c.key] = { key: c.key, title: c.title, status: "wait", detail: "检测中…" };
        STATE.order.push(c.key);
      });
      renderChecks();
      // 重新检测时先隐藏顶部警告条,等 done 事件根据结果再决定是否显示
      $("#banner-noncampus").classList.remove("show");
      $("#banner-hijack").classList.remove("show");
      break;
    }
    case "checkDone": {
      const c = ev.check;
      if (c && c.key) {
        STATE.checks[c.key] = c;
        if (!STATE.order.includes(c.key)) STATE.order.push(c.key);
        renderChecks();
      }
      break;
    }
    case "done": {
      STATE.report = ev.report;
      applyReport(ev.report);
      break;
    }
    case "log": {
      logLine(ev.text || "");
      break;
    }
    case "loginResult": {
      if (ev.reqId !== STATE.pendingLoginReqId) break;
      STATE.pendingLoginReqId = 0;
      const el = $("#login-result");
      const txt = $("#login-result-text");
      el.className = "note show " + (ev.ok ? "ok" : "err");
      el.querySelector(".ficon").dataset.icon = ev.ok ? "check" : "alert";
      hydrateIcons(el);
      txt.textContent = ev.message || (ev.ok ? "登录成功" : "登录失败");
      logLine("登录结果：" + txt.textContent);
      if (!ev.ok) B() && B().checkAuthStatus();
      else refreshAuthLine();
      loadConfigIntoForms();   // 登录后可能更新了记住的账号
      updateLoginAvailability();
      break;
    }
    case "authStatus": {
      renderAuthLine(ev);
      break;
    }
    case "permission": {
      if ((ev.denied || "").includes("ACCESS_FINE_LOCATION")) {
        logLine("未授予定位权限，WiFi 名称将显示为不可用（不影响其它检测）");
      }
      break;
    }
  }
}

/* ---------------- 报告 → Hero / 横幅 ---------------- */
function applyReport(r) {
  const warnPart = r.warn_count > 0 ? "（另有 " + r.warn_count + " 项提醒，见检测卡片与「引导」页）" : "";
  switch (r.state) {
    case "nonet":
      setHero("nonet", "当前没有任何网络连接。请开启 WLAN 或移动数据后重新检测。");
      break;
    case "noip":
      setHero("noip", "本机未获取到 IPv4 地址，无法进行网络检测。可能原因：WiFi 未连接、DHCP 未分配地址或网卡驱动异常。请尝试重新连接 WiFi，或在「引导」页查看处理方法。");
      break;
    case "noncampus":
      setHero("noncampus", "你的网络是正常的，但当前不在校园网环境（无法连通校园网网关 " + esc(r.gateway) + "）。"
        + "检测和登录功能已停用。连接校园网 WiFi 后重新检测即可恢复。");
      break;
    case "unauth":
      setHero("unauth", "校园网已连接，但还没有完成认证上网。"
        + "前往「登录」页输入学号密码认证，或查看「引导」页。");
      break;
    case "bad":
      setHero("bad", esc(r.summary) + "。" + warnPart);
      break;
    default:
      setHero("ok", esc(r.summary) + "。" + warnPart);
  }
  $("#banner-noncampus").classList.toggle("show", !!r.non_campus);
  $("#banner-hijack").classList.toggle("show", !!r.cellular_hijack);
  updateLoginAvailability();
}

/* ---------------- 登录页 ---------------- */
function renderAuthLine(st) {
  const el = $("#auth-line");
  const txt = $("#auth-line-text");
  el.querySelector(".ficon").dataset.icon = "shield";
  let cls = "info", text;
  if (!st.reachable) {
    cls = "err";
    text = "认证服务器不可达（" + esc(st.message || "当前可能不在校园网内") + "）";
  } else if (st.online === true) {
    cls = "ok";
    const who = st.account ? esc(st.account) + (st.carrier ? "@" + esc(st.carrier) : "") : "";
    text = "当前已认证在线" + (who ? "：" + who : "");
  } else if (st.online === false) {
    cls = "warn";
    text = "当前未认证，请输入学号密码登录";
  } else {
    cls = "warn";
    text = "无法确定认证状态（" + esc(st.message || "服务器未返回在线标志") + "）";
  }
  el.className = "note show " + cls;
  hydrateIcons(el);
  txt.innerHTML = text;
  logLine("认证状态：" + txt.textContent.replace(/<[^>]+>/g, ""));
}

function refreshAuthLine() {
  if (B() && B().checkAuthStatus) B().checkAuthStatus();
}

function updateLoginAvailability() {
  // 非校园网 / 未获取到 IP / 无网络时登录必然失败，停用登录按钮避免误操作
  const st = STATE.report && STATE.report.state;
  const unavailable = st === "noncampus" || st === "noip" || st === "nonet";
  const reason = { noncampus: "当前不在校园网环境", noip: "本机未获取到 IP 地址", nonet: "当前无网络连接" }[st] || "";
  const btn = $("#btn-login");
  btn.disabled = STATE.busy || unavailable || STATE.pendingLoginReqId !== 0;
  btn.title = unavailable ? reason + "，请恢复网络后重新检测再登录" : "";
  btn.innerHTML = STATE.pendingLoginReqId !== 0 ? "登录中…" : "登 录";
}

function doLogin() {
  const account = $("#f-account").value.trim();
  const password = $("#f-password").value;
  const carrier = $("#f-carrier").value;
  if (!account) { $("#f-account").focus(); return; }
  if (!password) { $("#f-password").focus(); return; }
  STATE.pendingLoginReqId = B().login(account, carrier, password);
  updateLoginAvailability();
  const el = $("#login-result");
  el.className = "note show info";
  el.querySelector(".ficon").dataset.icon = "info";
  hydrateIcons(el);
  $("#login-result-text").textContent = "正在登录，请稍候…";
}

/* ---------------- 设置页 ---------------- */
function fillSettings(cfg) {
  $("#s-gateway").value = cfg.gateway;
  $("#s-public").value = cfg.public_test_host;
  $("#s-domain").value = cfg.test_domain;
  $("#s-status").value = cfg.status_url;
  $("#s-login").value = cfg.login_url;
  $("#s-portal").value = cfg.portal_url;
  $("#s-carrier").value = cfg.carrier;
  $("#s-keyword").value = cfg.wifi_keyword;
  // 首页适用范围横幅中的关键字与配置保持一致
  const scopeKw = $("#scopeKeyword");
  if (scopeKw) scopeKw.textContent = cfg.wifi_keyword || "DORM";
}

function collectSettings() {
  return {
    gateway: $("#s-gateway").value.trim() || DEFAULTS.gateway,
    public_test_host: $("#s-public").value.trim() || DEFAULTS.public_test_host,
    test_domain: $("#s-domain").value.trim() || DEFAULTS.test_domain,
    status_url: $("#s-status").value.trim() || DEFAULTS.status_url,
    login_url: $("#s-login").value.trim() || DEFAULTS.login_url,
    portal_url: $("#s-portal").value.trim() || DEFAULTS.portal_url,
    carrier: $("#s-carrier").value,
    wifi_keyword: $("#s-keyword").value.trim()
  };
}

function saveSettings() {
  const merged = Object.assign({}, STATE.cfg, collectSettings());
  const ok = B().saveConfig(JSON.stringify(merged));
  if (ok) {
    STATE.cfg = merged;
    const h = $("#save-hint");
    h.classList.add("show");
    setTimeout(() => h.classList.remove("show"), 1600);
    logLine("设置已保存");
  }
}

function loadConfigIntoForms() {
  try {
    const raw = B() ? B().getConfig() : JSON.stringify(STATE.cfg);
    const cfg = JSON.parse(raw);
    STATE.cfg = Object.assign({}, DEFAULTS, cfg);
  } catch (e) {
    STATE.cfg = Object.assign({}, DEFAULTS);
  }
  fillSettings(STATE.cfg);
  // 登录表单回填
  $("#f-account").value = STATE.cfg.last_account || "";
  $("#f-carrier").value = STATE.cfg.carrier || "cmcc";
  $("#f-remember").checked = !!STATE.cfg.remember_password;
  $("#f-password").value = STATE.cfg.remember_password ? (STATE.cfg.saved_password || "") : "";
}

/* ---------------- 导航 ---------------- */
function switchView(name) {
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + name));
  $$(".navbtn").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  $("main").scrollTop = 0;
}

/* ---------------- 启动 ---------------- */
function init() {
  if (STATE.demo) installDemoApi();
  hydrateIcons(document);

  setHero("init", "点击下方按钮检测网络与校园网认证状态。本工具仅做检测，不会修改你的手机设置。");
  logLine("校园网助手已启动" + (STATE.demo ? "（演示模式）" : ""));

  // 应用信息
  try {
    const info = JSON.parse(B().getAppInfo());
    const api = info.apiLevel > 0 ? " · Android " + info.androidVersion + " (API " + info.apiLevel + ") · " + info.model : "";
    $("#about").innerHTML = "<b>校园网助手</b> 检测版 v" + esc(info.version) + api
      + "<br>纯检测工具：不修改系统网络配置，不上传任何数据";
  } catch (e) { /* 演示模式忽略 */ }

  loadConfigIntoForms();
  updateLoginAvailability();

  // 事件绑定
  $("#btn-detect").addEventListener("click", () => {
    STATE.report = null;
    B().runDetection();
  });
  $("#btn-login").addEventListener("click", doLogin);
  $("#btn-portal").addEventListener("click", () => B().openExternal(STATE.cfg.portal_url));
  $("#btn-portal-2").addEventListener("click", () => B().openExternal(STATE.cfg.portal_url));
  $("#btn-save").addEventListener("click", saveSettings);
  $("#btn-reset").addEventListener("click", () => {
    fillSettings(DEFAULTS);
    saveSettings();
  });
  $("#f-remember").addEventListener("change", e => {
    const merged = Object.assign({}, STATE.cfg, { remember_password: e.target.checked });
    B().saveConfig(JSON.stringify(merged));
    STATE.cfg = merged;
    if (!e.target.checked) $("#f-password").value = "";
  });
  $$(".navbtn").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
  $$("[data-goto-settings]").forEach(b =>
    b.addEventListener("click", () => B().openSystemSettings(b.dataset.gotoSettings)));

  // 适用范围横幅：关闭仅对本次启动生效（下次打开应用依旧提示）+ 教程链接
  $("#btnScopeClose").addEventListener("click", () => {
    $("#banner-scope").classList.add("hidden");
  });
  $$(".link-btn[data-url]").forEach(a => {
    a.addEventListener("click", e => {
      e.preventDefault();
      if (B() && B().openExternal) B().openExternal(a.dataset.url);
    });
  });
}

document.addEventListener("DOMContentLoaded", init);
