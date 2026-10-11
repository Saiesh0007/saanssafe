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
const EMOJI = ["🟢", "🟢", "🟠", "🔴", "⛔"];
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
async function searchPlaces(q) {
  try {
    const res = await api(`/api/places?q=${encodeURIComponent(q)}`);
    if (res.length) return res;
  } catch {}
  const om = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6`).then((r) => r.json()).catch(() => ({}));
  if (om.results?.length) {
    om.results.sort((a, b) => (a.country_code !== "IN") - (b.country_code !== "IN"));
    return om.results.map((x) => ({ name: x.name, admin: [x.admin2, x.admin1, x.country].filter(Boolean).join(", "), lat: x.latitude, lon: x.longitude }));
  }
  const nm = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=jsonv2&limit=6&countrycodes=in`).then((r) => r.json()).catch(() => []);
  return nm.map((x) => ({ name: x.display_name.split(",")[0], admin: x.display_name.split(",").slice(1, 4).join(",").trim(), lat: +x.lat, lon: +x.lon }));
}

async function load(place) {
  state.place = place;
  const sensitive = $("#sensitive").checked;
  $("#result").hidden = false;
  $("#banner").className = "banner lv1";
  $("#banner").innerHTML = `<div class="big">${t("Checking the air and heat…", "हवा और गर्मी देख रहे हैं…")}</div>`;
  try {
    state.report = await fetchReport(place, sensitive);
    state.day = 0;
    render();
    $("#result").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    $("#banner").className = "banner lv3";
    $("#banner").innerHTML = `<div class="big">${esc(e.message)}</div>`;
  }
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
  $("#meta").textContent = `${t("Updated", "अपडेट")} ${r.generated_at.replace("T", " ")} · ${r.sensitive ? t("Asthma-safe mode", "अस्थमा-सुरक्षित मोड") : t("Standard mode", "सामान्य मोड")}`;
  $("#tabs").innerHTML = r.days.map((x, i) => `<button role="tab" class="${i === state.day ? "on" : ""}" data-i="${i}">${dayLabel(i, x.date)}</button>`).join("");

  const lv = d.overall_level;
  $("#banner").className = `banner lv${lv}`;
  $("#banner").innerHTML = `<div class="emoji">${EMOJI[lv]}</div><div><div class="big">${HEADLINE[state.lang][lv]}</div>
    <div>${t("Worst during school hours (7 am - 3 pm)", "स्कूल समय (सुबह 7 - दोपहर 3) में सबसे खराब स्थिति")}</div></div>`;

  $("#statAir").innerHTML = `<div class="k">${t("Peak AQI (India)", "अधिकतम AQI")}</div><div class="v" style="color:${aqiColor(d.peak_aqi)}">${d.peak_aqi}</div><div class="c">${d.aqi_category}</div>`;
  $("#statHeat").innerHTML = `<div class="k">${t("Feels like", "महसूस तापमान")}</div><div class="v">${d.peak_feels_like}°</div><div class="c">${d.heat_category}</div>`;
  $("#statUv").innerHTML = `<div class="k">${t("Max UV", "अधिकतम UV")}</div><div class="v">${Math.round(d.max_uv)}</div><div class="c">${d.max_uv >= 8 ? t("Very high", "बहुत अधिक") : d.max_uv >= 6 ? t("High", "अधिक") : t("Moderate/low", "मध्यम/कम")}</div>`;

  $("#decHead").textContent = t(`Decisions for ${dayLabel(state.day, d.date).toLowerCase()}`, `${dayLabel(state.day, d.date)} के निर्णय`);
  $("#cards").innerHTML = d.activities.map((a) => `
    <div class="act b${a.level}">
      <div class="t">${esc(state.lang === "hi" ? a.name_hi : a.name)}</div><div class="w">${a.window}</div>
      <div class="verdict t${a.level}">${esc(state.lang === "hi" ? a.verdict_hi : a.verdict)}</div>
      <div class="a">${esc(state.lang === "hi" ? a.action_hi : a.action)}</div>
      ${a.driver ? `<div class="why">${a.driver === "air" ? t(`Because of air: AQI up to ${a.peak_aqi}`, `कारण: हवा, AQI ${a.peak_aqi} तक`) : t(`Because of heat: feels like ${a.peak_feels_like}°C`, `कारण: गर्मी, ${a.peak_feels_like}°C`)}</div>` : ""}
    </div>`).join("");

  renderChart(d.hourly);
  $("#tips").innerHTML = d.tips.map((x) => `<li>${esc(x)}</li>`).join("");
  renderNotice();
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
  const bars = hours.map((h) => `<rect x="${x(h.hour) + 2}" y="${yA(h.aqi)}" width="${bw - 4}" height="${H - P.b - yA(h.aqi)}" rx="2" fill="${aqiColor(h.aqi)}"><title>${String(h.hour).padStart(2, "0")}:00 · AQI ${h.aqi} · ${h.feels_like}°C</title></rect>`).join("");
  const line = hours.map((h, i) => `${i ? "L" : "M"}${x(h.hour) + bw / 2},${yT(h.feels_like)}`).join(" ");
  const ticks = [0, 6, 7, 12, 15, 18, 23].map((hr) => `<text x="${x(hr) + bw / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="currentColor" opacity=".6">${hr}h</text>`).join("");
  const aTicks = [100, 200, 300].filter((v) => v <= maxA).map((v) => `<line x1="${P.l}" x2="${W - P.r}" y1="${yA(v)}" y2="${yA(v)}" stroke="currentColor" opacity=".12"/><text x="${P.l - 4}" y="${yA(v) + 4}" text-anchor="end" font-size="10" fill="currentColor" opacity=".6">${v}</text>`).join("");
  $("#chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Hourly AQI bars and feels-like temperature line">${school}${aTicks}${bars}
    <path d="${line}" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>${ticks}
    <text x="${W - P.r + 4}" y="${yT(tMax - 2) + 4}" font-size="10" fill="currentColor" opacity=".7">${Math.round(tMax - 2)}°</text>
    <text x="${W - P.r + 4}" y="${yT(tMin + 2) + 4}" font-size="10" fill="currentColor" opacity=".7">${Math.round(tMin + 2)}°</text></svg>
    <div class="lg"><span><i class="sw" style="background:#eab308"></i>${t("Bars: AQI (CPCB colours)", "बार: AQI")}</span><span>━ ${t("Line: feels-like °C", "रेखा: महसूस तापमान")}</span><span><i class="sw" style="background:currentColor;opacity:.2"></i>${t("School hours", "स्कूल समय")}</span></div>`;
}

function renderNotice() {
  const text = state.report.notices[state.day][state.noticeLang];
  $("#notice").textContent = text;
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
$("#copyBtn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#notice").textContent); $("#copyBtn").textContent = "✓"; setTimeout(applyLang, 1200); } catch {}
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
  box.textContent = t("Checking live conditions…", "लाइव स्थिति देख रहे हैं…");
  try {
    const p = state.place || {};
    const res = await api("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, place: p.name, lat: p.lat, lon: p.lon, sensitive: $("#sensitive").checked }),
    });
    box.className = "answer"; box.textContent = res.answer.replace(/\*\*/g, "");
  } catch (err) { box.className = "answer"; box.textContent = err.message; }
});

applyLang();
