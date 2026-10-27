"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICON = {
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z"/></svg>',
  stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/></svg>',
  merge: '<svg viewBox="0 0 24 24"><path d="M6 3v6a6 6 0 0 0 6 6h0a6 6 0 0 1 6 6M18 3v6a6 6 0 0 1-3 5.2"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  heart: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z"/></svg>',
  users: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/></svg>',
  gift: '<svg viewBox="0 0 24 24"><rect x="3" y="8" width="18" height="5" rx="1"/><path d="M5 13v7h14v-7M12 8v12M12 8S10.5 3 8 4s0 4 4 4Zm0 0s1.5-5 4-4 0 4-4 4Z"/></svg>',
  gem: '<svg viewBox="0 0 24 24"><path d="M6 3h12l4 6-10 12L2 9z"/><path d="M2 9h20M12 21 8 9l4-6 4 6z"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
  rec: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg>',
  dot: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.5" fill="currentColor"/></svg>',
};

const AVATAR_COLORS = [
  ["#25f4ee", "#3b82f6"], ["#fe2c55", "#f97316"], ["#a855f7", "#ec4899"],
  ["#22c55e", "#14b8a6"], ["#f59e0b", "#ef4444"], ["#6366f1", "#25f4ee"],
];

let state = null;
let recs = { items: [], free: 0, total: 0 };
let serverOffset = 0; // server clock minus browser clock
let libFilter = "";

// ---------- formatting ----------

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return (n / 1024 ** i).toFixed(i >= 3 ? 2 : i ? 1 : 0) + " " + u[i];
}
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const fmtNum = (n) => (n === null || n === undefined ? "–" : compact.format(n));
const fullNum = (n) => (n === null || n === undefined ? "" : n.toLocaleString());

function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}
function fmtDur(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
function fmtAgo(ts) {
  const d = now() - ts;
  if (d < 10) return "เมื่อสักครู่";
  if (d < 60) return `${Math.floor(d)} วินาทีที่แล้ว`;
  if (d < 3600) return `${Math.floor(d / 60)} นาทีที่แล้ว`;
  if (d < 86400) return `${Math.floor(d / 3600)} ชั่วโมงที่แล้ว`;
  return new Date(ts * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short" });
}
function fmtIn(ts) {
  const d = ts - now();
  if (d <= 5) return "กำลังเช็ก";
  if (d < 60) return `อีก ${Math.ceil(d)} วิ`;
  return `อีก ${Math.ceil(d / 60)} นาที`;
}
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString("th-TH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
const now = () => Date.now() / 1000 + serverOffset;

// "user_20261027_201050.mp4" -> start time in seconds
function startFromName(name) {
  const m = name.match(/_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() / 1000 : null;
}

// ---------- avatars ----------

function avatarStyle(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const [a, b] = AVATAR_COLORS[h % AVATAR_COLORS.length];
  return `--av: linear-gradient(135deg, ${a}, ${b})`;
}
// Only draw an avatar <img> once the browser has it, so re-renders never flash
const avatarCache = {};
function avatarImg(url) {
  if (!url) return "";
  if (avatarCache[url] === "ok") return `<img src="${esc(url)}" alt="" referrerpolicy="no-referrer">`;
  if (avatarCache[url] === undefined) {
    avatarCache[url] = "loading";
    const img = new Image();
    img.referrerPolicy = "no-referrer";
    img.onload = () => { avatarCache[url] = "ok"; drawn = {}; if (state) render(); renderRecs(true); };
    img.onerror = () => { avatarCache[url] = "error"; };
    img.src = url;
  }
  return "";
}
function avatar(user) {
  const c = state && state.channels.find((x) => x.username === user);
  return `<div class="avatar" style="${avatarStyle(user)}">${esc(user[0].toUpperCase())}${avatarImg(c && c.avatar)}</div>`;
}
const displayName = (user) => {
  const c = state && state.channels.find((x) => x.username === user);
  return (c && c.nickname) || "@" + user;
};

// Write HTML only when it changed, so hover states, focus and videos survive polling
let drawn = {};
function draw(el, html) {
  if (drawn[el.id] === html) return false;
  drawn[el.id] = html;
  el.innerHTML = html;
  return true;
}

// ---------- api ----------

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg, isErr = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 3800);
}

async function refreshState() {
  try {
    state = await api("/api/state");
    serverOffset = state.now - Date.now() / 1000;
    render();
  } catch {
    const el = $("#account");
    el.className = "acct warn";
    el.querySelector(".acct-text").innerHTML = "<b>เชื่อมต่อโปรแกรมไม่ได้</b><span>โปรแกรมปิดอยู่หรือกำลังรีสตาร์ท</span>";
  }
}
async function refreshRecs() {
  try {
    recs = await api("/api/recordings");
    renderRecs();
    renderDisk();
  } catch { /* shown via state polling */ }
}

// ---------- render ----------

function render() {
  renderAccount();
  renderBanner();
  renderOnAir();
  renderChannels();
  renderEvents();
  const s = state.settings;
  const live = state.channels.filter((c) => c.recording).length;
  const watching = state.channels.filter((c) => !c.paused).length;
  $("#interval-note").textContent = live
    ? `กำลังอัด ${live} ช่อง · เฝ้าอยู่ ${watching} จาก ${state.channels.length} ช่อง`
    : `เฝ้าอยู่ ${watching} จาก ${state.channels.length} ช่อง · เช็กทุก ${Math.round(s.check_min / 60)}–${Math.round(s.check_max / 60)} นาที`;
  $("#channels-note").textContent = `เช็กแต่ละช่องทุก ${Math.round(s.check_min / 60)}–${Math.round(s.check_max / 60)} นาที แบบสุ่มเวลา`;
  $("#n-onair").textContent = live;
  $("#n-onair").className = live ? "hot" : "";
  $("#n-channels").textContent = state.channels.length;
  $(".rec-dot").classList.toggle("on", live > 0);
  document.title = live ? `● REC ${live} · Live Recorder` : "Live Recorder";
  tick();
}

function renderAccount() {
  const a = state.account, el = $("#account");
  const sync = state.cookie_sync;
  let cls = "acct", title = "กำลังตรวจ…", sub = "บัญชี TikTok";
  if (state.pause.reason === "no_cookies") { cls += " warn"; title = "ยังไม่มี cookie"; sub = "กดจัดการ cookie"; }
  else if (a.state === "ok") { cls += " ok"; title = "@" + a.name; sub = sync && !sync.error ? "ซิงก์ cookie จาก Chrome" : "ล็อกอินอยู่"; }
  else if (a.state === "logged_out") { cls += " warn"; title = "cookie หมดอายุ"; sub = "ล็อกอิน TikTok ใหม่"; }
  else if (a.state === "unknown") { cls += " warn"; title = "ตรวจ cookie ไม่ได้"; sub = "จะลองใหม่อัตโนมัติ"; }
  if (sync && sync.error) sub = "อ่าน Chrome ไม่ได้";
  el.className = cls;
  el.title = [a.error, sync && (sync.error ? "อ่าน cookie จาก Chrome ไม่ได้: " + sync.error
    : sync.last_sync ? "ดึง cookie จาก Chrome ล่าสุด " + fmtAgo(sync.last_sync) : "")].filter(Boolean).join("\n");
  el.querySelector(".acct-text").innerHTML = `<b>${esc(title)}</b><span>${esc(sub)}</span>`;
}

function renderBanner() {
  const p = state.pause, el = $("#banner");
  let title = "", body = "", action = false, captcha = false;
  const sync = state.cookie_sync;
  if (p.reason === "no_cookies") {
    title = "ยังไม่ได้ใส่ cookie";
    body = "ใส่ cookie ของบัญชี TikTok คุณเพื่อเริ่มเฝ้าดูช่อง";
    action = true;
  } else if (p.reason === "captcha") {
    title = "TikTok ขอให้ยืนยันตัวตน (CAPTCHA)";
    body = sync
      ? "หยุดเช็กช่องชั่วคราว (ไลฟ์ที่กำลังอัดยังอัดต่อ) · กด “เปิด TikTok” ยืนยันใน Chrome แล้วกด “ยืนยันแล้ว ทำงานต่อ”"
      : `หยุดเช็กชั่วคราว เหลือ <span data-left="${now() + p.seconds}"></span> · ยืนยันตัวตนใน tiktok.com แล้วอัปโหลด cookies.txt ใหม่`;
    action = !sync;
    captcha = true;
  } else if (p.reason) {
    title = "TikTok ขอให้ช้าลง (HTTP 429)";
    body = `รอแล้วจะทำงานต่อเอง เหลือ <span data-left="${now() + p.seconds}"></span>`;
  } else if (state.account.state === "logged_out") {
    title = "cookie หมดอายุหรือยังไม่ได้ล็อกอิน";
    body = sync ? "ล็อกอิน tiktok.com ใน Chrome แล้วโปรแกรมจะดึง cookie ใหม่เองภายใน 1 นาที"
      : "ช่องที่ต้องล็อกอินหรือจำกัดอายุอาจดูไม่ได้ ล็อกอิน tiktok.com แล้ว export cookies.txt ใหม่";
    action = !sync;
  }
  el.hidden = !title;
  if (!title) return draw(el, "");
  draw(el, `${ICON.warn}<div><b>${esc(title)}</b><p>${body}</p></div>` +
    (captcha ? `<div class="banner-actions">
        <a class="btn btn-sm" href="https://www.tiktok.com/" target="_blank" rel="noopener noreferrer">เปิด TikTok ${ICON.ext}</a>
        ${sync ? '<button class="btn btn-primary btn-sm" data-sync-cookies>ยืนยันแล้ว ทำงานต่อ</button>' : ""}
      </div>` : "") +
    (action ? '<button class="btn btn-primary btn-sm" data-open-cookies>ใส่ cookie</button>' : ""));
}

function airStats(st, viewers, mobile) {
  return `<div class="air-stats${mobile ? " m" : ""}">
    <div class="air-stat" title="${st.peak_viewers ? "สูงสุด " + fullNum(st.peak_viewers) : ""}"><span>${ICON.eye}คนดูตอนนี้</span><b>${fmtNum(viewers)}</b></div>
    <div class="air-stat likes" title="${fullNum(st.likes)}"><span>${ICON.heart}กดใจ</span><b>${fmtNum(st.likes)}</b></div>
    <div class="air-stat" title="คนเข้าดูทั้งหมด"><span>${ICON.users}เข้าดูทั้งหมด</span><b>${fmtNum(st.total_viewers)}</b></div>
    ${mobile ? "" : `<div class="air-stat" title="จำนวนคนที่ส่งของขวัญ"><span>${ICON.gift}คนส่งของขวัญ</span><b>${fmtNum(st.gift_senders)}</b></div>
    <div class="air-stat gems" title="${fullNum(st.diamonds)} เพชร"><span>${ICON.gem}เพชร</span><b>${fmtNum(st.diamonds)}</b></div>`}
  </div>`;
}

function renderOnAir() {
  const el = $("#onair-list");
  const live = state.channels.filter((c) => c.recording);
  if (!live.length) {
    const active = state.channels.filter((c) => !c.paused);
    const next = active.map((c) => c.next_check).filter(Boolean).sort()[0];
    let title, sub, off = false;
    if (!state.channels.length) { title = "ยังไม่มีช่องให้เฝ้า"; sub = "เพิ่มชื่อผู้ใช้ TikTok ที่ช่องด้านบน"; off = true; }
    else if (!active.length) { title = "หยุดเฝ้าทุกช่องอยู่"; sub = "เปิดสวิตช์ “เฝ้าดู” ที่ช่องด้านล่างเพื่อเริ่มใหม่"; off = true; }
    else if (state.pause.reason) { title = "พักการเช็กชั่วคราว"; sub = "ดูรายละเอียดที่แถบเตือนด้านบน"; off = true; }
    else {
      title = "ยังไม่มีใครไลฟ์";
      sub = `กำลังเฝ้า ${active.length} ช่อง` + (next ? ` · เช็กครั้งถัดไป <span data-next="${next}"></span>` : "") + " · เริ่มอัดเองทันทีที่มีคนไลฟ์";
    }
    return draw(el, `<div class="idle${off ? " off" : ""}"><div class="radar"><i></i></div><div><b>${title}</b><span>${sub}</span></div></div>`);
  }
  draw(el, live.map((c) => {
    const r = c.recording, st = r.stats || {}, u = esc(c.username);
    const viewers = st.viewers ?? c.viewers;
    const waiting = r.phase === "waiting";
    const phase = { reconnecting: "กำลังเชื่อมต่อใหม่", merging: "กำลังรวมไฟล์", starting: "กำลังเริ่ม", waiting: "ไลฟ์หลุด" }[r.phase];
    return `<article class="air${waiting ? " waiting" : ""}">
      <div class="air-av">${avatar(c.username)}<span class="onair-tag">${waiting ? "PAUSED" : "● REC"}</span></div>
      <div class="air-main">
        <div class="air-name"><b>${esc(c.nickname || "@" + c.username)}</b><a href="https://www.tiktok.com/@${encodeURIComponent(c.username)}/live" target="_blank" rel="noopener noreferrer">@${u} ↗</a></div>
        ${c.title ? `<p class="air-title" title="${esc(c.title)}">${esc(c.title)}</p>` : ""}
        ${airStats(st, viewers, false)}
        ${waiting && r.wait_until ? `<p class="air-note">ไลฟ์หลุด ถ้ากลับมาภายใน <b data-left="${r.wait_until}"></b> จะต่อเป็นคลิปเดียวกัน</p>` : ""}
      </div>
      ${airStats(st, viewers, true)}
      <div class="air-side">
        <span class="timer-label">${phase || "อัดมาแล้ว"}</span>
        <div class="timer" data-since="${r.started_at}"></div>
        <div class="air-meta">
          ${r.quality ? `<span class="tag q" title="คุณภาพที่ดีที่สุดที่ TikTok มีให้">${esc(r.quality)}</span>` : ""}
          <span class="tag">${fmtBytes(r.bytes)}</span>
          ${st.peak_viewers ? `<span class="tag">สูงสุด ${fmtNum(st.peak_viewers)} คน</span>` : ""}
        </div>
        <button class="btn btn-sm btn-stop" data-act="stop" data-user="${u}">${ICON.stop}หยุดอัด</button>
      </div>
    </article>`;
  }).join(""));
}

function channelStatus(c) {
  if (c.recording) return { cls: "live", text: "กำลังอัดอยู่", when: `<span data-since-short="${c.recording.started_at}"></span>` };
  if (c.paused) return { cls: "", text: "หยุดเฝ้าไว้", when: "" };
  if (c.error) return { cls: "err", text: c.error, when: c.last_check ? fmtTime(c.last_check) : "" };
  const when = c.next_check && !state.pause.reason ? `เช็ก<span data-next="${c.next_check}"></span>` : "";
  if (c.status === "live") return { cls: "live", text: "กำลังไลฟ์", when };
  if (c.status === "offline") return { cls: "on", text: "ออฟไลน์", when };
  return { cls: "on", text: "รอเช็กครั้งแรก", when };
}

function renderChannels() {
  const el = $("#channels");
  const list = [...state.channels].sort((a, b) =>
    (!!b.recording - !!a.recording) || (a.paused - b.paused) || a.username.localeCompare(b.username));
  if (!list.length) {
    return draw(el, '<div class="empty"><b>ยังไม่มีช่อง</b>พิมพ์ชื่อผู้ใช้ TikTok ในช่องด้านบนแล้วกด “เพิ่ม”</div>');
  }
  draw(el, list.map((c) => {
    const u = esc(c.username), s = channelStatus(c);
    const cls = ["ch", c.recording || c.status === "live" ? "is-live" : "", c.paused ? "is-paused" : "", s.cls === "err" ? "is-err" : ""].join(" ");
    return `<article class="${cls}">
      <div class="ch-top">
        <div class="ch-av">${avatar(c.username)}</div>
        <div class="ch-who"><b>${esc(c.nickname || "@" + c.username)}</b><a href="https://www.tiktok.com/@${encodeURIComponent(c.username)}" target="_blank" rel="noopener noreferrer">@${u}</a></div>
      </div>
      <div class="ch-status ${s.cls}" title="${esc(c.error || "")}"><span class="pip"></span><span class="what">${esc(s.text)}</span><span class="when">${s.when}</span></div>
      <div class="ch-foot">
        <label class="switch" title="${c.paused ? "เปิดเพื่อกลับมาเฝ้าช่องนี้" : "ปิดเพื่อหยุดเฝ้าชั่วคราว"}">
          <input type="checkbox" data-toggle="${u}" ${c.paused ? "" : "checked"}><i></i><span>เฝ้าดู</span>
        </label>
        <span class="grow"></span>
        <button class="icon-btn" data-act="check" data-user="${u}" title="เช็กตอนนี้" aria-label="เช็ก @${u} ตอนนี้" ${c.paused || c.recording ? "disabled" : ""}>${ICON.refresh}</button>
        <a class="icon-btn" href="https://www.tiktok.com/@${encodeURIComponent(c.username)}/live" target="_blank" rel="noopener noreferrer" title="เปิดไลฟ์ใน TikTok" aria-label="เปิดไลฟ์ของ @${u}">${ICON.ext}</a>
        <button class="icon-btn danger" data-act="remove" data-user="${u}" title="ลบช่อง" aria-label="ลบ @${u}">${ICON.trash}</button>
      </div>
    </article>`;
  }).join(""));
}

function renderChips() {
  const users = [...new Set(recs.items.map((r) => r.user))].sort();
  if (libFilter && !users.includes(libFilter)) libFilter = "";
  const chips = users.length > 1
    ? [["", "ทั้งหมด"], ...users.map((u) => [u, displayName(u)])]
        .map(([v, label]) => `<button class="chip${libFilter === v ? " on" : ""}" data-filter="${esc(v)}">${esc(label)}</button>`).join("")
    : "";
  draw($("#lib-chips"), chips);
}

function renderRecs(force) {
  if (force) delete drawn.recordings;
  renderChips();
  const el = $("#recordings");
  const q = $("#rec-search").value.trim().toLowerCase();
  const items = recs.items.filter((r) => (!libFilter || r.user === libFilter) &&
    (!q || r.name.toLowerCase().includes(q) || r.user.toLowerCase().includes(q) || displayName(r.user).toLowerCase().includes(q)));
  $("#n-files").textContent = recs.items.filter((r) => r.kind === "video").length;
  if (!items.length) {
    return draw(el, `<div class="empty"><b>${q || libFilter ? "ไม่พบคลิป" : "ยังไม่มีคลิป"}</b>${q || libFilter ? "ลองค้นหาคำอื่น" : "คลิปจะขึ้นที่นี่เมื่อมีช่องที่เฝ้าไว้เริ่มไลฟ์"}</div>`);
  }
  const html = items.map((r) => {
    const start = startFromName(r.name) || r.time;
    const when = new Date(start * 1000).toLocaleString("th-TH", { weekday: "short", day: "numeric", month: "short" }) + " · " + fmtTime(start);
    const who = `<span class="who">${avatar(r.user)}<span>${esc(displayName(r.user))}</span></span>`;
    if (r.kind === "video") {
      return `<article class="clip">
        <button class="thumb" data-play="${esc(r.path)}" data-title="${esc(displayName(r.user) + " · " + when)}" aria-label="เล่นคลิป ${esc(r.name)}">
          <video muted playsinline preload="none" data-src="/media/${encodeURI(r.path)}#t=15"></video>
          <span class="play">${ICON.play}</span>${who}<span class="dur" hidden></span>
        </button>
        <div class="clip-body">
          <div class="clip-text"><b>${esc(when)}</b><span>${fmtBytes(r.size)} · MP4</span></div>
          <a class="icon-btn" href="/media/${encodeURI(r.path)}?download=1" title="ดาวน์โหลด" aria-label="ดาวน์โหลด ${esc(r.name)}">${ICON.download}</a>
        </div>
      </article>`;
    }
    return `<article class="clip session${r.active ? " active" : ""}">
      <div class="thumb ph${r.active ? " active" : ""}">${r.active ? ICON.rec : ICON.layers}${who}</div>
      <div class="clip-body">
        <div class="clip-text"><b>${esc(when)}</b><span>${r.active ? "กำลังอัด" : "ยังไม่รวมไฟล์"} · ${r.segments} ส่วน · ${fmtBytes(r.size)}</span></div>
        ${r.active ? "" : `<button class="icon-btn" data-merge="${esc(r.path)}" title="รวมเป็น MP4" aria-label="รวมเป็น MP4">${ICON.merge}</button>`}
      </div>
    </article>`;
  }).join("");
  if (draw(el, html)) $$("video[data-src]", el).forEach((v) => thumbObserver.observe(v));
}

// Thumbnails: load a frame from each clip only when it scrolls into view
const thumbObserver = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const v = e.target;
    thumbObserver.unobserve(v);
    v.preload = "metadata";
    v.addEventListener("loadeddata", () => v.classList.add("ready"), { once: true });
    v.addEventListener("loadedmetadata", () => {
      const d = v.parentElement.querySelector(".dur");
      if (isFinite(v.duration) && v.duration > 0) { d.textContent = fmtDur(v.duration); d.hidden = false; }
    }, { once: true });
    v.src = v.dataset.src;
  }
}, { rootMargin: "200px" });

function eventKind(text) {
  if (/^🔴/.test(text)) return ["red", ICON.rec];
  if (/^✅/.test(text)) return ["green", ICON.check];
  if (/^(⚠️|❌|⏸|🛑|💾)/u.test(text) || /CAPTCHA|ผิดพลาด|ไม่ได้/.test(text)) return ["amber", ICON.warn];
  return ["", ICON.dot];
}
function renderEvents() {
  const ev = state.events;
  const out = state.settings.output_dir.replace(/\/$/, "") + "/";
  draw($("#events"), ev.length
    ? ev.map((e) => {
        const [cls, icon] = eventKind(e.text);
        const text = esc(e.text.replace(/^\p{Extended_Pictographic}️?\s*/u, "").split(out).join(""))
          .replace(/(\S+\/)([^/\s]+\.mp4)/g, '<span class="path">$2</span>');
        return `<li><span class="ic ${cls}">${icon}</span><div><p>${text}</p><time>${fmtDate(e.time)}</time></div></li>`;
      }).join("")
    : '<li class="none">ยังไม่มีกิจกรรม</li>');
}

function renderDisk() {
  const { free, total } = recs;
  if (!free) return;
  $("#disk-free").textContent = `ว่าง ${fmtBytes(free)}`;
  const used = total ? 1 - free / total : 0;
  $("#disk-bar").style.width = `${Math.round(used * 100)}%`;
  $(".meter").classList.toggle("low", free < 20 * 1024 ** 3);
  const clips = recs.items.reduce((s, r) => s + (r.size || 0), 0);
  const perHour = 1.8 * 3600 * 1e6 / 8; // ~1.8 Mbps per live
  $("#disk-note").textContent = `คลิปใช้ ${fmtBytes(clips)} · อัดได้อีกราว ${Math.floor(free / perHour)} ชั่วโมง`;
}

// live counters between polls
function tick() {
  $$("[data-since]").forEach((el) => { el.textContent = fmtClock(now() - +el.dataset.since); });
  $$("[data-since-short]").forEach((el) => { el.textContent = fmtDur(now() - +el.dataset.sinceShort); });
  $$("[data-left]").forEach((el) => { el.textContent = fmtClock(+el.dataset.left - now()); });
  $$("[data-next]").forEach((el) => { el.textContent = " " + fmtIn(+el.dataset.next); });
}
setInterval(tick, 1000);

// ---------- actions ----------

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#add-input");
  const name = input.value.trim().replace(/^@/, "").replace(/^https?:\/\/(www\.|m\.)?tiktok\.com\/@/, "").split(/[/?]/)[0];
  if (!name) return input.focus();
  try {
    const r = await api("/api/channels", { username: name });
    input.value = "";
    toast(`เพิ่ม @${r.username} แล้ว`);
    refreshState();
  } catch (err) { toast(err.message, true); }
});

async function channelAction(user, action, el) {
  if (el) el.disabled = true;
  try {
    await api(`/api/channels/${encodeURIComponent(user)}/${action}`, {});
    const msg = { remove: `ลบ @${user} แล้ว`, check: `กำลังเช็ก @${user}`, pause: `หยุดเฝ้า @${user} แล้ว`, resume: `เฝ้าดู @${user} ต่อแล้ว` }[action];
    toast(msg);
    await refreshState();
    if (action === "pause") setTimeout(refreshRecs, 1500);
  } catch (err) {
    toast(err.message, true);
    if (el) el.disabled = false;
    drawn = {};
    if (state) render();
  }
}

document.addEventListener("change", (e) => {
  const t = e.target.closest("[data-toggle]");
  if (!t) return;
  const user = t.dataset.toggle;
  const c = state.channels.find((x) => x.username === user);
  if (!t.checked && c && c.recording &&
      !confirm(`@${user} กำลังอัดอยู่ ถ้าหยุดเฝ้าจะหยุดอัดด้วย\nไฟล์ที่อัดไปแล้วจะถูกรวมเก็บไว้`)) {
    t.checked = true;
    return;
  }
  channelAction(user, t.checked ? "resume" : "pause", t);
});

document.addEventListener("click", async (e) => {
  const act = e.target.closest("[data-act]");
  if (act) {
    const { act: action, user } = act.dataset;
    if (action === "remove" && !confirm(`ลบ @${user} ออกจากรายการเฝ้าดู?\nคลิปที่อัดไว้แล้วจะไม่ถูกลบ`)) return;
    if (action === "stop") {
      if (!confirm(`หยุดอัด @${user}?\nไฟล์ที่อัดไปแล้วจะถูกรวมเก็บไว้ และช่องนี้จะหยุดเฝ้าจนกว่าจะเปิดสวิตช์ “เฝ้าดู” อีกครั้ง`)) return;
      return channelAction(user, "pause", act);
    }
    if (action === "check") act.classList.add("spin");
    return channelAction(user, action, act);
  }
  const chip = e.target.closest("[data-filter]");
  if (chip) { libFilter = chip.dataset.filter; return renderRecs(); }
  const play = e.target.closest("[data-play]");
  if (play) {
    const v = $("#video");
    $("#video-title").textContent = play.dataset.title;
    v.src = "/media/" + encodeURI(play.dataset.play);
    $("#dlg-video").showModal();
    v.play().catch(() => {});
    return;
  }
  const merge = e.target.closest("[data-merge]");
  if (merge) {
    merge.disabled = true;
    merge.classList.add("spin");
    toast("กำลังรวมไฟล์…");
    try {
      await api("/api/merge", { path: merge.dataset.merge });
      toast("รวมไฟล์เสร็จแล้ว");
    } catch (err) { toast(err.message, true); }
    refreshRecs();
    return;
  }
  if (e.target.closest("[data-open-cookies]") || e.target.closest("#account")) return openCookies();
  const syncBtn = e.target.closest("[data-sync-cookies]");
  if (syncBtn) {
    const label = syncBtn.textContent;
    syncBtn.disabled = true;
    syncBtn.textContent = "กำลังตรวจ…";
    try {
      const r = await api("/api/cookies/sync", {});
      const msg = { resumed: "ผ่านการยืนยันแล้ว ทำงานต่อ", still_captcha: "TikTok ยังขอให้ยืนยันอยู่ ลองยืนยันใน Chrome อีกครั้ง", updated: "ดึง cookie ใหม่จาก Chrome แล้ว", same: "cookie ใน Chrome ยังเป็นชุดเดิม" }[r.result] || "เรียบร้อย";
      toast(msg, r.result === "still_captcha");
    } catch (err) { toast(err.message, true); }
    syncBtn.disabled = false;
    syncBtn.textContent = label;
    refreshState();
  }
});

// sidebar: highlight the section in view
const navLinks = $$(".nav a");
const sectionObserver = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (e.isIntersecting) navLinks.forEach((a) => a.classList.toggle("active", a.hash === "#" + e.target.id));
  }
}, { rootMargin: "-30% 0px -60% 0px" });
["onair", "channels-sec", "library", "activity"].forEach((id) => sectionObserver.observe(document.getElementById(id)));

// video dialog
function closeVideo() { const v = $("#video"); v.pause(); v.removeAttribute("src"); v.load(); $("#dlg-video").close(); }
$("#video-close").addEventListener("click", closeVideo);
$("#dlg-video").addEventListener("click", (e) => { if (e.target.id === "dlg-video") closeVideo(); });
$("#dlg-video").addEventListener("cancel", (e) => { e.preventDefault(); closeVideo(); });

// cookie dialog
let cookieText = "";
function openCookies() {
  cookieText = "";
  const sync = state && state.cookie_sync;
  $("#cookie-chrome-box").hidden = !sync;
  $("#cookie-or").hidden = !sync;
  if (sync) {
    $("#cookie-chrome-note").textContent = sync.error
      ? "อ่านไม่ได้: " + sync.error
      : sync.last_sync ? `ดึงล่าสุด ${fmtAgo(sync.last_sync)} · อัปเดตเองทุกนาที` : "อ่าน cookie ของ tiktok.com จาก Chrome ทุกนาที";
  }
  $("#cookie-save").disabled = true;
  $("#drop").className = "drop";
  $("#drop-text").innerHTML = "วางไฟล์ cookies.txt ที่นี่ หรือ <u>เลือกไฟล์</u>";
  $("#cookie-file").value = "";
  $("#dlg-cookies").showModal();
}
$("#btn-cookies").addEventListener("click", openCookies);

async function takeFile(file) {
  if (!file) return;
  if (file.size > 1_000_000) return toast("ไฟล์ใหญ่เกินไป ต้องเป็น cookies.txt", true);
  cookieText = await file.text();
  const ok = cookieText.includes("tiktok.com");
  $("#drop").className = "drop" + (ok ? " ready" : "");
  $("#drop-text").textContent = ok ? `${file.name} พร้อมแล้ว` : "ไฟล์นี้ไม่มี cookie ของ tiktok.com";
  $("#cookie-save").disabled = !ok;
}
$("#cookie-file").addEventListener("change", (e) => takeFile(e.target.files[0]));
const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); takeFile(e.dataTransfer.files[0]); });

$("#cookie-form").addEventListener("submit", async (e) => {
  if (e.submitter?.value !== "default") return;
  e.preventDefault();
  $("#cookie-save").disabled = true;
  try {
    await api("/api/cookies", { text: cookieText });
    $("#dlg-cookies").close();
    toast("บันทึก cookie แล้ว กำลังตรวจสอบบัญชี…");
    setTimeout(refreshState, 300);
  } catch (err) {
    toast(err.message, true);
    $("#cookie-save").disabled = false;
  }
});

$("#rec-search").addEventListener("input", () => renderRecs());

// ---------- start ----------
refreshState().then(refreshRecs);
setInterval(refreshState, 2000);
setInterval(refreshRecs, 10000);
