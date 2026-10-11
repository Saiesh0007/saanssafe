const $ = (s) => document.querySelector(s);
const state = { lang: localGet("lang") || "en", report: null, day: 0, noticeLang: "en", place: null };

const CITIES = [
  { name: "Delhi (Anand Vihar)", lat: 28.6469, lon: 77.3160 },
  { name: "Lucknow", lat: 26.8393, lon: 80.9231 },
  { name: "Patna", lat: 25.5941, lon: 85.1376 },
  { name: "Ahmedabad", lat: 23.0225, lon: 72.5714 },
  { name: "Nagpur", lat: 21.1458, lon: 79.0882 },
  { name: "Mumbai", lat: 19.0760, lon: 72.8777 },
  { name: "Bengaluru", lat: 12.9716, lon: 77.5946 },
];
const HEADLINE = {
  en: ["All clear for outdoor activities", "Outdoors is fine, with care", "Limit time outdoors", "Move outdoor exertion indoors", "Consider closing / going online"],
  hi: ["बाहरी गतिविधियाँ ठीक हैं", "सावधानी के साथ बाहर ठीक", "बाहर का समय सीमित करें", "मेहनत वाली गतिविधि अंदर करें", "स्कूल बंद / ऑनलाइन पर विचार करें"],
};
const AQI_COLORS = [[50, "#16a34a"], [100, "#84cc16"], [200, "#eab308"], [300, "#f97316"], [400, "#dc2626"], [1e9, "#7f1d1d"]];
const ASK_EXAMPLES = {
  en: ["Can we hold sports day tomorrow?", "What should we tell parents of asthmatic kids?", "Best time today for outdoor PE?"],
  hi: ["क्या कल खेल दिवस रख सकते हैं?", "आज बाहर पीटी का सबसे अच्छा समय?", "अभिभावकों को क्या संदेश भेजें?"],
};

function localGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localSet(k, v) { try { localStorage.setItem(k, v); } catch {} }
const t = (en, hi) => (state.lang === "hi" ? hi : en);
const aqiColor = (v) => AQI_COLORS.find(([lim]) => v <= lim)[1];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function applyLang() {
  document.documentElement.lang = state.lang;
  $("#langBtn").textContent = state.lang === "hi" ? "English" : "हिंदी";
  document.querySelectorAll("[data-en]").forEach((el) => (el.textContent = el.dataset[state.lang]));
  $("#askChips").innerHTML = ASK_EXAMPLES[state.lang].map((q) => `<button class="chip" type="button">${esc(q)}</button>`).join("");
  if (state.report) render();
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Request failed (${r.status})`);
  return body;
}

// Fetch the forecast from the visitor's own browser (Open-Meteo allows CORS), so shared
// server IPs never hit rate limits; fall back to the server fetching it.
async function fetchReport(place, sensitive) {
  const common = `latitude=${place.lat}&longitude=${place.lon}&timezone=auto&forecast_days=4`;
  try {
    const [air, wx] = await Promise.all([
      fetch(`https://air-quality-api.open-meteo.com/v1/air-quality?${common}&hourly=pm2_5,pm10`).then((r) => (r.ok ? r.json() : Promise.reject())),
      fetch(`https://api.open-meteo.com/v1/forecast?${common}&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,uv_index`).then((r) => (r.ok ? r.json() : Promise.reject())),
    ]);
    return await api("/api/report", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: place.lat, lon: place.lon, place: place.name, sensitive, air, wx }),
    });
  } catch {
    return api(`/api/report?lat=${place.lat}&lon=${place.lon}&place=${encodeURIComponent(place.name)}&sensitive=${sensitive}`);
  }
}

// Place search: server first, then the same free geocoders straight from the browser.
const dedupe = (list) => list.filter((p, i) => list.findIndex((o) => o.name === p.name && o.admin === p.admin) === i);

async function searchPlaces(q) {
  try {
    const res = await api(`/api/places?q=${encodeURIComponent(q)}`);
    if (res.length) return res;
  } catch {}
  const om = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6`).then((r) => r.json()).catch(() => ({}));
  if (om.results?.length) {
    om.results.sort((a, b) => (a.country_code !== "IN") - (b.country_code !== "IN") || (b.population || 0) - (a.population || 0));
    return dedupe(om.results.map((x) => ({ name: x.name, admin: [x.admin2, x.admin1, x.country].filter(Boolean).join(", "), lat: x.latitude, lon: x.longitude })));
  }
  const nm = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=jsonv2&limit=6&countrycodes=in`).then((r) => r.json()).catch(() => []);
  return nm.map((x) => ({ name: x.display_name.split(",")[0], admin: x.display_name.split(",").slice(1, 4).join(",").trim(), lat: +x.lat, lon: +x.lon }));
}

async function load(place) {
  state.place = place;
  const sensitive = $("#sensitive").checked;
  $("#result").hidden = false;
  $("#banner").className = "verdict-panel tilt loading lv1";
  $("#banner").innerHTML = `<div class="ring">${ring(0)}<div class="val"><b>…</b></div></div><div><div class="kicker">${esc(place.name)}</div><div class="big">${t("Checking the air and heat…", "हवा और गर्मी देख रहे हैं…")}</div></div>`;
  requestAnimationFrame(() => $("#result").scrollIntoView({ behavior: "smooth", block: "start" }));
  try {
    state.report = await fetchReport(place, sensitive);
    state.day = 0;
    render();
  } catch (e) {
    $("#banner").className = "verdict-panel lv3";
    $("#banner").innerHTML = `<div class="big">${esc(e.message)}</div>`;
  }
}

// '2026-10-11T19:02' -> '11-10-2026, 7:02 pm'
function fmtStamp(iso) {
  const [d, tm = "00:00"] = iso.split("T");
  const [y, m, dd] = d.split("-");
  let [h, mi] = tm.split(":").map(Number);
  const ap = h >= 12 ? "pm" : "am";
  h = h % 12 || 12;
  return `${dd}-${m}-${y}, ${h}:${String(mi).padStart(2, "0")} ${ap}`;
}

function dayLabel(i, date) {
  const d = new Date(date + "T00:00");
  if (i === 0) return t("Today", "आज");
  if (i === 1) return t("Tomorrow", "कल");
  return d.toLocaleDateString(state.lang === "hi" ? "hi-IN" : "en-IN", { weekday: "short", day: "numeric" });
}

function render() {
  const r = state.report, d = r.days[state.day];
  $("#placeName").textContent = r.place;
  $("#meta").textContent = `${t("Updated", "अपडेट")} ${fmtStamp(r.generated_at)} · ${r.sensitive ? t("Asthma-safe mode", "अस्थमा-सुरक्षित मोड") : t("Standard mode", "सामान्य मोड")}`;
  $("#tabs").innerHTML = r.days.map((x, i) => `<button role="tab" class="${i === state.day ? "on" : ""}" data-i="${i}">${dayLabel(i, x.date)}</button>`).join("");

  const lv = d.overall_level;
  $("#banner").className = `verdict-panel tilt lv${lv}`;
  $("#banner").innerHTML = `<div class="ring">${ring(d.peak_aqi / 500)}<div class="val"><b data-count="${d.peak_aqi}">0</b><span>${t("Peak AQI", "अधिकतम AQI")}</span><span class="hrs">${t("7 am - 3 pm", "सुबह 7 - दोप. 3")}</span></div></div>
    <div><div class="kicker">${esc(state.lang === "hi" ? d.overall_hi : d.overall)} · ${dayLabel(state.day, d.date)}</div>
    <div class="big">${HEADLINE[state.lang][lv]}</div>
    <div class="small">${reasonLine(d)}</div>${nowLine(r, d)}</div>`;
  renderScale(lv);
  requestAnimationFrame(() => { const fg = $("#banner .fg"); if (fg) fg.style.strokeDashoffset = fg.dataset.to; });

  const heatPct = Math.max(0, Math.min(1, (d.peak_feels_like - 20) / 35));
  $("#statAir").innerHTML = `<div class="k">${t("AQI · school hours (CPCB)", "AQI · स्कूल समय (CPCB)")}</div><div class="v" style="color:${aqiColor(d.peak_aqi)}" data-count="${d.peak_aqi}">0</div><div class="c">${t(d.aqi_category, d.aqi_category_hi)}</div>
    <div class="bar"><i style="background:${aqiColor(d.peak_aqi)}" data-w="${Math.min(100, d.peak_aqi / 5)}"></i></div>`;
  $("#statHeat").innerHTML = `<div class="k">${t("Feels like · school hours", "महसूस तापमान · स्कूल समय")}</div><div class="v"><span data-count="${d.peak_feels_like}" data-dec="1">0</span>°</div><div class="c">${t(d.heat_category, d.heat_category_hi)}</div>
    <div class="bar"><i style="background:linear-gradient(90deg,#facc15,#f97316,#ef4444)" data-w="${heatPct * 100}"></i></div>`;
  $("#statUv").innerHTML = `<div class="k">${t("Max UV", "अधिकतम UV")}</div><div class="v" data-count="${Math.round(d.max_uv)}">0</div><div class="c">${d.max_uv >= 8 ? t("Very high", "बहुत अधिक") : d.max_uv >= 6 ? t("High", "अधिक") : t("Moderate/low", "मध्यम/कम")}</div>
    <div class="bar"><i style="background:linear-gradient(90deg,#a3e635,#facc15,#a21caf)" data-w="${Math.min(100, d.max_uv * 9)}"></i></div>`;
  requestAnimationFrame(() => document.querySelectorAll(".bar i[data-w]").forEach((b) => (b.style.width = b.dataset.w + "%")));
  countUp();
  document.documentElement.style.setProperty("--sky", aqiColor(d.peak_aqi));

  $("#decHead").textContent = t(`Decisions for ${dayLabel(state.day, d.date).toLowerCase()}`, `${dayLabel(state.day, d.date)} के निर्णय`);
  $("#cards").innerHTML = d.activities.map((a, i) => `
    <div class="act tilt b${a.level}" style="--i:${i}">
      <div class="t">${esc(state.lang === "hi" ? a.name_hi : a.name)}</div><div class="w">${a.window}</div>
      <div class="verdict t${a.level}">${esc(state.lang === "hi" ? a.verdict_hi : a.verdict)}</div>
      <div class="a">${esc(state.lang === "hi" ? a.action_hi : a.action)}</div>
      ${a.driver ? `<div class="why">${a.driver === "air" ? t(`Because of air: AQI up to ${a.peak_aqi}`, `कारण: हवा, AQI ${a.peak_aqi} तक`) : t(`Because of heat: feels like ${a.peak_feels_like}°C`, `कारण: गर्मी, ${a.peak_feels_like}°C`)}</div>` : ""}
    </div>`).join("");

  renderChart(d.hourly);
  $("#tips").innerHTML = d.tips.map((x) => `<li>${esc(t(x.en, x.hi))}</li>`).join("");
  renderNotice();
}

// Which of air or heat drives the day's worst verdict, so the AQI ring never looks contradictory.
function reasonLine(d) {
  const worst = d.activities.reduce((a, b) => (b.level > a.level ? b : a), d.activities[0]);
  const hours = t("during school hours", "स्कूल समय में");
  if (!worst || !worst.driver) return t("Conditions are fine all through school hours (7 am - 3 pm)", "पूरे स्कूल समय (सुबह 7 - दोपहर 3) स्थिति ठीक है");
  return worst.driver === "heat"
    ? t(`Driven by heat: feels like ${d.peak_feels_like}°C ${hours}`, `कारण: गर्मी - ${hours} महसूस तापमान ${d.peak_feels_like}°C`)
    : t(`Driven by air: AQI up to ${d.peak_aqi} ${hours}`, `कारण: हवा - ${hours} AQI ${d.peak_aqi} तक`);
}

// The current hour's AQI on the "Today" tab, so it's clear the ring is a school-hours peak.
function nowLine(r, d) {
  if (state.day !== 0) return "";
  const hr = +r.generated_at.slice(11, 13);
  const h = d.hourly.find((x) => x.hour === hr);
  if (!h) return "";
  return `<div class="now"><i style="background:${aqiColor(h.aqi)}"></i>${t("Right now", "अभी")}: AQI ${h.aqi} · ${h.feels_like}°C</div>`;
}

const SCALE = { en: ["Go", "Go with care", "Limit", "Move indoors", "Stay home"], hi: ["ठीक है", "सावधानी से", "सीमित करें", "अंदर ही रखें", "घर पर रहें"] };
function renderScale(lv) {
  $("#scale").innerHTML = SCALE[state.lang].map((name, i) => `<span class="s${i}${i === lv ? " on" : ""}">${name}</span>`).join("");
}

// SVG ring gauge; the foreground stroke animates from empty to `frac`.
function ring(frac) {
  const C = 2 * Math.PI * 52, to = C * (1 - Math.max(0.02, Math.min(1, frac)));
  return `<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="bg" cx="60" cy="60" r="52" fill="none" stroke-width="10"/>
    <circle class="fg" cx="60" cy="60" r="52" fill="none" stroke-width="10" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C}" data-to="${to}"/></svg>`;
}

function countUp() {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll("[data-count]").forEach((el) => {
    const end = +el.dataset.count, dec = +(el.dataset.dec || 0), t0 = performance.now(), dur = 1100;
    if (reduced) return (el.textContent = end.toFixed(dec));
    const step = (now) => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = (end * e).toFixed(dec);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

function renderChart(hours) {
  const W = 720, H = 200, P = { l: 34, r: 34, t: 10, b: 24 };
  const maxA = Math.max(300, ...hours.map((h) => h.aqi));
  const temps = hours.map((h) => h.feels_like);
  const tMin = Math.min(...temps) - 2, tMax = Math.max(...temps) + 2;
  const bw = (W - P.l - P.r) / 24;
  const x = (hr) => P.l + hr * bw;
  const yA = (v) => H - P.b - (v / maxA) * (H - P.t - P.b);
  const yT = (v) => H - P.b - ((v - tMin) / (tMax - tMin)) * (H - P.t - P.b);
  const school = `<rect x="${x(7)}" y="${P.t}" width="${bw * 9}" height="${H - P.t - P.b}" fill="currentColor" opacity=".06"/>`;
  const bars = hours.map((h) => `<rect class="b" style="animation-delay:${h.hour * 25}ms" x="${x(h.hour) + 2}" y="${yA(h.aqi)}" width="${bw - 4}" height="${H - P.b - yA(h.aqi)}" rx="2" fill="${aqiColor(h.aqi)}"><title>${String(h.hour).padStart(2, "0")}:00 · AQI ${h.aqi} · ${h.feels_like}°C</title></rect>`).join("");
  const line = hours.map((h, i) => `${i ? "L" : "M"}${x(h.hour) + bw / 2},${yT(h.feels_like)}`).join(" ");
  const ticks = [0, 6, 7, 12, 15, 18, 23].map((hr) => `<text x="${x(hr) + bw / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="currentColor" opacity=".6">${hr}h</text>`).join("");
  const aTicks = [100, 200, 300].filter((v) => v <= maxA).map((v) => `<line x1="${P.l}" x2="${W - P.r}" y1="${yA(v)}" y2="${yA(v)}" stroke="currentColor" opacity=".12"/><text x="${P.l - 4}" y="${yA(v) + 4}" text-anchor="end" font-size="10" fill="currentColor" opacity=".6">${v}</text>`).join("");
  $("#chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Hourly AQI bars and feels-like temperature line">${school}${aTicks}${bars}
    <path class="ln" d="${line}" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>${ticks}
    <text x="${W - P.r + 4}" y="${yT(tMax - 2) + 4}" font-size="10" fill="currentColor" opacity=".7">${Math.round(tMax - 2)}°</text>
    <text x="${W - P.r + 4}" y="${yT(tMin + 2) + 4}" font-size="10" fill="currentColor" opacity=".7">${Math.round(tMin + 2)}°</text></svg>
    <div class="lg"><span><i class="sw" style="background:#eab308"></i>${t("Bars: AQI (CPCB colours)", "बार: AQI")}</span><span>━ ${t("Line: feels-like °C", "रेखा: महसूस तापमान")}</span><span><i class="sw" style="background:currentColor;opacity:.2"></i>${t("School hours", "स्कूल समय")}</span></div>`;
}

function renderNotice() {
  const school = $("#schoolName").value.trim();
  let text = state.report.notices[state.day][state.noticeLang];
  if (school) text = text.replace(/(Principal|प्रधानाचार्य)$/, `$1\n${school}`);
  state.noticeText = text;
  $("#notice").innerHTML = esc(text).replace(/\*([^*\n]+)\*/g, "<b>$1</b>");
  const now = new Date();
  $("#stamp").textContent = now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  $("#waBtn").href = "https://wa.me/?text=" + encodeURIComponent(text);
  document.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.nl === state.noticeLang));
}

// --- search with suggestions
let timer, suggestions = [];
$("#q").addEventListener("input", () => {
  clearTimeout(timer);
  const q = $("#q").value.trim();
  if (q.length < 3) return ($("#suggest").hidden = true);
  timer = setTimeout(async () => {
    try { suggestions = await searchPlaces(q); } catch { suggestions = []; }
    $("#suggest").innerHTML = suggestions.length
      ? suggestions.map((p, i) => `<li data-i="${i}">${esc(p.name)}<small>${esc(p.admin)}</small></li>`).join("")
      : `<li>${t("No match - try adding the city name", "नहीं मिला - शहर का नाम जोड़ें")}</li>`;
    $("#suggest").hidden = false;
  }, 350);
});
$("#suggest").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-i]");
  if (!li) return;
  const p = suggestions[+li.dataset.i];
  $("#q").value = p.name; $("#suggest").hidden = true;
  load(p);
});
$("#searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#suggest").hidden = true;
  const q = $("#q").value.trim();
  if (!q) return;
  try {
    const res = suggestions.length ? suggestions : await searchPlaces(q);
    if (!res.length) throw new Error(t("Place not found", "जगह नहीं मिली"));
    load(res[0]);
  } catch (err) { alert(err.message); }
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("#suggest").hidden = true; });

$("#geoBtn").addEventListener("click", () => {
  if (!navigator.geolocation) return alert("Location not available");
  navigator.geolocation.getCurrentPosition(
    (pos) => load({ name: t("My location", "मेरी लोकेशन"), lat: +pos.coords.latitude.toFixed(4), lon: +pos.coords.longitude.toFixed(4) }),
    () => alert(t("Could not get your location - search instead.", "लोकेशन नहीं मिली - खोजें।")),
  );
});
$("#sensitive").addEventListener("change", () => state.place && load(state.place));
$("#chips").innerHTML = CITIES.map((c, i) => `<button class="chip" type="button" data-i="${i}">${c.name}</button>`).join("");
$("#chips").addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) load(CITIES[+b.dataset.i]); });
$("#tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) { state.day = +b.dataset.i; render(); } });
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => { state.noticeLang = b.dataset.nl; renderNotice(); }));
$("#schoolName").value = localGet("school") || "";
$("#schoolName").addEventListener("input", () => { localSet("school", $("#schoolName").value); if (state.report) renderNotice(); });
$("#copyBtn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(state.noticeText); $("#copyBtn").textContent = "✓"; setTimeout(applyLang, 1200); } catch {}
});
$("#langBtn").addEventListener("click", () => { state.lang = state.lang === "en" ? "hi" : "en"; state.noticeLang = state.lang; localSet("lang", state.lang); applyLang(); });

// --- advisor (Strands agent)
$("#askChips").addEventListener("click", (e) => { if (e.target.matches(".chip")) { $("#askQ").value = e.target.textContent; $("#askForm").requestSubmit(); } });
$("#askForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#askQ").value.trim();
  if (!q) return;
  const box = $("#answer");
  box.hidden = false; box.className = "answer loading";
  const steps = [t("Finding the school", "स्कूल ढूँढ रहे हैं"), t("Checking live air and heat", "लाइव हवा और गर्मी देख रहे हैं"),
    t("Writing the advice", "सलाह लिख रहे हैं"), t("Almost there - the free AI is busy, hang on", "बस थोड़ा और - मुफ़्त AI व्यस्त है, रुकिए")];
  let step = 0;
  box.textContent = steps[0];
  const ticker = setInterval(() => { step = Math.min(step + 1, steps.length - 1); box.textContent = steps[step]; }, 4000);
  try {
    const p = state.place || {};
    const res = await api("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, place: p.name, lat: p.lat, lon: p.lon, sensitive: $("#sensitive").checked, lang: state.lang }),
    });
    box.className = "answer"; box.textContent = res.answer.replace(/\*\*/g, "");
  } catch (err) {
    box.className = "answer";
    box.textContent = err.message === "busy"
      ? t("The free AI advisor is getting a lot of questions right now. Please try again in a minute - the dashboard above already has today's decisions.",
          "मुफ़्त AI सलाहकार के पास अभी बहुत सवाल हैं। कृपया एक मिनट बाद फिर पूछें - ऊपर डैशबोर्ड में आज के निर्णय पहले से हैं।")
      : err.message;
  } finally { clearInterval(ticker); }
});

// 3D tilt that follows the pointer (desktop only), and scroll reveals
if (matchMedia("(hover: hover) and (prefers-reduced-motion: no-preference)").matches) {
  document.addEventListener("pointermove", (e) => {
    const el = e.target.closest(".tilt");
    document.querySelectorAll(".tilting").forEach((x) => x !== el && x.classList.remove("tilting"));
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
    const max = el.classList.contains("verdict-panel") ? 4 : 9;
    el.style.setProperty("--ry", `${px * max}deg`);
    el.style.setProperty("--rx", `${-py * max}deg`);
    el.classList.add("tilting");
  }, { passive: true });
  document.addEventListener("pointerleave", () => document.querySelectorAll(".tilting").forEach((x) => x.classList.remove("tilting")));
}
const io = "IntersectionObserver" in window ? new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 }) : null;
document.querySelectorAll(".reveal").forEach((el, i) => { el.style.transitionDelay = `${Math.min(i, 6) * 70}ms`; io ? io.observe(el) : el.classList.add("in"); });

applyLang();
