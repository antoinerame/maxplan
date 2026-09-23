/* TGV Max Planner — interface */
'use strict';
(() => {
  /* ================================================================== utilitaires */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const store = {
    get(k, d) { try { const v = localStorage.getItem('tmp.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('tmp.' + k, JSON.stringify(v)); } catch { /* stockage indisponible */ } },
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const fmtPrice = v => (v === 0 ? 'Gratuit' : `≈ ${nf.format(v)} €`);
  const fmtDur = m => (m == null ? '' : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`);
  const toMin = hm => { const [h, m] = String(hm || '0:0').split(':').map(Number); return h * 60 + m; };
  const DAYS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
  const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const noon = iso => new Date(iso + 'T12:00:00');
  const isoOf = d => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
  const todayISO = () => isoOf(new Date());
  const addDays = (iso, n) => { const d = noon(iso); d.setDate(d.getDate() + n); return isoOf(d); };
  const fmtDay = iso => { const d = noon(iso); return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  const fmtShort = iso => { const d = noon(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
  const isMobile = () => matchMedia('(max-width: 899px)').matches;
  const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  const svg = p => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
  const ICON = {
    swap: svg('<path d="M7 20V4M3.5 7.5 7 4l3.5 3.5M17 4v16M13.5 16.5 17 20l3.5-3.5"/>'),
    locate: svg('<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>'),
    search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>'),
    star: svg('<path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.6 9.7l5.8-.8z"/>'),
    share: svg('<path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/>'),
    user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>'),
    sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    moon: svg('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>'),
    auto: svg('<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17z" fill="currentColor"/>'),
    ext: svg('<path d="M14 4h6v6M20 4l-8 8M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'),
    trash: svg('<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>'),
  };

  let toastTimer;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3800);
  }

  async function api(path, params = {}) {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null));
    let res;
    try { res = await fetch(`${path}?${qs}`, { headers: { Accept: 'application/json' } }); }
    catch { throw new Error('Connexion au serveur impossible — vérifie ta connexion internet.'); }
    let data = null;
    try { data = await res.json(); } catch { /* réponse non JSON */ }
    if (!res.ok) throw new Error(data?.error || `Le serveur a répondu ${res.status}.`);
    return data;
  }

  /* ================================================================== état */
  const state = {
    meta: null, tab: 'search',
    days: [], selKey: null, current: null, toCoord: null, searchSeq: 0, lastParams: null,
    sort: store.get('sort', 'dep'), freeOnly: store.get('freeOnly', false),
    explore: null, exFilter: '',
  };
  let profile = Object.assign({ sub: 'jeune', ter: {} }, store.get('profile', {}));
  let favs = store.get('favs', []);
  let theme = store.get('theme', 'auto');

  const profileParams = () => ({
    sub: profile.sub,
    ter_disc: Object.entries(profile.ter).filter(([, v]) => v > 0).map(([k, v]) => `${k}:${v}`).join(','),
  });

  /* ================================================================== carte */
  // Limites de déplacement : la France avec de la marge (pour pouvoir décaler la carte au-dessus du
  // panneau mobile) ; le dézoom reste bloqué au niveau national par minZoom.
  const FR_BOUNDS = L.latLngBounds([36.5, -10.5], [55, 16]);
  const METRO = L.latLngBounds([42.3, -4.9], [51.1, 8.4]);
  // Relief ombré sans aucun libellé (les noms, en français, sont posés par l'app).
  // En thème sombre, la même couche est inversée par filtre CSS (--tile-filter).
  const TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}';
  // Libellés en français (niveau 1 visible dès le zoom national, 2 et 3 en zoomant)
  const CITIES = [
    [1, 'Paris', 48.8566, 2.3522], [1, 'Lyon', 45.764, 4.8357], [1, 'Marseille', 43.2965, 5.3698], [1, 'Toulouse', 43.6047, 1.4442],
    [1, 'Bordeaux', 44.8378, -0.5792], [1, 'Lille', 50.6292, 3.0573], [1, 'Nantes', 47.2184, -1.5536], [1, 'Strasbourg', 48.5734, 7.7521],
    [1, 'Nice', 43.7102, 7.262], ['1 t1b', 'Montpellier', 43.6108, 3.8767], ['1 t1b', 'Rennes', 48.1173, -1.6778],
    [2, 'Reims', 49.2583, 4.0317], [2, 'Le Havre', 49.4944, 0.1079], [2, 'Saint-Étienne', 45.4397, 4.3872], [2, 'Toulon', 43.1242, 5.928],
    [2, 'Grenoble', 45.1885, 5.7245], [2, 'Dijon', 47.322, 5.0415], [2, 'Angers', 47.4784, -0.5632], [2, 'Nîmes', 43.8367, 4.3601],
    [2, 'Clermont-Ferrand', 45.7772, 3.087], [2, 'Le Mans', 48.0061, 0.1996], [2, 'Aix-en-Provence', 43.5297, 5.4474], [2, 'Brest', 48.3904, -4.4861],
    [2, 'Tours', 47.3941, 0.6848], [2, 'Amiens', 49.8941, 2.2958], [2, 'Limoges', 45.8336, 1.2611], [2, 'Perpignan', 42.6887, 2.8948],
    [2, 'Metz', 49.1193, 6.1757], [2, 'Besançon', 47.2378, 6.0241], [2, 'Orléans', 47.903, 1.9093], [2, 'Rouen', 49.4432, 1.0999],
    [2, 'Caen', 49.1829, -0.3707], [2, 'Nancy', 48.6921, 6.1844], [2, 'Avignon', 43.9493, 4.8055], [2, 'Poitiers', 46.5802, 0.3404],
    [2, 'La Rochelle', 46.1603, -1.1511], [2, 'Pau', 43.2951, -0.3708], [2, 'Mulhouse', 47.7508, 7.3359], [2, 'Bayonne', 43.4929, -1.4748],
    [2, 'Ajaccio', 41.9192, 8.7386], [2, 'Bastia', 42.697, 9.4509], [2, 'Annecy', 45.8992, 6.1294], [2, 'Chambéry', 45.5646, 5.9178],
    [3, 'Valence', 44.9334, 4.8924], [3, 'Béziers', 43.3442, 3.2158], [3, 'Narbonne', 43.184, 3.0039], [3, 'Arcachon', 44.6586, -1.1681],
    [3, 'Angoulême', 45.6484, 0.1562], [3, 'Brive-la-Gaillarde', 45.1589, 1.5331], [3, 'Agen', 44.2033, 0.6163], [3, 'Carcassonne', 43.213, 2.3491],
    [3, 'Montauban', 44.0176, 1.355], [3, 'Troyes', 48.2973, 4.0744], [3, 'Calais', 50.9513, 1.8587], [3, 'Dunkerque', 51.0343, 2.3768],
    [3, 'Arras', 50.291, 2.7775], [3, 'Saint-Malo', 48.6493, -2.0257], [3, 'Quimper', 47.996, -4.1024], [3, 'Vannes', 47.6582, -2.7608],
    [3, 'Lorient', 47.7482, -3.3702], [3, 'Laval', 48.0707, -0.7734], [3, 'Cherbourg', 49.6337, -1.6222], [3, 'Colmar', 48.0794, 7.3585],
    [3, 'Belfort', 47.6397, 6.8638], [3, 'Mâcon', 46.3069, 4.8287], [3, 'Bourg-en-Bresse', 46.2052, 5.2255], [3, 'Gap', 44.5594, 6.0786],
    [3, 'Briançon', 44.8986, 6.6432], [3, 'Manosque', 43.8352, 5.7911], [3, 'Tarbes', 43.2328, 0.0781], [3, 'Rodez', 44.3506, 2.575],
    [3, 'Aurillac', 44.9264, 2.44], [3, 'Le Puy-en-Velay', 45.0434, 3.8858], [3, 'Vichy', 46.1277, 3.4263], [3, 'Nevers', 46.991, 3.159],
    [3, 'Bourges', 47.081, 2.3988], [3, 'Châteauroux', 46.8103, 1.6913], [3, 'Blois', 47.5861, 1.3359], [3, 'Chartres', 48.4439, 1.489],
    [3, 'Niort', 46.3237, -0.4648], [3, 'Saint-Brieuc', 48.5136, -2.7603], [3, 'Épinal', 48.1724, 6.4496], [3, 'Charleville-Mézières', 49.7621, 4.7263],
    [3, 'Châlons-en-Champagne', 48.9566, 4.3631], [3, 'Thionville', 49.3579, 6.1683], [3, 'Cannes', 43.5528, 7.0174], [3, 'Menton', 43.7747, 7.4975],
    [3, 'Sète', 43.4029, 3.697], [3, 'Alès', 44.125, 4.0816], [3, 'Albi', 43.9289, 2.1464], [3, 'Cahors', 44.4475, 1.4419],
    [3, 'Périgueux', 45.1846, 0.7214], [3, 'Dax', 43.7102, -1.0535], [3, 'Lens', 50.432, 2.8333], [3, 'Valenciennes', 50.357, 3.5231],
    [3, 'Saint-Quentin', 49.8465, 3.2876], [3, 'Beauvais', 49.4295, 2.0807], [3, 'Auxerre', 47.7982, 3.5673], [3, 'Chalon-sur-Saône', 46.7806, 4.8539],
    [3, 'Boulogne-sur-Mer', 50.7264, 1.6147], [3, 'Hendaye', 43.3587, -1.7745], [3, 'Lourdes', 43.0947, -0.0459], [3, 'Montluçon', 46.3405, 2.6023],
    [3, 'Moulins', 46.5646, 3.3326], [3, 'Saint-Nazaire', 47.2735, -2.2138], [3, 'Morlaix', 48.5776, -3.828], [3, 'Dieppe', 49.9229, 1.0775],
    [3, 'Épernay', 49.04, 3.9594], [3, 'Verdun', 49.1599, 5.3844], [3, 'Vesoul', 47.623, 6.1557], [3, 'Lons-le-Saunier', 46.6741, 5.5559],
    [3, 'Aix-les-Bains', 45.6886, 5.9153], [3, 'Bourg-Saint-Maurice', 45.6186, 6.7687], [3, 'Modane', 45.2003, 6.6696], [3, 'Montélimar', 44.5581, 4.7509],
    [3, 'Arles', 43.6766, 4.6278], [3, 'Digne-les-Bains', 44.0925, 6.2356], [3, 'Millau', 44.0986, 3.0777], [3, 'Auch', 43.6465, 0.5855],
    [3, 'Libourne', 44.9153, -0.2436], [3, 'Saintes', 45.7466, -0.6331], [3, 'La Roche-sur-Yon', 46.6705, -1.426], [3, 'Les Sables-d\'Olonne', 46.4966, -1.7837],
    [3, 'Cholet', 47.0606, -0.8791], [3, 'Saumur', 47.26, -0.0769], [3, 'Alençon', 48.4329, 0.0913], [3, 'Évreux', 49.027, 1.1508],
  ];
  const REGION_LABELS = [
    ['Hauts-de-<br>France', 49.95, 2.75], ['Normandie', 49.05, 0.25], ['Grand Est', 48.75, 5.35], ['Bretagne', 48.15, -3.05],
    ['Pays de<br>la Loire', 47.5, -0.95], ['Centre-<br>Val de Loire', 47.35, 1.65], ['Bourgogne-<br>Franche-Comté', 47.2, 4.55],
    ['Nouvelle-<br>Aquitaine', 45.45, 0.35], ['Auvergne-<br>Rhône-Alpes', 45.1, 3.7], ['Occitanie', 44.0, 2.65],
    ['Provence-Alpes-<br>Côte d\'Azur', 44.15, 6.3], ['Corse', 42.2, 9.1],
  ];
  const MAP = {};

  function initMap() {
    const map = L.map('map', { zoomControl: false, minZoom: 5, maxZoom: 13, zoomSnap: 0.5, maxBounds: FR_BOUNDS, maxBoundsViscosity: 1 });
    MAP.map = map;
    L.control.zoom({ position: 'topright', zoomInTitle: 'Zoomer', zoomOutTitle: 'Dézoomer' }).addTo(map);
    map.attributionControl.setPrefix(false);
    for (const [name, z] of [['mask', 350], ['labels', 380], ['casing', 395]]) {
      const p = map.createPane(name);
      p.style.zIndex = z;
      p.style.pointerEvents = 'none';
    }
    MAP.tiles = L.tileLayer(TILE_URL, { maxNativeZoom: 13, maxZoom: 13, attribution: 'Relief © Esri, USGS, NOAA · Contours © IGN / data.gouv.fr' }).addTo(map);
    map.fitBounds(METRO);
    MAP.route = L.layerGroup().addTo(map);
    MAP.hover = L.layerGroup().addTo(map);

    // la France mise en avant : l'étranger est estompé, contours des régions discrets.
    // Rendu SVG avec une large marge pour que le voile couvre toujours tout l'écran.
    const maskRenderer = L.svg({ pane: 'mask', padding: 1.5 });
    fetch('/geo/france.json').then(r => r.json()).then(fr => {
      const holes = fr.geometry.coordinates.map(poly => poly[0].map(([x, y]) => [y, x]));
      MAP.mask = L.polygon([[[85, -180], [85, 180], [-85, 180], [-85, -180]], ...holes],
        { renderer: maskRenderer, stroke: false, interactive: false }).addTo(map);
      MAP.outline = L.polyline(holes.map(h => [...h, h[0]]), { renderer: maskRenderer, weight: 1.4, interactive: false }).addTo(map);
      styleMapOverlays();
    }).catch(() => {});
    fetch('/geo/regions.json').then(r => r.json()).then(rg => {
      MAP.borders = L.geoJSON(rg, { renderer: maskRenderer, interactive: false, style: () => ({ fill: false, weight: 0.9, dashArray: '3 5' }) }).addTo(map);
      styleMapOverlays();
    }).catch(() => {});

    for (const [tier, name, lat, lon] of CITIES) {
      L.marker([lat, lon], {
        pane: 'labels', interactive: false, keyboard: false,
        icon: L.divIcon({ className: `lbl city t${tier}`, html: `<span>${esc(name)}</span>`, iconSize: [0, 0] }),
      }).addTo(map);
    }
    for (const [name, lat, lon] of REGION_LABELS) {
      L.marker([lat, lon], {
        pane: 'labels', interactive: false, keyboard: false,
        icon: L.divIcon({ className: 'lbl region', html: `<span>${name}</span>`, iconSize: [0, 0] }),
      }).addTo(map);
    }
    // libellés révélés selon le zoom pour ne jamais se chevaucher
    const syncZoom = () => {
      const z = map.getZoom(), c = map.getContainer().classList;
      c.toggle('z-lt6', z < 6); c.toggle('z-lt7', z < 7); c.toggle('z-lt8', z < 8); c.toggle('z-ge7', z >= 7);
    };
    map.on('zoomend', syncZoom);
    syncZoom();
    // la carte suit la taille de la fenêtre (rotation du téléphone…) et recadre ce qui est affiché
    let rt;
    addEventListener('resize', () => {
      clearTimeout(rt);
      rt = setTimeout(() => {
        map.invalidateSize();
        if (MAP.route.getLayers().length && MAP.lastFit) fitTo(...MAP.lastFit);
        else map.fitBounds(METRO);
      }, 200);
    });
  }


  function styleMapOverlays() {
    MAP.mask?.setStyle({ fillColor: cssVar('--map-mask'), fillOpacity: Number(cssVar('--map-mask-op')) || 0.6 });
    MAP.outline?.setStyle({ color: cssVar('--map-border'), opacity: 0.9 });
    MAP.borders?.setStyle({ color: cssVar('--map-border'), opacity: 0.55 });
  }

  function mapTheme() {
    if (!MAP.map) return;
    styleMapOverlays();
    if (state.tab === 'search' && state.current) drawItinerary(state.current, false);
    if (state.tab === 'explore' && state.explore) drawExplore(state.explore, false);
  }

  function fitTo(pts, maxZoom = 10) {
    const map = MAP.map;
    MAP.lastFit = [pts, maxZoom];
    if (!pts.length) { map.fitBounds(METRO); return; }
    if (pts.length === 1) { map.setView(pts[0], 9); return; }
    let opts = { padding: [56, 56], maxZoom };
    if (isMobile()) {
      const sheet = Math.min($('#panel').getBoundingClientRect().height, innerHeight * 0.66);
      opts = { paddingTopLeft: [28, 64], paddingBottomRight: [28, sheet + 20], maxZoom };
    }
    map.fitBounds(L.latLngBounds(pts), opts);
  }

  function clearMap() { MAP.route?.clearLayers(); MAP.hover?.clearLayers(); }

  function drawItinerary(it, fit = true) {
    clearMap();
    const pts = [];
    const free = cssVar('--free'), paid = cssVar('--paid'), casing = cssVar('--route-casing');
    const ink = cssVar('--ink'), surface = cssVar('--surface');
    // points des arrêts successifs ; une gare sans coordonnées est « sautée » (le trait relie ses voisines)
    const P = it.legs.map(l => (l.from_lat != null ? [l.from_lat, l.from_lon] : null));
    const lastLeg = it.legs[it.legs.length - 1];
    P.push(lastLeg.to_lat != null ? [lastLeg.to_lat, lastLeg.to_lon] : null);
    it.legs.forEach((l, i) => { if (!P[i + 1] && l.to_lat != null) P[i + 1] = [l.to_lat, l.to_lon]; });
    const known = (i, step) => { for (let k = i; k >= 0 && k < P.length; k += step) if (P[k]) return P[k]; return null; };
    it.legs.forEach((l, i) => {
      let c = (!l.free && l.path && l.path.length > 1) ? l.path : [known(i, -1), known(i + 1, 1)];
      c = c.filter(p => p && p[0] != null);
      if (c.length < 2 || (c.length === 2 && c[0][0] === c[1][0] && c[0][1] === c[1][1])) return;
      pts.push(...c);
      L.polyline(c, { pane: 'casing', color: casing, weight: 10, opacity: 0.95, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(MAP.route);
      L.polyline(c, { color: l.free ? free : paid, weight: 5, opacity: 1, lineCap: 'round', lineJoin: 'round', dashArray: l.free ? null : '1 10', interactive: false }).addTo(MAP.route);
    });
    const stops = it.legs.map((l, i) => ({ lat: l.from_lat, lon: l.from_lon, name: l.from_name, time: l.dep, kind: i ? 'change' : 'start' }));
    const last = it.legs[it.legs.length - 1];
    stops.push({ lat: last.to_lat, lon: last.to_lon, name: last.to_name, time: last.arr, kind: 'end' });
    stops.forEach((s, i) => {
      if (s.lat == null) return;
      const left = i % 2 === 1;   // arrêts successifs : étiquettes alternées pour éviter qu'elles se chevauchent
      L.circleMarker([s.lat, s.lon], { radius: s.kind === 'change' ? 5 : 7, color: ink, weight: 3, fillColor: s.kind === 'end' ? ink : surface, fillOpacity: 1 })
        .addTo(MAP.route)
        .bindTooltip(`<b>${esc(s.time)}</b>${esc(s.name)}`, { permanent: true, direction: left ? 'left' : 'right', offset: [left ? -10 : 10, 0], className: 'stop-tip' });
    });
    if (fit) fitTo(pts);
  }

  function drawExplore(data, fit = true) {
    clearMap();
    const o = data.origin;
    const oll = o.lat != null ? [o.lat, o.lon] : null;
    const pts = oll ? [oll] : [];
    const free = cssVar('--free'), via = cssVar('--via'), ink = cssVar('--ink'), surface = cssVar('--surface');
    const highlight = (d, col) => {
      MAP.hover.clearLayers();
      if (oll) L.polyline([oll, [d.lat, d.lon]], { color: col, weight: 4, opacity: 1, dashArray: d.nconn ? '6 6' : null, interactive: false }).addTo(MAP.hover);
    };
    const n = data.destinations.length;
    const faint = n > 100 ? 0.22 : n > 50 ? 0.32 : 0.5;   // beaucoup de destinations : traits plus légers
    for (const d of data.destinations) {
      const col = d.nconn ? via : free, ll = [d.lat, d.lon];
      pts.push(ll);
      if (oll) {
        L.polyline([oll, ll], { color: col, weight: n > 100 ? 1.2 : 1.6, opacity: faint, dashArray: d.nconn ? '4 6' : null, interactive: false }).addTo(MAP.route);
        L.polyline([oll, ll], { color: col, weight: 14, opacity: 0 }).addTo(MAP.route)
          .on('mouseover', () => highlight(d, col)).on('mouseout', () => MAP.hover.clearLayers())
          .on('click', () => exploreToItinerary(d));
      }
      L.circleMarker(ll, { radius: 5.5, color: surface, weight: 1.5, fillColor: col, fillOpacity: 1 })
        .addTo(MAP.route)
        .bindTooltip(`<b>${esc(d.dep)}</b>${esc(d.name)}${d.nconn ? `<span class="tip-via">via ${esc(d.via.join(', '))}</span>` : ''}`,
          { direction: 'top', offset: [0, -4], className: 'stop-tip' })
        .on('mouseover', () => highlight(d, col)).on('mouseout', () => MAP.hover.clearLayers())
        .on('click', () => exploreToItinerary(d));
    }
    if (oll) {
      L.circleMarker(oll, { radius: 8, color: ink, weight: 3, fillColor: surface, fillOpacity: 1 }).addTo(MAP.route)
        .bindTooltip(esc(o.name), { permanent: true, direction: 'right', offset: [10, 0], className: 'stop-tip' });
    }
    if (fit) fitTo(pts, 8);
  }

  /* ================================================================== thème */
  function applyTheme() {
    const root = document.documentElement;
    if (theme === 'auto') root.removeAttribute('data-theme'); else root.dataset.theme = theme;
    const label = { auto: 'automatique', light: 'clair', dark: 'sombre' }[theme];
    const b = $('#btn-theme');
    b.innerHTML = ICON[theme === 'auto' ? 'auto' : theme === 'dark' ? 'moon' : 'sun'];
    b.setAttribute('aria-label', `Thème ${label} — changer`);
    b.title = `Thème : ${label}`;
    mapTheme();
  }

  /* ================================================================== champs gare (autocomplétion) */
  const stationValue = input => input.dataset.label || input.value.trim();
  function setStation(input, name, label) {
    input.value = name || '';
    input.dataset.label = label || '';
  }

  function attachAC(input, kind) {
    const list = $('#ac-' + input.id);
    let items = [], active = -1, seq = 0, timer;
    const close = () => { list.hidden = true; active = -1; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); };
    const render = () => {
      if (!items.length) { close(); return; }
      list.innerHTML = items.map((it, i) =>
        `<li role="option" id="${list.id}-${i}" data-i="${i}" aria-selected="${i === active}"><span>${esc(it.name)}</span>` +
        `<em class="tag ${it.max ? 'max' : 'ter'}">${it.max ? 'TGV Max' : 'TER'}</em></li>`).join('');
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      if (active >= 0) input.setAttribute('aria-activedescendant', `${list.id}-${active}`);
    };
    const pick = i => { const it = items[i]; if (!it) return; setStation(input, it.name, it.label); close(); syncFav(); };
    input.addEventListener('input', () => {
      input.dataset.label = '';
      syncFav();
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { items = []; close(); return; }
      timer = setTimeout(async () => {
        const my = ++seq;
        try {
          const r = await api('/api/stations', { q, kind });
          if (my !== seq) return;
          items = r; active = -1; render();
        } catch { /* silencieux : on garde la saisie libre */ }
      }, 150);
    });
    input.addEventListener('keydown', e => {
      if (list.hidden || !items.length) return;
      if (e.key === 'ArrowDown') { active = (active + 1) % items.length; render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
      else if (e.key === 'Enter' && active >= 0) { pick(active); e.preventDefault(); }
      else if (e.key === 'Escape') close();
    });
    list.addEventListener('mousedown', e => { const li = e.target.closest('li'); if (li) { e.preventDefault(); pick(Number(li.dataset.i)); } });
    input.addEventListener('blur', () => setTimeout(close, 120));
    input.addEventListener('focus', () => { if (isMobile() && $('#panel').dataset.sheet === 'peek') setSheet('full'); });
  }

  function locate(input) {
    if (!navigator.geolocation) { toast("La localisation n'est pas disponible sur ce navigateur."); return; }
    toast('Recherche de ta position…');
    navigator.geolocation.getCurrentPosition(async pos => {
      try {
        // position arrondie (~1 km) : suffisant pour trouver la gare, sans plus de précision que nécessaire
        const r = await api('/api/nearest', { lat: pos.coords.latitude.toFixed(2), lon: pos.coords.longitude.toFixed(2) });
        if (!r.length) { toast('La liste des gares se prépare encore, réessaie dans une minute.'); return; }
        setStation(input, r[0].name, r[0].label);
        syncFav();
        toast(`Gare TGV Max la plus proche : ${r[0].name} (${r[0].km} km)`);
      } catch (e) { toast(e.message); }
    }, () => toast("Position refusée ou indisponible. Tape le nom de ta gare."), { timeout: 10000, maximumAge: 600000 });
  }

  /* ================================================================== formulaire */
  const segVal = name => $(`.seg[data-name="${name}"] [aria-pressed="true"]`)?.dataset.v;
  function setSeg(name, v) {
    $$(`.seg[data-name="${name}"] button`).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === String(v))));
  }

  function clampDate(iso) {
    if (!state.meta?.dates?.start) return iso;
    const { start, end } = state.meta.dates;
    return iso < start ? start : iso > end ? end : iso;
  }
  function setDates(fd, td) {
    $('#s-fd').value = clampDate(fd);
    $('#s-td').value = clampDate(td || fd);
    markQuick();
  }
  function quickRange(kind) {
    const t = todayISO(), dow = noon(t).getDay();
    if (kind === 'today') return [t, t];
    if (kind === 'tomorrow') return [addDays(t, 1), addDays(t, 1)];
    if (kind === 'week') return [t, addDays(t, 6)];
    // week-end : du vendredi au dimanche (ou à partir d'aujourd'hui si on y est déjà)
    if (dow === 0) return [t, t];
    if (dow === 6) return [t, addDays(t, 1)];
    if (dow === 5) return [t, addDays(t, 2)];
    const fri = addDays(t, 5 - dow);
    return [fri, addDays(fri, 2)];
  }
  function markQuick() {
    const fd = $('#s-fd').value, td = $('#s-td').value;
    $$('.chip[data-quick]').forEach(c => {
      const [a, b] = quickRange(c.dataset.quick).map(clampDate);
      c.setAttribute('aria-pressed', String(a === fd && b === td));
    });
  }

  function updateOptsSummary() {
    const mc = segVal('maxconn'), ter = $('#s-ter').checked, tt = segVal('ter_transfers'), n = $('#s-nights').checked;
    $('#row-tt').hidden = !ter;
    const parts = [mc === '0' ? 'TGV Max direct' : `${plural(Number(mc), 'corresp.', 'corresp.')} Max`,
      ter ? `TER (${tt} corresp.)` : 'sans TER', n ? 'nuit incluse' : 'sans nuit'];
    $('#opts-sum').textContent = parts.join(' · ');
  }

  function formState() {
    return {
      f: $('#s-from').value.trim(), fl: $('#s-from').dataset.label || '',
      t: $('#s-to').value.trim(), tl: $('#s-to').dataset.label || '',
      du: $('#s-fd').value, au: $('#s-td').value, h1: $('#s-start').value, h2: $('#s-end').value,
      mc: segVal('maxconn'), ter: $('#s-ter').checked ? '1' : '0', tc: segVal('ter_transfers'), n: $('#s-nights').checked ? '1' : '0',
    };
  }
  function applyState(s) {
    if (s.f != null) setStation($('#s-from'), s.f, s.fl);
    if (s.t != null) setStation($('#s-to'), s.t, s.tl);
    if (s.du) setDates(s.du, s.au || s.du);
    $('#s-start').value = s.h1 || '';
    $('#s-end').value = s.h2 || '';
    if (s.mc != null) setSeg('maxconn', s.mc);
    if (s.ter != null) $('#s-ter').checked = s.ter !== '0';
    if (s.tc != null) setSeg('ter_transfers', s.tc);
    if (s.n != null) $('#s-nights').checked = s.n === '1';
    updateOptsSummary();
    syncFav();
  }
  function shareURL() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(formState())) if (v !== '' && v != null) p.set(k, v);
    return `${location.origin}/?${p}`;
  }

  /* ================================================================== recherche */
  async function runSearch() {
    const fromIn = $('#s-from'), toIn = $('#s-to');
    const from = stationValue(fromIn), to = stationValue(toIn);
    if (!from || !to) { toast("Indique une gare de départ et une gare d'arrivée."); (from ? toIn : fromIn).focus(); return; }
    let fd = $('#s-fd').value, td = $('#s-td').value || fd;
    if (!fd) { toast('Choisis une date de départ.'); return; }
    if (td < fd) [fd, td] = [td, fd];
    const days = [];
    for (let d = fd; d <= td && days.length < 31; d = addDays(d, 1)) days.push(d);
    const start = $('#s-start').value, end = $('#s-end').value;
    const common = {
      from, to, maxconn: segVal('maxconn'), ter: $('#s-ter').checked ? 1 : 0, ter_transfers: segVal('ter_transfers'),
      nights: $('#s-nights').checked ? 1 : 0, ...profileParams(),
    };
    const token = ++state.searchSeq;
    state.days = days.map(d => ({ date: d, loading: true }));
    state.selKey = null; state.current = null;
    state.lastParams = { from, to };
    clearMap();
    renderResults();
    store.set('last', formState());
    history.replaceState(null, '', shareURL().replace(location.origin, ''));
    if (isMobile()) {
      document.activeElement?.blur();
      setSheet('half');
      $('#scroll').scrollTo({ top: $('#results').offsetTop, behavior: 'smooth' });   // aller droit aux résultats
    }
    $('#btn-search').disabled = true;

    const queue = [...days];
    const worker = async () => {
      while (queue.length) {
        const d = queue.shift();
        const params = { ...common, from_date: d, to_date: d };
        if (d === fd && start) params.start = start;
        if (d === td && end) params.end = end;
        let day;
        try {
          const r = await api('/api/search', params);
          day = r.days[0];
          if (r.to_coord) state.toCoord = r.to_coord;
        } catch (e) { day = { date: d, itineraries: [], error: e.message }; }
        if (token !== state.searchSeq) return;
        Object.assign(state.days.find(x => x.date === d), day, { loading: false });
        renderResults();
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (token !== state.searchSeq) return;
    $('#btn-search').disabled = false;
    // sélection automatique du premier trajet pour que la carte montre tout de suite quelque chose
    const first = visibleTrips()[0];
    if (first && !state.selKey) select(first.key, false);
    else if (!first && state.toCoord) fitTo([[state.toCoord.lat, state.toCoord.lon]]);
  }

  function tripSort(a, b) {
    const A = a.it, B = b.it;
    if (state.sort === 'dur') return (A.duration_min ?? 1e9) - (B.duration_min ?? 1e9) || toMin(A.departure) - toMin(B.departure);
    if (state.sort === 'price') return A.cost_eur - B.cost_eur || (A.duration_min ?? 1e9) - (B.duration_min ?? 1e9);
    return toMin(A.departure) - toMin(B.departure) || A.cost_eur - B.cost_eur;
  }
  function dayTrips(d) {
    let list = (d.itineraries || []).map((it, i) => ({ it, key: `${d.date}#${i}`, date: d.date }));
    if (state.freeOnly) list = list.filter(x => !x.it.paid);
    return list.sort(tripSort);
  }
  const visibleTrips = () => state.days.flatMap(d => (d.loading ? [] : dayTrips(d)));
  const findTrip = key => {
    const [date, i] = key.split('#');
    const d = state.days.find(x => x.date === date);
    return d?.itineraries?.[Number(i)] || null;
  };

  function renderResults() {
    const box = $('#results');
    if (!state.days.length) { box.innerHTML = emptyHTML(); return; }
    const loaded = state.days.filter(d => !d.loading).length, total = state.days.length;
    const all = state.days.flatMap(d => d.itineraries || []);
    const freeN = all.filter(t => !t.paid).length;
    const paid = all.filter(t => t.paid).map(t => t.cost_eur);
    const cheapest = paid.length ? Math.min(...paid) : null;
    const { from, to } = state.lastParams || {};
    let html = `<div class="res-head" id="res-head">
      <div class="res-sum">${loaded < total ? `Recherche… ${loaded}/${total} jours · ` : ''}<b>${plural(all.length, 'trajet', 'trajets')}</b>`
      + (all.length ? ` · <b>${freeN}</b> 100 % gratuit${freeN > 1 ? 's' : ''}${cheapest != null ? ` · avec TER dès ${nf.format(cheapest)} €` : ''}` : '')
      + `<small>${esc(nameOf($('#s-from')) || from || '')} → ${esc(nameOf($('#s-to')) || to || '')}</small></div>
      <div class="res-tools">
        <div class="seg sm" id="sort" role="group" aria-label="Trier par">${[['dep', 'Départ'], ['dur', 'Durée'], ['price', 'Prix']]
          .map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${state.sort === v}">${l}</button>`).join('')}</div>
        <button class="btn ghost sm" type="button" id="btn-share">${ICON.share}<span>Partager</span></button>
      </div>
      <label class="switch sm"><input type="checkbox" id="free-only"${state.freeOnly ? ' checked' : ''}><span class="track"></span><span>100 % gratuits seulement</span></label>
      ${loaded < total ? `<div class="progress"><i style="width:${Math.round(loaded / total * 100)}%"></i></div>` : ''}
    </div>`;

    for (const d of state.days) {
      const list = d.loading ? [] : dayTrips(d);
      html += `<h3 class="day"><span>${fmtDay(d.date)}</span><small>${d.loading ? 'recherche…' : plural(list.length, 'trajet', 'trajets')}</small></h3>`;
      if (d.loading) { html += skeleton(2); continue; }
      if (d.error) { html += `<p class="notice err">${esc(d.error)}</p>`; continue; }
      if (d.notice) html += `<p class="notice">${esc(d.notice)}</p>`;
      if (list.length) html += `<ul class="trips">${list.map(x => tripRow(x.it, x.key)).join('')}</ul>`;
      else if (!d.notice) html += `<p class="none">${state.freeOnly && (d.itineraries || []).length ? 'Pas de trajet 100 % gratuit ce jour-là.' : 'Aucun trajet ce jour-là.'}</p>`;
      if (d.hidden_night) html += `<p class="none">+ ${plural(d.hidden_night, 'trajet de nuit masqué', 'trajets de nuit masqués')} (option « Trajets de nuit »).</p>`;
    }
    if (loaded === total && !all.length) {
      html += `<div class="empty"><h2>Pas de TGV Max sur cette période</h2><p>Essaie d'autres dates, d'autoriser une correspondance de plus, d'activer le complément TER ou les trajets de nuit (dans Options).</p></div>`;
    }
    box.innerHTML = html;
    box.style.setProperty('--rh', `${$('#res-head').offsetHeight}px`);
  }

  const nameOf = input => input.value.trim();

  function skeleton(n) {
    return Array.from({ length: n }, () => '<div class="skel" aria-hidden="true"><div><i></i><i></i></div><div><i></i><i></i></div><div><i></i></div></div>').join('');
  }

  function tripRow(it, key) {
    const sel = key === state.selKey;
    const first = it.legs[0], last = it.legs[it.legs.length - 1];
    const via = it.legs.slice(0, -1).map(l => l.to_name);
    const nconn = it.legs.length - 1;
    const meta = [fmtDur(it.duration_min), nconn ? plural(nconn, 'correspondance', 'correspondances') : 'direct'];
    if (via.length) meta.push(`via ${via.join(', ')}`);
    const badges = (it.paid ? '<em class="b ter">+ TER</em>' : '') + (it.nocturnal ? `<em class="b night">${ICON.moon}Nuit</em>` : '');
    return `<li class="trip${sel ? ' is-sel' : ''}" data-key="${key}">
      <button class="trip-hit" type="button" aria-expanded="${sel}">
        <span class="t-times"><b>${esc(it.departure)}</b><span>${esc(it.arrival)}${it.arrival_day ? `<sup>+${it.arrival_day}</sup>` : ''}</span></span>
        <span class="t-main">
          <span class="t-route">${esc(first.from_name)} <i>→</i> ${esc(last.to_name)}</span>
          <span class="t-meta">${esc(meta.join(' · '))}</span>
          <span class="t-badges">${badges}</span>
        </span>
        <span class="price ${it.paid ? 'paid' : 'free'}">${fmtPrice(it.cost_eur)}</span>
      </button>
      ${sel ? detailHTML(it) : ''}
    </li>`;
  }

  const absMin = (hm, day) => toMin(hm) + (day || 0) * 1440;

  function detailHTML(it) {
    let h = '<div class="detail"><ol class="line">';
    it.legs.forEach((l, i) => {
      let sub = '';
      if (i > 0) {
        const prev = it.legs[i - 1];
        const wait = absMin(l.dep, l.dep_day) - absMin(prev.arr, prev.arr_day);
        sub = `<small>arrivée ${esc(prev.arr)} · correspondance ${fmtDur(Math.max(0, wait))}</small>`;
      }
      h += `<li class="stop${i === 0 ? ' first' : ''}"><span class="s-time">${esc(l.dep)}${l.dep_day ? `<sup>+${l.dep_day}</sup>` : ''}</span><span class="s-node"></span><span class="s-name">${esc(l.from_name)}${sub}</span></li>`;
      const dur = l.duration_min ?? (absMin(l.arr, l.arr_day) - absMin(l.dep, l.dep_day));
      let body;
      if (l.free) {
        body = `<div class="s-title"><b>TGV Max ${esc(l.train)}</b><em class="b free">0 €</em></div>
          <div class="s-sub">${fmtDur(dur)} · 1 réservation Max</div>`;
      } else {
        const p = l.price || {};
        const steps = (l.steps || []).length > 1
          ? `<ul class="s-steps">${l.steps.map(s => `<li><b>${esc(s.dep)}</b> ${esc(s.from)} → ${esc(s.to)} <span>(${esc(s.mode)})</span></li>`).join('')}</ul>` : '';
        body = `<div class="s-title"><b>${esc(l.mode)}</b><em class="b paid">${fmtPrice(p.price)}</em></div>
          <div class="s-sub">${fmtDur(dur)}${l.transfers ? ` · ${plural(l.transfers, 'correspondance', 'correspondances')}` : ''}</div>
          ${steps}
          <div class="s-note">Estimation : ${esc(p.label || '')}${p.distance_km ? ` · ${p.distance_km} km` : ''}</div>`;
      }
      h += `<li class="leg${l.free ? '' : ' paid'}"><span class="s-time"></span><span class="s-node"></span><div class="s-body">${body}
        <a class="link" href="${esc(l.book_url)}" target="_blank" rel="noopener">Réserver sur SNCF Connect ${ICON.ext}</a></div></li>`;
    });
    const last = it.legs[it.legs.length - 1];
    h += `<li class="stop last"><span class="s-time">${esc(last.arr)}${last.arr_day ? `<sup>+${last.arr_day}</sup>` : ''}</span><span class="s-node"></span><span class="s-name">${esc(last.to_name)}<small>arrivée</small></span></li>`;
    return h + '</ol></div>';
  }

  function select(key, scroll = true) {
    state.selKey = state.selKey === key ? null : key;
    state.current = state.selKey ? findTrip(state.selKey) : null;
    renderResults();
    if (state.current) {
      drawItinerary(state.current);
      if (scroll) $(`.trip[data-key="${CSS.escape(key)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else clearMap();
  }

  const EXAMPLES = [['Paris', 'paris', 'Lyon', 'lyon'], ['Paris', 'paris', 'Bordeaux', 'bordeaux'], ['Lille', 'lille', 'Marseille', 'marseille'], ['Paris', 'paris', 'Annecy', 'annecy']];
  function emptyHTML() {
    return `<div class="empty">
      <h2>Où aller à 0 € ?</h2>
      <p>Choisis un départ, une arrivée et des dates : on cherche les TGV Max gratuits, même avec correspondances, et on complète en TER quand la gare n'a pas de TGV Max.</p>
      <div class="examples"><span class="lbl-sm">Essayer pour demain</span>
        ${EXAMPLES.map(([f, fl, t, tl], i) => `<button class="example" type="button" data-ex="${i}">${esc(f)} → ${esc(t)} <span>voir les trajets</span></button>`).join('')}
      </div></div>`;
  }

  /* ================================================================== explorer */
  async function runExplore() {
    const input = $('#e-from');
    const from = stationValue(input), date = $('#e-date').value;
    if (!from) { toast('Indique une gare de départ.'); input.focus(); return; }
    const box = $('#explore-results');
    box.innerHTML = skeleton(4);
    $('#btn-explore').disabled = true;
    if (isMobile()) { document.activeElement?.blur(); setSheet('half'); }
    try {
      state.explore = await api('/api/explore', { from, date, maxconn: segVal('e_maxconn'), ...profileParams() });
      state.exFilter = '';
      renderExplore();
      drawExplore(state.explore);
      if (isMobile()) $('#scroll').scrollTo({ top: $('#explore-results').offsetTop, behavior: 'smooth' });
    } catch (e) { box.innerHTML = `<p class="notice err">${esc(e.message)}</p>`; }
    $('#btn-explore').disabled = false;
  }

  function renderExplore() {
    const data = state.explore, box = $('#explore-results');
    const direct = data.destinations.filter(d => !d.nconn).length;
    box.innerHTML = `<div class="res-head">
        <div class="res-sum"><b>${plural(direct, 'gare', 'gares')} en direct</b> · ${plural(data.destinations.length - direct, 'avec correspondance', 'avec correspondance')}
          <small>Depuis ${esc(data.origin.name)}, ${fmtDay(data.date)} · touche une gare pour voir les trajets</small></div>
        <input class="input sm ex-filter" id="ex-filter" type="search" placeholder="Filtrer les gares…" aria-label="Filtrer les gares">
      </div>
      ${data.notice ? `<p class="notice">${esc(data.notice)}</p>` : ''}
      <ul class="trips" id="ex-list"></ul>`;
    renderExploreList();
  }

  function renderExploreList() {
    const data = state.explore, f = state.exFilter.toLowerCase();
    const list = data.destinations.filter(d => !f || d.name.toLowerCase().includes(f));
    $('#ex-list').innerHTML = list.length ? list.map(d => `<li class="trip dest"><button class="trip-hit" type="button" data-dest="${esc(d.label)}">
        <span class="t-times"><b>${esc(d.dep)}</b><span>${esc(d.arr)}${d.arr_day ? `<sup>+${d.arr_day}</sup>` : ''}</span></span>
        <span class="t-main"><span class="t-route">${esc(d.name)}</span>${d.nconn ? `<span class="t-meta">via ${esc(d.via.join(', '))}</span>` : ''}</span>
        <em class="b ${d.nconn ? 'via' : 'free'}">${d.nconn ? plural(d.nconn, 'corresp.', 'corresp.') : 'Direct'}</em>
      </button></li>`).join('') : '<li class="none">Aucune gare ne correspond.</li>';
  }

  function exploreToItinerary(d) {
    const o = state.explore.origin;
    setStation($('#s-from'), o.name, o.label);
    setStation($('#s-to'), d.name, d.label);
    setDates(state.explore.date, state.explore.date);   // même jour que l'exploration
    $('#s-start').value = ''; $('#s-end').value = '';
    showTab('search');
    runSearch();
  }

  /* ================================================================== favoris */
  const favKey = (f, t) => `${(f.label || f.name).toLowerCase()}|${(t.label || t.name).toLowerCase()}`;
  const currentOD = () => ({
    from: { name: $('#s-from').value.trim(), label: $('#s-from').dataset.label || '' },
    to: { name: $('#s-to').value.trim(), label: $('#s-to').dataset.label || '' },
  });
  function syncFav() {
    const od = currentOD();
    const on = !!(od.from.name && od.to.name) && favs.some(x => favKey(x.from, x.to) === favKey(od.from, od.to));
    const b = $('#btn-fav');
    b.setAttribute('aria-pressed', String(on));
    b.setAttribute('aria-label', on ? 'Retirer ce trajet des favoris' : 'Enregistrer ce trajet dans les favoris');
    $('#fav-count').textContent = favs.length || '';
  }
  function toggleFav() {
    const od = currentOD();
    if (!od.from.name || !od.to.name) { toast("Choisis d'abord un départ et une arrivée."); return; }
    const k = favKey(od.from, od.to), i = favs.findIndex(x => favKey(x.from, x.to) === k);
    if (i >= 0) { favs.splice(i, 1); toast('Retiré des favoris.'); }
    else { favs.unshift(od); toast(`${od.from.name} → ${od.to.name} ajouté aux favoris.`); }
    store.set('favs', favs);
    syncFav(); renderFavs();
  }
  function renderFavs() {
    const box = $('#favs');
    if (!favs.length) {
      box.innerHTML = `<div class="empty"><h2>Pas encore de favoris</h2><p>Dans l'onglet Itinéraire, remplis un départ et une arrivée puis touche l'étoile : tu pourras relancer la recherche en un geste.</p></div>`;
      return;
    }
    box.innerHTML = favs.map((f, i) => `<div class="fav">
        <div><b>${esc(f.from.name)} → ${esc(f.to.name)}</b><small>Relance avec les dates choisies dans Itinéraire</small></div>
        <button class="btn primary sm" type="button" data-fav-go="${i}">${ICON.search}<span>Chercher</span></button>
        <button class="btn ghost sm" type="button" data-fav-del="${i}" aria-label="Supprimer ce favori">${ICON.trash}</button>
      </div>`).join('');
  }

  /* ================================================================== profil */
  const DISCOUNTS = [0, 25, 30, 40, 50, 60, 75, 100];
  function renderProfileChip() {
    const b = $('#btn-profile');
    b.innerHTML = `${ICON.user}<span>${profile.sub === 'senior' ? 'Max Senior' : 'Max Jeune'}</span>`;
  }
  function openProfile(first = false) {
    const regions = (state.meta?.regions || []).filter(r => r.code !== '11');
    $('#region-list').innerHTML = regions.map(r => {
      const v = profile.ter[r.code] || 0;
      return `<div class="region-row${v ? ' on' : ''}"><label for="rg-${r.code}"><b>${esc(r.name)}</b><small>${esc(r.network)}</small></label>
        <select id="rg-${r.code}" data-code="${r.code}">${DISCOUNTS.map(p => `<option value="${p}"${p === v ? ' selected' : ''}>${p === 0 ? 'Aucune' : p === 100 ? '100 % (abonnement)' : `−${p} %`}</option>`).join('')}</select></div>`;
    }).join('');
    $$('#form-profile input[name="sub"]').forEach(r => { r.checked = r.value === profile.sub; });
    $('#dlg-title').textContent = first ? 'Bienvenue à bord' : 'Mon profil';
    $('#dlg-intro').textContent = first
      ? "Deux questions pour que les résultats te correspondent : ton abonnement, et tes éventuelles réductions TER. Tout reste sur ton appareil."
      : 'Sert à savoir quels trains sont gratuits pour toi et à estimer le prix des TER. Enregistré sur cet appareil uniquement.';
    $('#dlg-profile').showModal();
  }
  function saveProfile() {
    const sub = $('#form-profile input[name="sub"]:checked')?.value || 'jeune';
    const ter = {};
    $$('#region-list select').forEach(s => { const v = Number(s.value); if (v) ter[s.dataset.code] = v; });
    profile = { sub, ter };
    store.set('profile', profile);
    store.set('profileSet', true);
    renderProfileChip();
    toast('Profil enregistré.');
    if (state.tab === 'search' && state.days.length) runSearch();
    else if (state.tab === 'explore' && state.explore) runExplore();
  }

  /* ================================================================== onglets + panneau mobile */
  function showTab(t) {
    state.tab = t;
    $$('.tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === t)));
    for (const v of ['search', 'explore', 'favs']) $('#view-' + v).hidden = v !== t;
    $('#scroll').scrollTop = 0;
    if (t === 'search') { if (state.current) drawItinerary(state.current); else clearMap(); }
    else if (t === 'explore') { if (state.explore) drawExplore(state.explore); else clearMap(); }
    else clearMap();
  }

  function setSheet(s) {
    const p = $('#panel');
    const changed = p.dataset.sheet !== s;
    p.dataset.sheet = s;
    p.style.removeProperty('--sheet-h');
    // la hauteur du panneau change la zone visible de la carte : on recadre après l'animation
    if (changed && isMobile() && MAP.lastFit && MAP.route?.getLayers().length) setTimeout(() => fitTo(...MAP.lastFit), 320);
  }
  function initSheet() {
    const panel = $('#panel'), handle = $('#sheet-handle');
    let startY = 0, startH = 0, moved = false, dragging = false;
    handle.addEventListener('pointerdown', e => {
      if (!isMobile()) return;
      dragging = true; moved = false; startY = e.clientY; startH = panel.getBoundingClientRect().height;
      panel.classList.add('dragging');
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', e => {
      if (!dragging) return;
      const dy = startY - e.clientY;
      if (Math.abs(dy) > 6) moved = true;
      panel.style.setProperty('--sheet-h', `${Math.max(120, Math.min(innerHeight - 40, startH + dy))}px`);
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      panel.classList.remove('dragging');
      if (!moved) return;
      const h = panel.getBoundingClientRect().height;
      const snaps = { peek: 196, half: innerHeight * 0.58, full: innerHeight - 48 };
      const best = Object.entries(snaps).sort((a, b) => Math.abs(a[1] - h) - Math.abs(b[1] - h))[0][0];
      setSheet(best);
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('click', () => {
      if (moved) { moved = false; return; }
      setSheet({ peek: 'half', half: 'full', full: 'peek' }[panel.dataset.sheet] || 'half');
    });
  }

  /* ================================================================== événements */
  function bindUI() {
    $('#btn-swap').innerHTML = ICON.swap;
    $('#btn-search').innerHTML = `${ICON.search}<span>Rechercher</span>`;
    $('#btn-fav').innerHTML = ICON.star;
    $$('[data-locate]').forEach(b => { b.innerHTML = ICON.locate; b.addEventListener('click', () => locate($('#' + b.dataset.locate))); });

    attachAC($('#s-from'), 'origin');
    attachAC($('#s-to'), 'dest');
    attachAC($('#e-from'), 'origin');

    $$('.tab').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
    $('.tabs').addEventListener('keydown', e => {
      if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
      const tabs = $$('.tab'), i = tabs.findIndex(t => t.getAttribute('aria-selected') === 'true');
      const n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      n.focus(); showTab(n.dataset.tab);
    });

    $$('.seg[data-name]').forEach(seg => seg.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      setSeg(seg.dataset.name, b.dataset.v);
      updateOptsSummary();
    }));
    $('#s-ter').addEventListener('change', updateOptsSummary);
    $('#s-nights').addEventListener('change', updateOptsSummary);

    $('#btn-swap').addEventListener('click', () => {
      const a = $('#s-from'), b = $('#s-to');
      const [av, al] = [a.value, a.dataset.label];
      setStation(a, b.value, b.dataset.label);
      setStation(b, av, al);
      const s = $('#btn-swap');
      s.classList.toggle('spin');
      syncFav();
      if (stationValue(a) && stationValue(b)) runSearch();   // relance directement dans l'autre sens
    });
    $$('.chip[data-quick]').forEach(c => c.addEventListener('click', () => setDates(...quickRange(c.dataset.quick))));
    $('#s-fd').addEventListener('change', () => {
      if (!$('#s-td').value || $('#s-td').value < $('#s-fd').value) $('#s-td').value = $('#s-fd').value;
      markQuick();
    });
    $('#s-td').addEventListener('change', markQuick);

    $('#form-search').addEventListener('submit', e => { e.preventDefault(); runSearch(); });
    $('#form-explore').addEventListener('submit', e => { e.preventDefault(); runExplore(); });
    $('#btn-fav').addEventListener('click', toggleFav);

    // délégation : résultats
    $('#results').addEventListener('click', async e => {
      const hit = e.target.closest('.trip-hit');
      if (hit) { select(hit.closest('.trip').dataset.key); return; }
      const sortB = e.target.closest('#sort button');
      if (sortB) { state.sort = sortB.dataset.v; store.set('sort', state.sort); renderResults(); return; }
      const ex = e.target.closest('[data-ex]');
      if (ex) {
        const [f, fl, t, tl] = EXAMPLES[Number(ex.dataset.ex)];
        setStation($('#s-from'), f, fl); setStation($('#s-to'), t, tl);
        setDates(...quickRange('tomorrow'));
        runSearch();
        return;
      }
      if (e.target.closest('#btn-share')) {
        const url = shareURL();
        try {
          if (navigator.share && isMobile()) await navigator.share({ title: 'TGV Max Planner', text: 'Regarde ces trajets TGV Max', url });
          else { await navigator.clipboard.writeText(url); toast('Lien copié : envoie-le à qui tu veux.'); }
        } catch { toast(url); }
      }
    });
    $('#results').addEventListener('change', e => {
      if (e.target.id === 'free-only') { state.freeOnly = e.target.checked; store.set('freeOnly', state.freeOnly); renderResults(); }
    });
    $('#explore-results').addEventListener('input', e => {
      if (e.target.id === 'ex-filter') { state.exFilter = e.target.value; renderExploreList(); }
    });
    $('#explore-results').addEventListener('click', e => {
      const b = e.target.closest('[data-dest]');
      if (b) exploreToItinerary(state.explore.destinations.find(d => d.label === b.dataset.dest));
    });
    $('#favs').addEventListener('click', e => {
      const go = e.target.closest('[data-fav-go]'), del = e.target.closest('[data-fav-del]');
      if (go) {
        const f = favs[Number(go.dataset.favGo)];
        setStation($('#s-from'), f.from.name, f.from.label); setStation($('#s-to'), f.to.name, f.to.label);
        showTab('search'); runSearch();
      } else if (del) {
        favs.splice(Number(del.dataset.favDel), 1); store.set('favs', favs); renderFavs(); syncFav();
      }
    });

    $('#btn-profile').addEventListener('click', () => openProfile(false));
    $('#dlg-profile').addEventListener('close', () => {
      if ($('#dlg-profile').returnValue === 'save') saveProfile();
      else store.set('profileSet', true);
    });
    $('#region-list').addEventListener('change', e => {
      if (e.target.matches('select')) e.target.closest('.region-row').classList.toggle('on', Number(e.target.value) > 0);
    });
    $('#btn-theme').addEventListener('click', () => {
      theme = { auto: 'light', light: 'dark', dark: 'auto' }[theme];
      store.set('theme', theme);
      applyTheme();
      toast(`Thème ${{ auto: 'automatique (comme ton appareil)', light: 'clair', dark: 'sombre' }[theme]}.`);
    });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (theme === 'auto') mapTheme(); });
  }

  /* ================================================================== démarrage */
  async function init() {
    initMap();
    applyTheme();
    bindUI();
    initSheet();
    renderProfileChip();
    updateOptsSummary();
    syncFav();
    renderFavs();
    renderResults();

    try { state.meta = await api('/api/meta'); }
    catch { $('#data-status').textContent = 'Données SNCF indisponibles pour le moment.'; return; }
    const { start, end } = state.meta.dates;
    if (start) {
      $('#data-status').textContent = `Places TGV Max du ${fmtShort(start)} au ${fmtShort(end)}`;
      for (const s of ['#s-fd', '#s-td', '#e-date']) { $(s).min = start; $(s).max = end; }
    }
    setDates(...quickRange('tomorrow'));
    $('#e-date').value = clampDate(todayISO());

    const q = new URLSearchParams(location.search);
    if (q.get('f') && q.get('t')) {
      applyState(Object.fromEntries(q));
      runSearch();
    } else {
      const last = store.get('last', null);
      if (last) applyState({ ...last, du: null, au: null, h1: '', h2: '' });
      else { setStation($('#s-from'), 'Paris', 'paris'); }
      setStation($('#e-from'), $('#s-from').value || 'Paris', $('#s-from').dataset.label || 'paris');
    }
    if (!store.get('profileSet', false)) openProfile(true);

    if ('serviceWorker' in navigator && !/^(localhost|127\.|\[::1\])/.test(location.hostname)) {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
  }

  init();
})();
