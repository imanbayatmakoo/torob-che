/* Torob shopping companion — vanilla JS, RTL, mobile-first. All cards render from tool events (never LLM text). */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const feed = $("#feed"), chipsEl = $("#chips"), input = $("#text"), sendBtn = $("#send"), inst = $("#inst");
  let sessionId = localStorage.getItem("tsc_session") || null;
  let busy = false, statusEl = null, currentPhone = null, lastStage = 0;

  const FA = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const toman = (n) => (n == null ? "قیمت ثبت نشده" : FA((n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1)) + " میلیون تومان");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const DIM_FA = { camera: "دوربین", battery: "باتری", speed: "سرعت", storage: "حافظه" };
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const add = (node) => { feed.appendChild(node); requestAnimationFrame(() => (feed.scrollTop = feed.scrollHeight)); return node; };

  function welcome() {
    feed.innerHTML = "";
    add(el(`<div class="welcome">
      <h2>سلام! 👋 دنبال گوشی هستید؟</h2>
      <div>من کمک می‌کنم از بین صدها مدل، گوشی مناسب را پیدا کنید و بدانید <b>کدام مغازهٔ پاساژ</b> دارد، کجاست و قبل از رفتن موجودی‌اش را چک کنید.</div>
      <ol><li>بگویید بودجه چقدر است و برای چه کسی/چه کاری</li><li>اگر بخواهید بگویید الان چه گوشی‌ای دارید و چه مشکلی دارد</li><li>بقیه‌اش با من 🙂</li></ol>
    </div>`));
    setChips(["برای مامانم گوشی تا ۷۰ میلیون، دوربین و باتری خوب", "تا ۲۰ میلیون", "گوشی فعلیم A10 است، شارژش زود تموم میشه", "حدود ۱۰۰ میلیون، برای بازی"]);
    setStage(0);
  }

  function setChips(list) {
    chipsEl.innerHTML = "";
    (list || []).forEach((c) => { const b = el(`<button>${esc(c)}</button>`); b.onclick = () => send(c); chipsEl.appendChild(b); });
  }

  function setStage(s) {
    lastStage = Math.max(lastStage, s);
    document.querySelectorAll(".step").forEach((x) => {
      const n = +x.dataset.s;
      x.classList.toggle("active", n === s);
      x.classList.toggle("done", n < s);
    });
  }

  function renderProfile(p, visitLabel) {
    const box = $("#profile"); if (!p) return;
    const parts = [];
    if (p.budget_max) parts.push(`💰 تا ${toman(p.budget_max)}`);
    if (p.for_whom) parts.push(`👤 ${esc(p.for_whom)}`);
    if (p.priorities?.length) parts.push("⭐ " + p.priorities.map((d) => DIM_FA[d]).join("، "));
    if (p.current_phone) parts.push(`📱 الان: ${esc(p.current_phone)}`);
    if (p.installment_only) parts.push("💳 اقساطی");
    if (p.area) parts.push(`📍 ${p.area === "شیخ هادی" ? "جمهوری / شیخ هادی" : esc(p.area)}`);
    if (visitLabel) parts.push(`🕔 ${esc(visitLabel)}`);
    box.innerHTML = parts.map((x) => `<span class="pchip">${x}</span>`).join("");
    inst.checked = !!p.installment_only;
  }

  function status(text) {
    if (!statusEl) statusEl = add(el(`<div class="status"><span class="dot"></span><span></span></div>`));
    statusEl.lastElementChild.textContent = text;
    feed.appendChild(statusEl);
  }
  function clearStatus() { statusEl?.remove(); statusEl = null; }

  // ------------------------------------------------------------ cards
  function bars(r, vs, cur) {
    return `<div class="bars">${["camera", "battery", "speed", "storage"].map((d) => {
      const v = r[d]; const c = cur?.ratings?.[d];
      const delta = vs && vs[d] != null ? `<span class="delta ${vs[d] < 0 ? "neg" : ""}">${vs[d] >= 0 ? "▲" : "▼"} ${FA(Math.abs(vs[d]).toFixed(1))}</span>` :
        (v == null ? `<span class="delta na">نامشخص</span>` : `<span class="delta na">${FA(v.toFixed(1))}/۱۰</span>`);
      return `<div class="bar"><span>${DIM_FA[d]}</span><div class="track">${v != null ? `<div class="fill" style="width:${v * 10}%"></div>` : ""}${c != null ? `<div class="cur" style="right:${c * 10}%" title="گوشی فعلی"></div>` : ""}</div>${delta}</div>`;
    }).join("")}</div>`;
  }

  function freshBadge(f) {
    const cls = { fresh: "ok", recent: "info", old: "warn", unknown: "" }[f.tier] || "";
    return `<span class="badge ${cls}">🕒 ${esc(f.label)}</span>`;
  }

  function renderCurrent(d) {
    if (!d.found) {
      add(el(`<div class="card"><span class="role alternative">گوشی فعلی</span><div class="meta" style="margin-top:6px">${esc(d.note)}</div></div>`));
      return;
    }
    currentPhone = d;
    const s = d.specs || {};
    add(el(`<div class="card"><span class="role alternative">نقطهٔ شروع: گوشی فعلی شما</span>
      <div class="phead">${d.image ? `<img src="${esc(d.image)}" alt="">` : `<div style="font-size:40px">📱</div>`}
      <div><div class="pname">${esc(d.name)}</div><div class="meta">${d.year ? "سال " + FA(d.year) + " · " : ""}${s.battery_mah ? "باتری " + FA(s.battery_mah) + " · " : ""}${s.main_mp ? "دوربین " + FA(s.main_mp) + "MP" : ""}</div></div></div>
      ${bars(d.ratings, null, null)}
      <div class="badges"><span class="badge info">منبع: ${esc(d.source_label)}</span></div></div>`));
  }

  function renderRecs(data, cur) {
    if (!data.picks.length) { add(el(`<div class="card"><div class="meta">${esc(data.note || "پیشنهادی پیدا نشد")}</div></div>`)); return; }
    add(el(`<div class="section-title"><span>مرحلهٔ ۱ · ${FA(data.picks.length)} پیشنهاد از بین ${FA(data.considered_models)} مدل در بازار</span></div>`));
    if (cur?.found) add(el(`<div class="legend">نوار‌ها امتیاز ۰ تا ۱۰ هستند؛ خط سیاه = گوشی فعلی شما · ▲ یعنی چقدر بهتر</div>`));
    if (data.relaxed) add(el(`<div class="sim">در بودجهٔ دقیق شما گزینهٔ خوبی نبود؛ تا ۱۵٪ بالاتر را هم نگاه کردم.</div>`));
    if (data.guardrail_removed) add(el(`<div class="legend">🛡️ ${FA(data.guardrail_removed)} مدل که در مشکلِ گوشی فعلی‌تان بهتر نبودند حذف شدند.</div>`));
    data.picks.forEach((c) => {
      const node = add(el(`<div class="card ${c.role === "best" ? "best" : ""}">
        <span class="role ${c.role}">${esc(c.role_label)}</span>
        <div class="phead"><img src="${esc(c.image)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
          <div><div class="pname">${esc(c.name)}</div>
          <div class="price">${esc(c.price_label.replace(/[\d.,]+/g, (m) => FA(m)))}</div>
          <div class="meta">${c.variant.storage_gb ? FA(c.variant.storage_gb) + " گیگ" : ""}${c.variant.ram_gb ? " · رم " + FA(c.variant.ram_gb) : ""} · در ${FA(c.n_shops)} مغازهٔ حضوری${c.n_inst_shops ? ` (${FA(c.n_inst_shops)} اقساطی)` : ""}</div></div></div>
        ${bars(c.ratings, c.vs_current, cur)}
        <ul class="reasons">${c.reasons.map((r) => `<li>${/[A-Za-z]/.test(r) ? `<bdi dir="ltr">${esc(r.replace(/^تراشه /, ""))}</bdi> <span class="meta">(تراشه)</span>` : esc(r).replace(/\d[\d,.]*/g, (m) => FA(m))}</li>`).join("")}</ul>
        <div class="badges">${freshBadge(c.freshness)}<span class="badge">📦 موجودی تأیید نشده</span>
          <span class="badge ${c.confidence.known >= 7 ? "ok" : "warn"}" title="${esc(c.confidence.filled_from_variant ? "بعضی مشخصات از نسخهٔ دیگر همین مدل" : "")}">📊 ${esc(c.confidence.label.replace(/\d+/g, (m) => FA(m)))}</span>
          ${c.speed_basis === "ram_estimate" ? `<span class="badge warn">سرعت تخمینی (از رم)</span>` : ""}</div>
        <div class="actions"><button class="primary">کدام مغازه‌ها دارند؟</button></div></div>`));
      node.querySelector(".primary").onclick = () => action({ type: "select_model", model_key: c.model_key, name: c.name, storage_gb: c.variant.storage_gb });
    });
    const cmp = add(el(`<div class="actions"><button class="secondary">مقایسهٔ کنار هم</button></div>`));
    cmp.querySelector("button").onclick = () => action({ type: "compare", model_keys: data.picks.map((p) => p.model_key) });
  }

  function renderCompare(rows) {
    if (!rows.length) return;
    const dims = [["min_price", "قیمت از", (v) => toman(v), "min"], ["n_shops", "مغازه‌ها", FA, "max"], ["camera", "دوربین", (v) => v == null ? "—" : FA(v), "max"],
      ["battery", "باتری", (v) => v == null ? "—" : FA(v), "max"], ["speed", "سرعت", (v) => v == null ? "—" : FA(v), "max"],
      ["battery_mah", "میلی‌آمپر", (v) => v == null ? "—" : FA(v), "max"], ["main_mp", "مگاپیکسل", (v) => v == null ? "—" : FA(v), "max"]];
    const head = rows.map((r) => `<th style="direction:ltr">${esc(r.name)}</th>`).join("");
    const body = dims.map(([k, label, f, best]) => {
      const vals = rows.map((r) => r[k]).filter((v) => v != null);
      const win = vals.length ? (best === "min" ? Math.min(...vals) : Math.max(...vals)) : null;
      return `<tr><td>${label}</td>${rows.map((r) => `<td class="${r[k] === win && vals.length > 1 ? "win" : ""}">${f(r[k])}</td>`).join("")}</tr>`;
    }).join("");
    add(el(`<div class="card"><span class="role alternative">مقایسه</span><table class="cmp"><tr><th></th>${head}</tr>${body}</table></div>`));
  }

  function renderShops(ev) {
    const d = ev.data, m = ev.model;
    setStage(3);
    add(el(`<div class="section-title"><span>مرحلهٔ ۲ و ۳ · ${FA(d.n)} مغازهٔ حضوری برای <b style="direction:ltr;display:inline-block">${esc(m.name)}</b></span></div>`));
    if (ev.fell_back === "area_removed") add(el(`<div class="sim">در منطقهٔ انتخابی شما مغازه‌ای نبود؛ همهٔ مناطق را نشان می‌دهم.</div>`));
    if (!d.n) { add(el(`<div class="card meta">هیچ مغازهٔ حضوری‌ای این مدل را ثبت نکرده است.</div>`)); return; }
    add(el(`<div class="legend">ترتیب بر اساس قیمت، تازگی قیمت، گارانتی، رجیستری${ev.visit_label ? "، باز بودن در " + esc(ev.visit_label) : ""} و اقساط. روی «چرا؟» بزنید.</div>`));
    const top = d.shops.slice(0, 6);
    top.forEach((s) => {
      const w = s.warranty || {};
      const wb = { official: ["ok", "گارانتی شرکتی"], store_test: ["warn", "فقط تست"], none: ["bad", "بدون گارانتی"], other: ["info", "گارانتی دیگر"], unknown: ["", "گارانتی نامشخص"] }[w.kind || "unknown"];
      const ob = { open: "ok", listed: "", unknown: "", closed: "bad", closed_then: "bad" }[s.open.status];
      const reg = { registered: ["ok", "رجیستر شده"], not_registered: ["bad", "رجیستر نشده"], unknown: ["", "رجیستری نامشخص"] }[s.registry || "unknown"];
      const parts = Object.entries(s.score_parts).map(([k, v]) => `${{ price: "قیمت", freshness: "تازگی", warranty: "گارانتی", registry: "رجیستری", open: "ساعت کاری", installment: "اقساط", budget: "بودجه" }[k]}: ${FA(v)}`).join(" · ");
      add(el(`<div class="card shop"><div class="rank">${FA(s.rank)}</div>
        <div><div><b>${esc(s.shop_name)}</b></div>
          <div class="addr">📍 ${esc([s.passage, s.floor, s.unit].filter(Boolean).join(" · ") || s.address)}</div>
          <div class="badges">${freshBadge(s.freshness)}<span class="badge">📦 ${esc(s.stock.label)}</span>
            <span class="badge ${wb[0]}">${wb[1]}${w.months ? " " + FA(w.months) + " ماهه" : ""}</span><span class="badge ${reg[0]}">${reg[1]}</span>
            <span class="badge ${ob}">${esc(s.open.label.replace(/\d/g, (x) => FA(x)))}</span>${s.installment ? `<span class="badge ok">💳 اقساط: ${esc(s.payment_providers.join("، ") || "دارد")}</span>` : ""}</div>
          <details><summary>چرا رتبهٔ ${FA(s.rank)}؟ (امتیاز ${FA(s.score)})</summary>${parts}</details></div>
        <div class="sprice ${s.over_budget ? "meta" : ""}">${toman(s.price)}${s.over_budget ? "<br><small>بالای بودجه</small>" : ""}</div></div>`));
    });
    if (d.route?.length) {
      add(el(`<div class="card"><span class="role">مسیر پیشنهادی در پاساژ (قبل از تماس)</span><ol class="route">${d.route.map((r) => `<li><b>${esc(r.shop_name)}</b> — ${esc([r.passage, r.floor, r.unit].filter(Boolean).join("، "))}</li>`).join("")}</ol></div>`));
    }
    const act = add(el(`<div class="card"><div>⚠️ قیمت ثبت‌شده یعنی موجودی نیست. بگذارید قبل از رفتن با مغازه‌ها تماس بگیرم.</div><div class="actions"><button class="primary">📞 تماس با مغازه‌ها (شبیه‌سازی)</button></div></div>`));
    act.querySelector("button").onclick = () => action({ type: "contact", shop_ids: top.slice(0, 3).map((s) => s.shop_id) });
  }

  function renderContactStart(ev) {
    setStage(4);
    add(el(`<div class="section-title"><span>مرحلهٔ ۴ · تماس با مغازه‌ها</span></div>`));
    add(el(`<div class="sim">🤖 ${esc(ev.note)}</div>`));
  }

  function renderCall(c) {
    const ic = { confirmed: "✅", out_of_stock: "❌", no_answer: "📵", no_installment: "⚠️" }[c.status];
    const priceNote = c.price_changed && c.confirmed_price ? `<span class="badge warn">قیمت عوض شده: ${toman(c.listed_price)} ← ${toman(c.confirmed_price)}</span>` : (c.confirmed_price ? `<span class="badge ok">قیمت تأییدشده: ${toman(c.confirmed_price)}</span>` : "");
    add(el(`<div class="card call ${c.status}"><div class="ic">${ic}</div><div>
      <div><b>${esc(c.shop_name)}</b> · <span class="meta">${esc(c.status_label)}</span></div>
      <div class="bubble q">🗣️ ${esc(c.question)}</div>
      ${c.reply ? `<div class="bubble">🏪 ${esc(c.reply)}</div>` : `<div class="bubble">… بوق آزاد، کسی جواب نداد. سراغ مغازهٔ بعدی می‌روم.</div>`}
      <div class="badges">${priceNote}${c.installment === true ? `<span class="badge ok">💳 اقساط دارد</span>` : c.installment === false ? `<span class="badge warn">فقط نقد</span>` : ""}<span class="badge">شبیه‌سازی</span></div></div></div>`));
  }

  function renderPlan(p) {
    if (!p.stops.length) {
      add(el(`<div class="card plan"><h3>هنوز مغازهٔ تأییدشده‌ای نداریم</h3><div class="meta">مدل دیگری را امتحان کنیم یا شرط اقساط را برداریم؟</div></div>`));
      return;
    }
    const best = p.stops.reduce((a, b) => (a.confirmed_price ?? 1e15) <= (b.confirmed_price ?? 1e15) ? a : b);
    add(el(`<div class="card plan"><span class="role cheaper">برنامهٔ خرید شما</span>
      <h3 style="margin-top:6px;direction:ltr;text-align:right">${esc(p.model.name)}</h3>
      <div class="meta">${p.visit_label ? "🕔 " + esc(p.visit_label) + " · " : ""}بهترین قیمت تأییدشده: <b>${toman(best.confirmed_price)}</b> در ${esc(best.shop_name)}</div>
      <ol class="route">${p.stops.map((s) => `<li><b>${esc(s.shop_name)}</b> — ${toman(s.confirmed_price)}${s.installment ? " · 💳" : ""}<br><span class="meta">${esc([s.passage, s.floor, s.unit].filter(Boolean).join("، ") || s.address)}</span></li>`).join("")}</ol>
      ${p.backup.length ? `<div class="meta" style="margin-top:6px">پشتیبان: ${p.backup.map((b) => esc(b.shop_name) + " (" + esc(b.status_label) + ")").join("، ")}</div>` : ""}
      <div style="margin-top:8px"><b>چک‌لیست قبل از پرداخت</b></div><ul class="check">${p.checklist.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
      <div class="badges"><span class="badge">تماس‌ها شبیه‌سازی شده‌اند</span></div></div>`));
  }

  // ------------------------------------------------------------ transport
  function handle(ev) {
    switch (ev.type) {
      case "session": sessionId = ev.session_id; localStorage.setItem("tsc_session", sessionId); break;
      case "status": status(ev.text); break;
      case "user_echo": break;
      case "message": clearStatus(); if (ev.text) add(el(`<div class="msg bot"></div>`)).textContent = ev.text; break;
      case "profile": renderProfile(ev.profile, ev.visit_label); break;
      case "current_phone": clearStatus(); renderCurrent(ev.data); break;
      case "recommendations": clearStatus(); setStage(1); renderRecs(ev.data, ev.current); break;
      case "compare": clearStatus(); renderCompare(ev.data); break;
      case "shops": clearStatus(); renderShops(ev); break;
      case "contact_start": clearStatus(); renderContactStart(ev); break;
      case "contact_result": clearStatus(); renderCall(ev.data); status("تماس با مغازهٔ بعدی…"); break;
      case "plan": clearStatus(); renderPlan(ev.data); break;
      case "chips": setChips(ev.chips); break;
      case "stage": renderProfile(ev.profile, ev.visit_label); if (ev.stage >= lastStage) setStage(ev.stage === 2 ? 3 : ev.stage); break;
      case "done": clearStatus(); break;
    }
  }

  async function post(body) {
    if (busy) return; busy = true; sendBtn.disabled = true;
    try {
      const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, ...body }) });
      const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
      for (;;) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          if (chunk.startsWith("data: ")) { try { handle(JSON.parse(chunk.slice(6))); } catch (e) { console.error(e); } }
        }
      }
    } catch (e) {
      clearStatus(); add(el(`<div class="msg bot">اتصال قطع شد؛ دوباره تلاش کنید.</div>`));
    } finally { busy = false; sendBtn.disabled = false; clearStatus(); }
  }

  function send(text) {
    text = (text ?? input.value).trim(); if (!text || busy) return;
    input.value = "";
    add(el(`<div class="msg user"></div>`)).textContent = text;
    post({ text });
  }
  function action(a) {
    if (busy) return;
    const label = { select_model: `${a.name} را انتخاب کردم؛ کدام مغازه‌ها دارند؟`, contact: "با مغازه‌ها تماس بگیر", compare: "مقایسه‌شان کن",
      toggle_installment: a.value ? "فقط اقساطی" : "اقساط مهم نیست" }[a.type];
    add(el(`<div class="msg user"></div>`)).textContent = label;
    post({ action: a });
  }

  sendBtn.onclick = () => send();
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  inst.onchange = () => action({ type: "toggle_installment", value: inst.checked });
  $("#reset").onclick = () => { localStorage.removeItem("tsc_session"); sessionId = null; currentPhone = null; lastStage = 0; $("#profile").innerHTML = ""; inst.checked = false; welcome(); };
  localStorage.removeItem("tsc_session"); sessionId = null;
  welcome();
})();
