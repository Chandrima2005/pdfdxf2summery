// Landing page: the three animated drawing types, showcase cards (from the sample catalog) and the mode pill.

const SHOWCASE = [
  { id: "db-001.dxf", cat: "db", tag: "Electrical", title: "Distribution board", featured: true,
    desc: "Breakers, RCDs, cables and loads. Trace every circuit, total the loads and verify the protection rules.",
    qs: ["How many circuits are in this distribution board?", "Are all socket circuits protected by an RCD as the spec requires?"] },
  { id: "plan-001.dxf", cat: "plan", tag: "Architecture", title: "Building floor plan",
    desc: "Rooms, corridors, doors and windows. Measure areas and widths, then check them against the building spec.",
    qs: ["How many rooms are in this plan?", "Does the corridor meet the minimum width required by the spec?"] },
  { id: "ckt-001.dxf", cat: "ckt", tag: "Electronics", title: "Electronic circuit",
    desc: "Components and nets. Follow connections, read values and count parts.",
    qs: ["How many components are on the schematic?", "What is the value of R3 in ohms?"] },
];

function renderCards() {
  document.getElementById("cards").innerHTML = SHOWCASE.map(c => `
    <article class="card t-${c.cat}${c.featured ? " featured" : ""}">
      <div class="thumb skeleton"><img src="/api/image/${c.id}?size=thumb" alt="${esc(c.title)} sample" loading="lazy"
           onload="this.parentElement.classList.remove('skeleton')"></div>
      <div class="tagrow"><span class="tag">${c.tag}</span>${c.featured ? '<span class="ribbon">★ MAIN FOCUS</span>' : ""}</div>
      <h3>${c.title}</h3>
      <p>${c.desc}</p>
      <div class="chips">${c.qs.map(q => `<div class="chip">${esc(q)}</div>`).join("")}</div>
      <a class="btn primary block" href="/app?sample=${c.id}">Ask about this →</a>
    </article>`).join("");
}

async function init() {
  bindThemeToggle();
  document.getElementById("trio").innerHTML = trio();
  renderCards();
  revealOnScroll();
  try {
    const cfg = await api("/api/config");
    if (cfg.desktop) {
      document.getElementById("modePill").innerHTML = '<span class="dot off"></span>Desktop · works offline';
    }
  } catch { /* the static page still works without these extras */ }
}

init();
