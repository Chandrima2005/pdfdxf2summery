// Shared helpers for both pages: theme, API calls, escaping, toasts, small SVG graphics.

// Theme is applied before first paint (see the inline script in each page head); dark by default.
const Theme = {
  get: () => { try { return localStorage.getItem("theme") || "dark"; } catch { return "dark"; } },
  set(t) {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("theme", t); } catch { /* private mode: theme just won't persist */ }
    document.querySelectorAll("[data-theme-toggle]").forEach(b => { b.textContent = t === "dark" ? "☀️ Light" : "🌙 Dark"; });
  },
  toggle() { Theme.set(Theme.get() === "dark" ? "light" : "dark"); },
};

function bindThemeToggle() {
  Theme.set(Theme.get());
  document.querySelectorAll("[data-theme-toggle]").forEach(b => b.addEventListener("click", Theme.toggle));
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(text, isError = false) {
  let el = document.querySelector(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
  el.textContent = text;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3500);
}

// Small animated "current" line used in the library header.
function waveSvg() {
  let d = "M0 11";
  for (let x = 4; x <= 140; x += 4) d += ` L${x} ${(11 + 7 * Math.sin(x / 10)).toFixed(1)}`;
  return `<svg class="wave" viewBox="0 0 140 22" preserveAspectRatio="none"><path class="wave-base" d="${d}"/><path class="wave-flow" d="${d}"/></svg>`;
}

// Fade sections in as they scroll into view.
function revealOnScroll() {
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }), { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach(el => io.observe(el));
}
