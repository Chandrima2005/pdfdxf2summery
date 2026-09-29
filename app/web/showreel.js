// Landing page: animated distribution board, floor plan and circuit, shown side by side.
// These are illustrations (the numbers on them are examples), animated with CSS only.

function boardSvg() {
  const loads = [["C1", "25A", "🔌", "Sockets", true], ["C2", "10A", "💡", "Lights", false], ["C3", "20A", "♨️", "Heater", false],
                 ["C4", "20A", "♨️", "Heater", false], ["C5", "32A", "🔌", "Sockets", true], ["C6", "16A", "💡", "Lights", false]];
  const mods = loads.map(([tag, amp, ico, name, rcd], i) => {
    const x = 58 + i * 60, cx = x + 22;
    return `<line class="wire" x1="${cx}" y1="114" x2="${cx}" y2="126"/>
      <g class="mcb" style="animation-delay:${(0.2 + i * 0.1).toFixed(2)}s">
        <rect class="mod" x="${x}" y="126" width="44" height="76" rx="7"/>
        <rect class="tog" x="${cx - 6}" y="138" width="12" height="20" rx="3"/>
        <circle class="led" cx="${cx}" cy="169" r="3.2" style="animation-delay:${(i * 0.4).toFixed(1)}s"/>
        <text class="lbl" x="${cx}" y="186">${tag}</text><text class="amp" x="${cx}" y="197">${amp}</text></g>
      <path class="wire" d="M${cx} 202 V256"/><path class="flow" d="M${cx} 202 V256" style="animation-delay:${(i * 0.15).toFixed(2)}s"/>
      <text class="ico" x="${cx}" y="278">${ico}</text><text class="nm" x="${cx}" y="296">${name}</text>
      ${rcd ? `<g class="rcdtag"><rect x="${x - 3}" y="222" width="50" height="15" rx="7.5"/><text x="${cx}" y="232.5">RCD 30mA</text></g>` : ""}`;
  }).join("");
  return `<svg class="dbsvg" viewBox="0 0 480 350" role="img" aria-label="Distribution board illustration">
    <defs><linearGradient id="dbg" x1="0" x2="1"><stop offset="0" stop-color="#4CC9F0"/><stop offset="1" stop-color="#8B5CF6"/></linearGradient></defs>
    <rect class="enc" x="30" y="22" width="420" height="318" rx="20"/>
    <text class="hdr" x="52" y="47">DB-01 · 230 V · 6 WAYS</text><circle class="led" cx="426" cy="43" r="4"/>
    <path class="wire" d="M240 0 V58"/><path class="flow" d="M240 0 V58"/>
    <rect class="main" x="203" y="58" width="74" height="36" rx="7"/><text class="mainlbl" x="240" y="81">MAIN 63A</text>
    <path class="wire" d="M240 94 V110"/><path class="flow" d="M240 94 V110"/>
    <rect x="70" y="109" width="340" height="6" rx="3" fill="url(#dbg)"/>
    ${mods}
    <rect class="scanbar" x="52" y="121" width="56" height="86" rx="9"/>
    <g class="result"><rect x="110" y="306" width="260" height="26" rx="13"/><text x="240" y="323">✓ 6 circuits · 9.2 kW · RCDs OK</text></g>
  </svg>`;
}

function planSvg() {
  const rooms = [["LIVING", "21.6 m²", 60, 62, 180, 120], ["KITCHEN", "18.4 m²", 240, 62, 180, 120], ["BEDROOM 1", "13.0 m²", 60, 182, 130, 100],
                 ["", "", 190, 182, 60, 100], ["BEDROOM 2", "9.0 m²", 250, 182, 90, 100], ["BATH", "5.6 m²", 340, 182, 80, 100]];
  const parts = rooms.map(([name, area, x, y, w, h], i) =>
    `<rect class="room" x="${x}" y="${y}" width="${w}" height="${h}" style="animation-delay:${(i * 0.7).toFixed(1)}s"/>
     <rect class="wall" x="${x}" y="${y}" width="${w}" height="${h}"/>
     ${name ? `<text class="lbl" x="${x + w / 2}" y="${y + h / 2 - 2}">${name}</text><text class="amp" x="${x + w / 2}" y="${y + h / 2 + 12}">${area}</text>` : ""}`).join("");
  return `<svg class="dbsvg" viewBox="0 0 480 350" role="img" aria-label="Floor plan illustration">
    <rect class="enc" x="30" y="22" width="420" height="318" rx="20"/>
    <text class="hdr" x="52" y="47">PLAN-01 · 1:100 · GROUND FLOOR</text><circle class="led" cx="426" cy="43" r="4"/>
    ${parts}
    <rect class="wall outer" x="60" y="62" width="360" height="220"/>
    <line class="win" x1="100" y1="62" x2="170" y2="62"/><line class="win" x1="300" y1="62" x2="370" y2="62"/>
    <line class="win" x1="60" y1="210" x2="60" y2="250"/><line class="win" x1="270" y1="282" x2="320" y2="282"/><line class="win" x1="420" y1="200" x2="420" y2="240"/>
    <path class="door" d="M190 212 A26 26 0 0 0 164 238"/><path class="door" d="M250 212 A26 26 0 0 1 276 238"/>
    <path class="door" d="M205 182 A26 26 0 0 1 231 156"/><path class="door" d="M340 250 A24 24 0 0 1 364 226"/>
    <path class="dim" d="M192 262 H248 M192 256 V268 M248 256 V268"/><text class="dimtxt" x="220" y="252">1.2 m</text>
    <g class="result"><rect x="100" y="306" width="280" height="26" rx="13"/><text x="240" y="323">✓ 5 rooms · corridor 1.2 m ≥ 1.1 m</text></g>
  </svg>`;
}

function zigzag(x, y0, y1, n = 6, amp = 7) {
  const step = (y1 - y0) / n;
  let d = `M${x} ${y0}`;
  for (let i = 0; i < n; i++) d += ` L${x + (i % 2 ? amp : -amp)} ${(y0 + step * (i + 0.5)).toFixed(1)}`;
  return `${d} L${x} ${y1}`;
}

function circuitSvg() {
  const top = "M88 170 H120 V110 H190 M270 110 H420";
  const gnd = "M88 210 H120 V270 H420 M230 132 V270";
  const branches = "M300 110 V172 M300 182 V270 M350 110 V148 M350 192 V206 M350 226 V270 M400 110 V128 M400 164 V184 M400 220 V270";
  return `<svg class="dbsvg" viewBox="0 0 480 350" role="img" aria-label="Circuit illustration">
    <rect class="enc" x="30" y="22" width="420" height="318" rx="20"/>
    <text class="hdr" x="52" y="47">CKT-01 · 5 V REGULATOR</text><circle class="led" cx="426" cy="43" r="4"/>
    <path class="wire" d="${top} ${gnd} ${branches}"/>
    <path class="flow" d="${top}"/><path class="flow" d="M300 110 V172 M350 110 V148 M400 110 V128" style="animation-delay:.3s"/>
    <rect class="comp" x="52" y="150" width="36" height="80" rx="6"/><text class="lbl" x="70" y="245">J1</text>
    <circle class="node" cx="88" cy="170" r="3"/><circle class="node" cx="88" cy="210" r="3"/>
    <rect class="comp" x="190" y="88" width="80" height="44" rx="7"/><text class="lbl" x="230" y="108">U1</text><text class="amp" x="230" y="122">REG-5V</text>
    <line class="plate" x1="288" y1="174" x2="312" y2="174"/><line class="plate" x1="288" y1="181" x2="312" y2="181"/>
    <text class="lbl start" x="322" y="170">C1</text><text class="amp start" x="322" y="182">10µF</text>
    <path class="res" d="${zigzag(350, 148, 192)}"/><text class="lbl start" x="362" y="168">R1</text><text class="amp start" x="362" y="180">330Ω</text>
    <path class="ledfill" d="M340 206 H360 L350 224 Z"/><line class="plate" x1="340" y1="226" x2="360" y2="226"/>
    <path class="res" d="${zigzag(400, 128, 164)}"/><path class="res" d="${zigzag(400, 184, 220)}"/>
    <text class="lbl start" x="412" y="148">R2</text><text class="lbl start" x="412" y="204">R3</text>
    <circle class="node" cx="400" cy="174" r="3.5"/><circle class="node" cx="300" cy="110" r="3"/>
    <circle class="node" cx="350" cy="110" r="3"/><circle class="node" cx="400" cy="110" r="3"/>
    <text class="nm" x="120" y="104">+12 V</text><text class="nm" x="120" y="286">GND</text>
    <g class="result"><rect x="110" y="306" width="260" height="26" rx="13"/><text x="240" y="323">✓ 7 components · R3 = 1 kΩ</text></g>
  </svg>`;
}

function trio() {
  const items = [
    ["db", "⚡ Distribution board", "Circuits, loads, RCDs", "db-001.dxf", boardSvg()],
    ["plan", "🏠 Building plan", "Rooms, widths, windows", "plan-001.dxf", planSvg()],
    ["ckt", "🔌 Electronic circuit", "Parts, values, nets", "ckt-001.dxf", circuitSvg()],
  ];
  return items.map(([k, title, sub, sample, svg], i) => `
    <a class="trio-item t-${k}" href="/app?sample=${sample}" style="animation-delay:${0.15 + i * 0.12}s">
      <div class="trio-cap"><span><b>${title}</b><small>${sub}</small></span><em>Try it →</em></div>
      ${svg}
    </a>`).join("");
}
