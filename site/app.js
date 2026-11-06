(() => {
  "use strict";
  const PRIORITY = ["Банки", "Инвестиции и рынки капитала"];
  const SECTORS = ["Банки", "Инвестиции и рынки капитала", "Аудит и консалтинг", "Страхование",
                   "Госсектор и регуляторы", "Финтех", "Корпоративные финансы"];
  const KINDS = ["Стажировка", "Вакансия", "Программа"];
  const DAY = 86400000;
  const $ = (id) => document.getElementById(id);

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* приватный режим */ } },
  };
  const favs = new Set(store.get("fav", []));
  const hidden = new Set(store.get("hidden", []));
  const state = Object.assign({ q: "", sectors: [], kinds: [], onlyNew: false, salary: false,
    fav: false, showHidden: false, source: "", sort: "priority" }, store.get("filters", {}));

  let all = [];
  let lastVisit = store.get("lastVisit", null);

  const fmtDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  };
  const ageMs = (v) => Date.now() - new Date(v.first_seen || v.published || 0).getTime();
  const isNew = (v) => ageMs(v) < 2 * DAY;

  function chips(container, values, key, counts) {
    container.innerHTML = "";
    values.forEach((val) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "chip";
      b.setAttribute("aria-pressed", state[key].includes(val));
      b.innerHTML = `${val}<small>${counts[val] || 0}</small>`;
      b.onclick = () => {
        const set = new Set(state[key]);
        set.has(val) ? set.delete(val) : set.add(val);
        state[key] = [...set];
        b.setAttribute("aria-pressed", set.has(val));
        render();
      };
      container.appendChild(b);
    });
  }

  function matches(v) {
    if (!state.showHidden && hidden.has(v.id)) return false;
    if (state.fav && !favs.has(v.id)) return false;
    if (state.sectors.length && !state.sectors.includes(v.sector)) return false;
    if (state.kinds.length && !state.kinds.includes(v.kind)) return false;
    if (state.onlyNew && !isNew(v)) return false;
    if (state.salary && !(v.salary_from || v.salary_to)) return false;
    if (state.source && v.source_type !== state.source) return false;
    if (state.q) {
      const hay = [v.title, v.employer, v.department, v.description, v.sector, (v.conditions || []).join(" ")]
        .join(" ").toLowerCase().replace(/ё/g, "е");
      const words = state.q.toLowerCase().replace(/ё/g, "е").split(/\s+/).filter(Boolean);
      if (!words.every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  const sorters = {
    date: (a, b) => (b.published || b.first_seen || "").slice(0, 10).localeCompare((a.published || a.first_seen || "").slice(0, 10))
      || (b.score || 0) - (a.score || 0),
    priority: (a, b) => (PRIORITY.includes(b.sector) - PRIORITY.includes(a.sector)) || sorters.date(a, b),
    salary: (a, b) => ((b.salary_to || b.salary_from || 0) - (a.salary_to || a.salary_from || 0)) || sorters.date(a, b),
  };

  function card(v) {
    const node = $("card").content.firstElementChild.cloneNode(true);
    if (hidden.has(v.id)) node.classList.add("is-hidden");
    const badges = node.querySelector(".card__badges");
    const badge = (text, cls) => { const s = document.createElement("span"); s.className = "badge " + cls; s.textContent = text; badges.appendChild(s); };
    if (isNew(v)) badge("Новое", "badge--new");
    badge(v.kind || "Вакансия", "badge--kind");
    if (v.sector) badge(v.sector, PRIORITY.includes(v.sector) ? "badge--prio" : "");
    if (v.deadline) badge("Дедлайн " + v.deadline, "");

    const a = node.querySelector(".card__title a");
    a.textContent = v.title; a.href = v.url;
    node.querySelector(".card__employer").textContent = v.employer || "Работодатель не указан в источнике";

    const sal = node.querySelector(".f-salary");
    if (v.salary) { sal.textContent = v.salary; if (v.salary_from || v.salary_to) sal.classList.add("has"); }
    else { sal.innerHTML = '<span class="na">не указана</span>'; }
    const dept = node.querySelector(".f-dept");
    dept.textContent = v.department || "—";
    if (!v.department) dept.classList.add("na");
    const cond = node.querySelector(".f-cond");
    const c = [...(v.conditions || [])];
    if (v.location && v.location !== "Москва") c.unshift(v.location);
    cond.textContent = c.length ? c.join(" · ") : "уточняйте у работодателя";
    if (!c.length) cond.classList.add("na");

    const more = node.querySelector(".card__more");
    if (v.description) node.querySelector(".card__desc").textContent = v.description;
    else more.remove();

    const extra = (v.tags || []).filter((t) => t.startsWith("Также:")).map((t) => t.slice(7));
    node.querySelector(".card__source").textContent = v.source + (extra.length ? " · также " + extra.join(", ") : "");
    const pub = v.published ? "опубл. " + fmtDate(v.published) : "найдено " + fmtDate(v.first_seen);
    node.querySelector(".card__date").textContent = pub;
    const apply = node.querySelector(".card__apply");
    apply.href = v.apply_url || v.url;
    apply.textContent = v.apply_url ? "Откликнуться" : "Открыть";

    const fav = node.querySelector(".fav");
    const setFav = () => { fav.setAttribute("aria-pressed", favs.has(v.id)); fav.textContent = favs.has(v.id) ? "★" : "☆"; };
    setFav();
    fav.onclick = () => { favs.has(v.id) ? favs.delete(v.id) : favs.add(v.id); store.set("fav", [...favs]); setFav(); if (state.fav) render(); };
    const hide = node.querySelector(".hide");
    hide.title = hidden.has(v.id) ? "Вернуть" : "Скрыть";
    hide.onclick = () => { hidden.has(v.id) ? hidden.delete(v.id) : hidden.add(v.id); store.set("hidden", [...hidden]); render(); };
    return node;
  }

  function render() {
    store.set("filters", state);
    const rows = all.filter(matches).sort(sorters[state.sort] || sorters.date);
    const list = $("list");
    list.replaceChildren(...rows.map(card));
    $("empty").hidden = rows.length > 0;
    const word = (n) => (n % 10 === 1 && n % 100 !== 11) ? "предложение" : ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) ? "предложения" : "предложений";
    $("count").textContent = `Показано ${rows.length} ${word(rows.length)} из ${all.length}`;
  }

  function bindControls() {
    const q = $("q"); q.value = state.q;
    let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => { state.q = q.value.trim(); render(); }, 150); };
    [["f-new", "onlyNew"], ["f-salary", "salary"], ["f-fav", "fav"], ["f-hidden", "showHidden"]].forEach(([id, key]) => {
      const el = $(id); el.checked = !!state[key]; el.onchange = () => { state[key] = el.checked; render(); };
    });
    const src = $("f-source"); src.onchange = () => { state.source = src.value; render(); };
    const sort = $("f-sort"); sort.value = state.sort; sort.onchange = () => { state.sort = sort.value; render(); };
  }

  async function init() {
    bindControls();
    try {
      const r = await fetch("data/vacancies.json", { cache: "no-cache" });
      const data = await r.json();
      all = data.vacancies || [];
      const upd = new Date(data.updated_at);
      $("updated").textContent = "Обновлено " + upd.toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      $("updated").textContent = "Не удалось загрузить данные";
      $("empty").hidden = false;
      $("empty").textContent = "Файл с вакансиями не загрузился. Обновите страницу; если ошибка повторяется, проверьте последний запуск обновления в GitHub Actions.";
      return;
    }
    const count = (key) => all.reduce((m, v) => (m[v[key]] = (m[v[key]] || 0) + 1, m), {});
    const sc = count("sector"), kc = count("kind");
    chips($("f-sector"), SECTORS.filter((s) => sc[s]), "sectors", sc);
    chips($("f-kind"), KINDS.filter((k) => kc[k]), "kinds", kc);
    const srcNames = {};
    all.forEach((v) => { srcNames[v.source_type] = srcNames[v.source_type] || v.source.replace(/ · .*/, ""); });
    const sel = $("f-source");
    Object.entries(srcNames).forEach(([k, name]) => { const o = new Option(name, k); sel.add(o); });
    sel.value = state.source;

    $("s-total").textContent = all.length;
    $("s-new").textContent = all.filter((v) => ageMs(v) < DAY).length;
    $("s-bank").textContent = all.filter((v) => PRIORITY.includes(v.sector)).length;
    $("s-salary").textContent = all.filter((v) => v.salary_from || v.salary_to).length;
    store.set("lastVisit", new Date().toISOString());
    render();
  }
  init();
})();
