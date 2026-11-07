// Local SVG icons: no external font or network dependency.
const paths = {
  owner_portal: 'M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
  pos: 'M4 3h16v14H4z M8 21h8 M12 17v4 M7 7h10 M7 11h3',
  orders: 'M6 3h12v18l-3-2-3 2-3-2-3 2z M9 7h6 M9 11h6 M9 15h3',
  products: 'm12 3 9 5v9l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v9 M7 5l9 5',
  inventory: 'M3 21V8l9-5 9 5v13 M7 21V11h10v10 M7 15h10 M7 19h10',
  map: 'm3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2z M9 3v16 M15 5v16',
  customers: 'M8 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M1 21v-3a7 7 0 0 1 14 0v3 M17 3a4 4 0 0 1 0 8 M18 14a6 6 0 0 1 5 6',
  suppliers: 'M2 5h13v13H2z M15 10h4l3 4v4h-7 M5 18a2 2 0 1 0 4 0 M16 18a2 2 0 1 0 4 0',
  cash: 'M3 5h18v15H3z M3 9h18 M15 13h6v4h-6z M6 3h12',
  hr: 'M4 5h16v16H4z M8 3v4 M16 3v4 M4 11h16 M8 15h2 M14 15h2',
  reports: 'M4 3v18h17 M8 16v-5 M13 16V6 M18 16V9',
  suggestions: 'm12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z',
  settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
};
export function navIcon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({viewBox:'0 0 24 24', fill:'none', stroke:'currentColor', 'stroke-width':'1.6', 'stroke-linecap':'round', 'stroke-linejoin':'round', 'aria-hidden':'true', class:'nav-svg'})) svg.setAttribute(key, value);
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', paths[name] || paths[name === 'cashier_portal' ? 'pos' : name === 'inventory_portal' ? 'inventory' : 'suppliers']);
  svg.append(path);
  return svg;
}
