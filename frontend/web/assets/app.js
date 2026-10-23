/* Torob shopping companion — vanilla JS, RTL, mobile-first. All cards render from tool events (never LLM text). */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const feed = $("#feed"), chipsEl = $("#chips"), input = $("#text"), sendBtn = $("#send"), inst = $("#inst"), areaSel = $("#area");
  let sessionId = localStorage.getItem("torob_che_session") || null;
  let busy = false, statusEl = null, currentPhone = null, lastStage = 0;

  const FA = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const toman = (n) => (n == null ? "قیمت ثبت نشده" : FA((n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1)) + " میلیون تومان");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const DIM_FA = { camera: "دوربین", battery: "باتری", speed: "سرعت", storage: "حافظه" };
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  // Scroll policy: never follow the bottom. Once per request, bring the START of the first
  // real response node into view (status/loader nodes never trigger it). Manual scrolling cancels it.
  let awaitingScroll = false, userScrolled = false;
  const add = (node, opts = {}) => {
    feed.appendChild(node);
    if (awaitingScroll && !userScrolled && !opts.noScroll) {
      awaitingScroll = false;
      requestAnimationFrame(() => {
        if (userScrolled) return;
        const top = node.getBoundingClientRect().top - feed.getBoundingClientRect().top + feed.scrollTop - 8;
        feed.scrollTop = Math.max(0, top);
      });
    }
    return node;
  };
  const markUserScroll = () => { if (busy) userScrolled = true; };
  ["wheel", "touchmove", "pointerdown", "keydown"].forEach((t) => feed.addEventListener(t, markUserScroll, { passive: true }));

  // Theme (optional dark mode, persisted)
  const themeBtn = $("#theme");
  function applyTheme(t, save) {
    const dark = t === "dark";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    if (themeBtn) {
      themeBtn.setAttribute("aria-pressed", String(dark));
      themeBtn.setAttribute("aria-label", dark ? "بازگشت به حالت روشن" : "فعال‌سازی حالت تیره");
      themeBtn.title = dark ? "حالت روشن" : "حالت تیره";
      themeBtn.textContent = dark ? "☀️" : "🌙";
    }
    const m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = dark ? "#1b1d22" : "#d73948";
    if (save) { try { localStorage.setItem("torob_che_theme", dark ? "dark" : "light"); } catch (e) {} }
  }
  let storedTheme = null; try { storedTheme = localStorage.getItem("torob_che_theme"); } catch (e) {}
  applyTheme(storedTheme === "dark" ? "dark" : "light", false);
  if (themeBtn) themeBtn.onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);

  function welcome() {
    feed.innerHTML = "";
    add(el(`<div class="welcome">
      <h2>سلام! 👋 دنبال چه چیزی هستید؟</h2>
      <div>من کمک می‌کنم از بین هزاران کالای ترب، انتخاب درست را پیدا کنید و بدانید <b>کدام مغازهٔ حضوری</b> دارد، کجاست و قبل از رفتن موجودی‌اش را چک کنید.</div>
      <div class="mode-note">🎯 مشاور تخصصی: گوشی، هدفون، اسپیکر، دوربین مدار بسته، پاوربانک · 🔎 بقیهٔ دسته‌ها: جست‌وجو و مقایسهٔ مغازه‌ها</div>
      <ol><li>بگویید بودجه چقدر است و برای چه کسی/چه کاری</li><li>اگر بخواهید بگویید الان چه وسیله‌ای دارید و چه مشکلی دارد</li><li>بقیه‌اش با من 🙂</li></ol>
    </div>`));
    setChips(["برای مامانم گوشی تا ۷۰ میلیون، دوربین و باتری خوب", "گوشی فعلیم A10 است، شارژش زود تموم میشه",
      "هدفون بی‌سیم با حذف نویز تا ۵ میلیون", "پاوربانک سبک برای سفر تا ۲ میلیون", "دوربین مدار بسته برای حیاط", "یخچال ساید بای ساید"]);
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
    const pri = (p.priorities || []).map((d) => DIM_FA[d]).filter(Boolean);
    if (pri.length) parts.push("⭐ " + pri.join("، "));
    if (p.current_phone) parts.push(`📱 الان: ${esc(p.current_phone)}`);
    if (p.installment_only) parts.push("💳 اقساطی");
    if (p.area) parts.push(`📍 ${p.area === "شیخ هادی" ? "جمهوری / شیخ هادی" : esc(p.area)}`);
    if (visitLabel) parts.push(`🕔 ${esc(visitLabel)}`);
    box.innerHTML = parts.map((x) => `<span class="pchip">${x}</span>`).join("");
    inst.checked = !!p.installment_only;
    if (areaSel) {
      if (p.area && ![...areaSel.options].some((o) => o.value === p.area)) areaSel.appendChild(el(`<option value="${esc(p.area)}">${esc(p.area)}</option>`));
      areaSel.value = p.area || "";
    }
  }

  function status(text) {
    if (!statusEl) statusEl = add(el(`<div class="status"><span class="dot"></span><span></span></div>`), { noScroll: true });
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

  const SPEC_FA = { battery_hours: ["باتری", "ساعت"], anc: ["حذف نویز", ""], driver_mm: ["درایور", "mm"], has_mic: ["میکروفون", ""],
    weight_g: ["وزن", "گرم"], battery_mah: ["باتری", "mAh"], power_w: ["توان", "وات"], bluetooth: ["بلوتوث", ""], resolution_mp: ["رزولوشن", "MP"],
    night_range_m: ["دید در شب", "متر"], ip_water: ["ضدآب", ""], capacity_mah: ["ظرفیت", "mAh"], output_w: ["خروجی", "وات"], ports: ["درگاه", ""] };
  const specVal = (k, v) => v === true ? "دارد" : v === false ? "ندارد" : k === "anc" ? ({ active: "فعال", call_mic_only: "فقط مکالمه", none: "ندارد" }[v] || v) : k === "ip_water" ? `IPX${FA(v)}` : FA(v);
  const faNum = (t) => esc(t).replace(/\d[\d,.]*/g, (m) => FA(m));
  function renderProducts(data, cur) {
    const prods = data.products || [];
    if (!prods.length) {
      add(el(`<div class="card"><div class="meta">${esc(data.note || "با این فیلترها (بودجه/منطقه/اقساط) کالایی در مغازه‌های حضوری پیدا نشد.")}</div><div class="meta">می‌توانید بودجه را بیشتر کنید، منطقه را «همه» بگذارید یا فیلتر اقساط را بردارید.</div></div>`));
      return;
    }
    add(el(`<div class="section-title"><span>مرحلهٔ ۱ · ${FA(prods.length)} پیشنهاد از بین ${FA(data.n_candidates)} کالا${data.category ? " در «" + esc(data.category) + "»" : ""}</span></div>`));
    add(el(`<div class="mode-note">${data.expert ? "🎯 حالت تخصصی: رتبه‌بندی بر اساس مشخصات ثبت‌شده، نسبت به همین دسته. مشخصهٔ ثبت‌نشده «نامشخص» است، نه بد." : "🔎 حالت جست‌وجوی عمومی: کالای واقعی و قیمت و مغازه‌ها؛ امتیاز کیفیت برای این دسته نداریم."}</div>`));
    if (cur) add(el(`<div class="card"><span class="role alternative">نقطهٔ شروع: وسیلهٔ فعلی شما</span><div class="pname" style="margin-top:6px">${esc(cur.name)}</div><div class="badges"><span class="badge info">منبع: ${esc(cur.source_label)}</span></div></div>`));
    const roles = ["best", "cheaper", "alternative"], labels = data.expert ? ["بهترین تطابق با نیاز شما", "گزینهٔ دوم", "گزینهٔ سوم"] : ["مرتبط‌ترین", "گزینهٔ دیگر", "گزینهٔ دیگر"];
    prods.forEach((c, i) => {
      const specs = Object.entries(c.specs || {}).filter(([k]) => SPEC_FA[k]).slice(0, 6).map(([k, v]) => `<span>${SPEC_FA[k][0]}: ${specVal(k, v)} ${SPEC_FA[k][1]}</span>`).join("");
      const vs = Object.values(c.vs_current || {}).map((x) => `<li class="${x.better ? "good" : "bad"}">${esc(x.label)}: ${FA(x.current)} ← ${FA(x.new)} (${x.pct > 0 ? "+" : ""}${FA(x.pct)}٪)</li>`).join("");
      const unk = new Set(c.unknowns || []);
      const node = add(el(`<div class="card ${i === 0 ? "best" : ""}">
        <span class="role ${roles[i] || "alternative"}">${labels[i] || "گزینهٔ دیگر"}</span>
        <div class="phead">${c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : `<div style="font-size:40px">🛍️</div>`}
          <div><div class="pname">${esc(c.name)}</div><div class="price">از ${toman(c.price)}</div>
          <div class="meta">${c.brand ? esc(c.brand) + " · " : ""}در ${FA(c.n_shops)} مغازهٔ حضوری${c.n_installment_shops ? ` (${FA(c.n_installment_shops)} اقساطی)` : ""}</div></div></div>
        ${specs ? `<div class="specs">${specs}</div>` : ""}
        ${vs ? `<ul class="vs-list">${vs}</ul>` : ""}
        <ul class="reasons">${(c.reasons || []).map((r) => `<li class="${unk.has(r) ? "unknown" : ""}">${faNum(r)}</li>`).join("")}</ul>
        <div class="badges"><span class="badge">📦 موجودی تأیید نشده</span>${data.expert ? "" : `<span class="badge">بدون امتیاز کیفیت</span>`}</div>
        <div class="actions"><button class="primary">کدام مغازه‌ها دارند؟</button></div></div>`));
      node.querySelector(".primary").onclick = () => action({ type: "select_product", product_id: c.product_id, name: c.name });
    });
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
    if (!d.n) {
      const o = ev.outside_area;
      if (o && o.n) {
        const box = add(el(`<div class="card"><div>در منطقهٔ انتخابی شما مغازه‌ای این کالا را ثبت نکرده است. بیرون از این منطقه <b>${FA(o.n)}</b> مغازه دارند.</div><div class="ask"><button class="primary">همهٔ مناطق را نشان بده</button></div></div>`));
        box.querySelector("button").onclick = () => setArea("");
      } else add(el(`<div class="card meta">با این فیلترها هیچ مغازهٔ حضوری‌ای این کالا را ثبت نکرده است.</div>`));
      return;
    }
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
          ${s.blocked_reason ? `<div class="meta">⛔ ${esc(s.blocked_reason)} — در برنامهٔ تماس و مسیر نمی‌آید</div>` : ""}
          <details><summary>چرا رتبهٔ ${FA(s.rank)}؟ (امتیاز ${FA(s.score)})</summary>${parts}</details></div>
        <div class="sprice ${s.over_budget ? "meta" : ""}">${toman(s.price)}${s.over_budget ? "<br><small>بالای بودجه</small>" : ""}</div></div>`));
    });
    if (d.route?.length) {
      add(el(`<div class="card"><span class="role">مسیر پیشنهادی در پاساژ (قبل از تماس)</span><ol class="route">${d.route.map((r) => `<li><b>${esc(r.shop_name)}</b> — ${esc([r.passage, r.floor, r.unit].filter(Boolean).join("، "))}</li>`).join("")}</ol></div>`));
    }
    const ok = d.shops.filter((s) => s.actionable !== false);
    if (!ok.length) { add(el(`<div class="card meta">همهٔ این مغازه‌ها در زمان انتخابی بسته‌اند یا بالای بودجه‌اند. زمان رفتن یا بودجه را عوض کنید.</div>`)); return; }
    const act = add(el(`<div class="card"><div>⚠️ قیمت ثبت‌شده یعنی موجودی نیست. بگذارید قبل از رفتن با مغازه‌ها تماس بگیرم.</div><div class="actions"><button class="primary">📞 تماس با مغازه‌ها (شبیه‌سازی)</button></div></div>`));
    act.querySelector("button").onclick = () => action({ type: "contact", shop_ids: ok.slice(0, 3).map((s) => s.shop_id) });
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
      case "session": sessionId = ev.session_id; localStorage.setItem("torob_che_session", sessionId); break;
      case "status": status(ev.text); break;
      case "user_echo": break;
      case "message": clearStatus(); if (ev.text) add(el(`<div class="msg bot"></div>`)).textContent = ev.text; break;
      case "profile": renderProfile(ev.profile, ev.visit_label); break;
      case "current_phone": clearStatus(); renderCurrent(ev.data); break;
      case "recommendations": clearStatus(); setStage(1); renderRecs(ev.data, ev.current); break;
      case "products": clearStatus(); setStage(1); renderProducts(ev.data, ev.current); break;
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
    if (busy) return; busy = true; sendBtn.disabled = true; awaitingScroll = true; userScrolled = false;
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
    } finally { busy = false; awaitingScroll = false; sendBtn.disabled = false; clearStatus(); }
  }

  function send(text) {
    text = (text ?? input.value).trim(); if (!text || busy) return;
    input.value = "";
    add(el(`<div class="msg user"></div>`), { noScroll: true }).textContent = text;
    post({ text });
  }
  function action(a) {
    if (busy) return;
    const label = { select_product: `${a.name} را انتخاب کردم؛ کدام مغازه‌ها دارند؟`, set_area: a.value ? `فقط مغازه‌های ${a.value === "شیخ هادی" ? "جمهوری / شیخ هادی" : a.value}` : "همهٔ مناطق", select_model: `${a.name} را انتخاب کردم؛ کدام مغازه‌ها دارند؟`, contact: "با مغازه‌ها تماس بگیر", compare: "مقایسه‌شان کن",
      toggle_installment: a.value ? "فقط اقساطی" : "اقساط مهم نیست" }[a.type];
    add(el(`<div class="msg user"></div>`), { noScroll: true }).textContent = label;
    post({ action: a });
  }

  sendBtn.onclick = () => send();
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  inst.onchange = () => action({ type: "toggle_installment", value: inst.checked });
  function setArea(v) { if (areaSel) areaSel.value = v; action({ type: "set_area", value: v }); }
  if (areaSel) areaSel.onchange = () => setArea(areaSel.value);
  $("#reset").onclick = () => { localStorage.removeItem("torob_che_session"); sessionId = null; currentPhone = null; lastStage = 0; $("#profile").innerHTML = ""; inst.checked = false; if (areaSel) areaSel.value = ""; welcome(); };
  localStorage.removeItem("torob_che_session"); sessionId = null;
  welcome();
})();
