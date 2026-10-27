"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICON = {
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z"/></svg>',
  stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1"/></svg>',
  film: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M10 9.5v5l4-2.5z"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/></svg>',
  merge: '<svg viewBox="0 0 24 24"><path d="M6 3v6a6 6 0 0 0 6 6h0a6 6 0 0 1 6 6M18 3v6a6 6 0 0 1-3 5.2"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  heart: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z"/></svg>',
  users: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/></svg>',
  gift: '<svg viewBox="0 0 24 24"><rect x="3" y="8" width="18" height="5" rx="1"/><path d="M5 13v7h14v-7M12 8v12M12 8S10.5 3 8 4s0 4 4 4Zm0 0s1.5-5 4-4 0 4-4 4Z"/></svg>',
  gem: '<svg viewBox="0 0 24 24"><path d="M6 3h12l4 6-10 12L2 9z"/><path d="M2 9h20M12 21 8 9l4-6 4 6z"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
};

const AVATAR_COLORS = [
  ["#25f4ee", "#3b82f6"], ["#fe2c55", "#f97316"], ["#a855f7", "#ec4899"],
  ["#22c55e", "#14b8a6"], ["#f59e0b", "#ef4444"], ["#6366f1", "#25f4ee"],
];

let state = null;
let recs = { items: [], free: 0 };
let serverOffset = 0; // server clock minus browser clock

// ---------- formatting ----------

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return (n / 1024 ** i).toFixed(i >= 3 ? 2 : i ? 1 : 0) + " " + u[i];
}
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const fmtNum = (n) => (n === null || n === undefined ? "–" : compact.format(n));

function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
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
  if (d <= 5) return "เร็ว ๆ นี้";
  if (d < 60) return `อีก ${Math.ceil(d)} วินาที`;
  return `อีก ${Math.ceil(d / 60)} นาที`;
}
function fmtDate(ts) {
  return new Date(ts * 1000).toLocaleString("th-TH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
const now = () => Date.now() / 1000 + serverOffset;

function avatarStyle(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const [a, b] = AVATAR_COLORS[h % AVATAR_COLORS.length];
  return `--av: linear-gradient(135deg, ${a}, ${b})`;
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
  } catch (e) {
    $("#account").className = "pill pill-warn";
    $("#account").innerHTML = '<span class="dot"></span><span>เชื่อมต่อโปรแกรมไม่ได้</span>';
  }
}
async function refreshRecs() {
  try {
    recs = await api("/api/recordings");
    renderRecs();
    renderStats();
  } catch { /* shown via state polling */ }
}

// ---------- render ----------

function render() {
  renderAccount();
  renderBanner();
  renderChannels();
  renderEvents();
  renderStats();
  const s = state.settings;
  $("#interval-note").textContent = `เช็กสถานะแต่ละช่องทุก ${Math.round(s.check_min / 60)}–${Math.round(s.check_max / 60)} นาที`;
}

function renderAccount() {
  const a = state.account, el = $("#account");
  const noCookies = state.pause.reason === "no_cookies";
  let cls = "pill pill-muted", text = "กำลังตรวจ cookie…";
  if (noCookies) { cls = "pill pill-warn"; text = "ยังไม่มี cookie"; }
  else if (a.state === "ok") { cls = "pill pill-ok"; text = "@" + a.name; }
  else if (a.state === "logged_out") { cls = "pill pill-warn"; text = "cookie หมดอายุ"; }
  else if (a.state === "unknown") { cls = "pill pill-warn"; text = "ตรวจ cookie ไม่ได้"; }
  el.className = cls;
  el.title = a.error || "";
  el.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>`;
}

function renderBanner() {
  const p = state.pause, el = $("#banner");
  let title = "", body = "", action = false;
  if (p.reason === "no_cookies") {
    title = "ยังไม่ได้ใส่ cookie";
    body = "อัปโหลดไฟล์ cookies.txt จากบัญชี TikTok ของคุณเพื่อเริ่มเฝ้าดูช่อง";
    action = true;
  } else if (p.reason === "captcha") {
    title = "TikTok ขอให้ยืนยันตัวตน (CAPTCHA)";
    body = `หยุดเช็กชั่วคราว เหลือ ${fmtClock(p.seconds)} · เปิด tiktok.com ในเบราว์เซอร์ ยืนยันตัวตนเอง แล้ว export cookies.txt ใหม่มาอัปโหลด`;
    action = true;
  } else if (p.reason) {
    title = "TikTok ขอให้ช้าลง (HTTP 429)";
    body = `รอสักครู่แล้วจะทำงานต่อเอง เหลือ ${fmtClock(p.seconds)}`;
  } else if (state.account.state === "logged_out") {
    title = "cookie หมดอายุหรือยังไม่ได้ล็อกอิน";
    body = "ช่องที่ต้องล็อกอินหรือจำกัดอายุอาจดูไม่ได้ ล็อกอิน tiktok.com แล้ว export cookies.txt ใหม่";
    action = true;
  }
  el.hidden = !title;
  if (!title) return;
  el.innerHTML = `${ICON.warn}<div><b>${esc(title)}</b><p>${esc(body)}</p></div>` +
    (action ? '<button class="btn btn-primary btn-sm" data-open-cookies>อัปโหลด cookie</button>' : "");
}

function channelBadge(c) {
  if (c.recording) {
    const label = { reconnecting: "กำลังเชื่อมต่อใหม่", merging: "กำลังรวมไฟล์", starting: "กำลังเริ่ม" }[c.recording.phase] || "กำลังบันทึก";
    return `<span class="badge badge-rec"><i></i>${label}</span>`;
  }
  if (c.paused) return '<span class="badge badge-off">หยุดเฝ้า</span>';
  if (c.status === "live") return '<span class="badge badge-live"><i></i>LIVE</span>';
  if (c.status === "error") return '<span class="badge badge-err"><i></i>มีปัญหา</span>';
  if (c.status === "offline") return '<span class="badge badge-off"><i></i>ออฟไลน์</span>';
  return '<span class="badge badge-wait"><i></i>รอเช็ก</span>';
}

// Cards re-render every poll, so only draw an avatar once the browser has it cached
const avatarCache = {};
function avatarImg(url) {
  if (!url) return "";
  if (avatarCache[url] === "ok") return `<img src="${esc(url)}" alt="" referrerpolicy="no-referrer">`;
  if (avatarCache[url] === undefined) {
    avatarCache[url] = "loading";
    const img = new Image();
    img.referrerPolicy = "no-referrer";
    img.onload = () => { avatarCache[url] = "ok"; if (state) renderChannels(); };
    img.onerror = () => { avatarCache[url] = "error"; };
    img.src = url;
  }
  return "";
}

function renderChannels() {
  const el = $("#channels");
  const list = [...state.channels].sort((a, b) => (!!b.recording - !!a.recording) || a.username.localeCompare(b.username));
  if (!list.length) {
    el.innerHTML = '<div class="empty"><b>ยังไม่มีช่อง</b>พิมพ์ชื่อผู้ใช้ TikTok ด้านบนแล้วกด “เพิ่มช่อง”</div>';
    return;
  }
  el.innerHTML = list.map((c) => {
    const u = esc(c.username), r = c.recording;
    let body;
    const st = (r && r.stats) || {};
    const viewers = st.viewers ?? c.viewers;
    if (r) {
      body = `${c.title ? `<p class="live-title" title="${esc(c.title)}">${esc(c.title)}</p>` : ""}
        <div class="live-stats">
          <div title="คนดูตอนนี้${st.peak_viewers ? ` · สูงสุด ${st.peak_viewers.toLocaleString()}` : ""}">${ICON.eye}<b>${fmtNum(viewers)}</b><span>คนดู</span></div>
          <div class="likes" title="${st.likes != null ? st.likes.toLocaleString() : ""}">${ICON.heart}<b>${fmtNum(st.likes)}</b><span>กดใจ</span></div>
          <div title="คนเข้าดูทั้งหมด">${ICON.users}<b>${fmtNum(st.total_viewers)}</b><span>เข้าดูทั้งหมด</span></div>
        </div>
        <div class="gift-row">
          <span title="จำนวนคนที่ส่งของขวัญ (รวมทั้งไลฟ์)">${ICON.gift}<b>${fmtNum(st.gift_senders)}</b> คนส่ง</span>
          <span title="${st.diamonds != null ? st.diamonds.toLocaleString() + " เพชร" : ""}">${ICON.gem}<b>${fmtNum(st.diamonds)}</b> เพชร</span>
        </div>
        <div class="rec-info">
        <div><span>เวลา</span><b data-since="${r.started_at}">${fmtClock(now() - r.started_at)}</b></div>
        <div><span>ขนาด</span><b>${fmtBytes(r.bytes)}</b></div>
        <div><span>คุณภาพ</span><b>${esc(r.quality || "–")}</b></div></div>`;
    } else {
      const lines = [];
      if (c.paused) lines.push("หยุดเฝ้าชั่วคราว กด “เฝ้าต่อ” เพื่อเริ่มใหม่");
      else {
        lines.push(c.last_check ? `เช็กล่าสุด ${fmtAgo(c.last_check)}` : "ยังไม่ได้เช็ก");
        if (c.next_check && !state.pause.reason) lines.push(`ครั้งถัดไป <span data-next="${c.next_check}">${fmtIn(c.next_check)}</span>`);
      }
      if (c.error) lines.push(`<span class="err" title="${esc(c.error)}">${esc(c.error)}</span>`);
      body = `<div class="card-meta">${lines.map((l) => `<span>${l}</span>`).join("")}</div>`;
    }
    const toggle = r
      ? `<button class="btn btn-sm" data-act="pause" data-user="${u}">${ICON.stop}หยุดบันทึก</button>`
      : c.paused
        ? `<button class="btn btn-sm" data-act="resume" data-user="${u}">${ICON.play}เฝ้าต่อ</button>`
        : `<button class="btn btn-sm" data-act="pause" data-user="${u}">${ICON.pause}หยุดเฝ้า</button>`;
    return `<article class="card ${r ? "is-rec" : ""} ${c.paused ? "is-paused" : ""}">
      <div class="card-top">
        <div class="avatar" style="${avatarStyle(c.username)}">${esc(c.username[0].toUpperCase())}${avatarImg(c.avatar)}</div>
        <div class="card-name"><b>${esc(c.nickname || "@" + c.username)}</b><a href="https://www.tiktok.com/@${encodeURIComponent(c.username)}/live" target="_blank" rel="noopener noreferrer">${c.nickname ? `@${u} · ` : ""}เปิดใน TikTok ↗</a></div>
        ${channelBadge(c)}
      </div>
      ${body}
      <div class="card-actions">
        ${r ? "" : `<button class="btn btn-sm" data-act="check" data-user="${u}">${ICON.refresh}เช็กตอนนี้</button>`}
        ${toggle}
        <button class="btn btn-sm btn-danger" data-act="remove" data-user="${u}" aria-label="ลบ @${u}" title="ลบช่อง">${ICON.trash}</button>
      </div>
    </article>`;
  }).join("");
}

function renderRecs() {
  const el = $("#recordings");
  const q = $("#rec-search").value.trim().toLowerCase();
  const items = recs.items.filter((r) => !q || r.name.toLowerCase().includes(q) || r.user.toLowerCase().includes(q));
  if (!items.length) {
    el.innerHTML = `<div class="empty"><b>${q ? "ไม่พบไฟล์" : "ยังไม่มีไฟล์"}</b>${q ? "ลองค้นหาคำอื่น" : "ไฟล์จะขึ้นที่นี่เมื่อมีช่องเริ่มไลฟ์"}</div>`;
    return;
  }
  el.innerHTML = items.map((r) => {
    const path = encodeURI(r.path);
    if (r.kind === "video") {
      return `<div class="rec">
        <div class="rec-thumb video">${ICON.film}</div>
        <div class="rec-main"><b>${esc(r.name)}</b><span>@${esc(r.user)} · ${fmtDate(r.time)} · ${fmtBytes(r.size)}</span></div>
        <div class="rec-actions">
          <button class="btn btn-sm" data-play="${esc(r.path)}" data-title="${esc(r.name)}">${ICON.play}<span class="label">ดู</span></button>
          <a class="btn btn-sm" href="/media/${path}?download=1" aria-label="ดาวน์โหลด">${ICON.download}</a>
        </div></div>`;
    }
    return `<div class="rec">
      <div class="rec-thumb ${r.active ? "active" : ""}">${ICON.layers}</div>
      <div class="rec-main"><b>${esc(r.name)}</b><span>@${esc(r.user)} · ${r.segments} ส่วน · ${fmtBytes(r.size)}${r.active ? " · กำลังบันทึก" : ""}</span></div>
      <div class="rec-actions">${r.active ? "" : `<button class="btn btn-sm" data-merge="${esc(r.path)}">${ICON.merge}<span class="label">รวมเป็น MP4</span></button>`}</div>
    </div>`;
  }).join("");
}

function renderEvents() {
  const ev = state.events;
  $("#events").innerHTML = ev.length
    ? ev.map((e) => `<li>${esc(e.text)}<time>${fmtDate(e.time)}</time></li>`).join("")
    : '<li class="muted">ยังไม่มีกิจกรรม</li>';
}

function renderStats() {
  if (state) {
    $("#s-channels").textContent = state.channels.length;
    $("#s-recording").textContent = state.channels.filter((c) => c.recording).length;
  }
  $("#s-files").textContent = recs.items.filter((r) => r.kind === "video").length;
  $("#s-free").textContent = recs.free ? fmtBytes(recs.free) : "–";
}

// live counters between polls
setInterval(() => {
  document.querySelectorAll("[data-since]").forEach((el) => { el.textContent = fmtClock(now() - +el.dataset.since); });
  document.querySelectorAll("[data-next]").forEach((el) => { el.textContent = fmtIn(+el.dataset.next); });
}, 1000);

// ---------- actions ----------

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#add-input");
  const name = input.value.trim().replace(/^@/, "").replace(/^https?:\/\/(www\.)?tiktok\.com\/@/, "").split(/[/?]/)[0];
  if (!name) return input.focus();
  try {
    const r = await api("/api/channels", { username: name });
    input.value = "";
    toast(`เพิ่ม @${r.username} แล้ว`);
    refreshState();
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("click", async (e) => {
  const act = e.target.closest("[data-act]");
  if (act) {
    const { act: action, user } = act.dataset;
    if (action === "remove" && !confirm(`ลบ @${user} ออกจากรายการเฝ้าดู?\n(ไฟล์ที่บันทึกไว้แล้วจะไม่ถูกลบ)`)) return;
    if (action === "pause" && act.textContent.includes("หยุดบันทึก") && !confirm(`หยุดบันทึก @${user}?\nไฟล์ที่บันทึกไปแล้วจะถูกเก็บไว้ และช่องนี้จะหยุดเฝ้าจนกว่าจะกด “เฝ้าต่อ”`)) return;
    act.disabled = true;
    try {
      await api(`/api/channels/${encodeURIComponent(user)}/${action}`, {});
      const msg = { remove: `ลบ @${user} แล้ว`, check: `กำลังเช็ก @${user}`, pause: `หยุด @${user} แล้ว`, resume: `เฝ้าดู @${user} ต่อแล้ว` }[action];
      toast(msg);
      refreshState();
      if (action === "pause") setTimeout(refreshRecs, 1500);
    } catch (err) { toast(err.message, true); act.disabled = false; }
    return;
  }
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
    merge.lastElementChild.textContent = "กำลังรวม…";
    try {
      await api("/api/merge", { path: merge.dataset.merge });
      toast("รวมไฟล์เสร็จแล้ว");
    } catch (err) { toast(err.message, true); }
    refreshRecs();
    return;
  }
  if (e.target.closest("[data-open-cookies]")) openCookies();
});

// video dialog
function closeVideo() { const v = $("#video"); v.pause(); v.removeAttribute("src"); v.load(); $("#dlg-video").close(); }
$("#video-close").addEventListener("click", closeVideo);
$("#dlg-video").addEventListener("click", (e) => { if (e.target.id === "dlg-video") closeVideo(); });
$("#dlg-video").addEventListener("cancel", (e) => { e.preventDefault(); closeVideo(); });

// cookie dialog
let cookieText = "";
function openCookies() {
  cookieText = "";
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

$("#rec-search").addEventListener("input", renderRecs);

// ---------- start ----------
refreshState();
refreshRecs();
setInterval(refreshState, 2000);
setInterval(refreshRecs, 10000);
