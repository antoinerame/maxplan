/* MaxPlan — interface */
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
  const DAYS_S = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'];
  const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const noon = iso => new Date(iso + 'T12:00:00');
  const isoOf = d => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
  const todayISO = () => isoOf(new Date());
  const addDays = (iso, n) => { const d = noon(iso); d.setDate(d.getDate() + n); return isoOf(d); };
  const fmtDay = iso => { const d = noon(iso); return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  const fmtShort = iso => { const d = noon(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  const fmtDayS = iso => { const d = noon(iso); return `${DAYS_S[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
  const isMobile = () => matchMedia('(max-width: 899px)').matches;
  const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  const svg = p => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
  const ICON = {
    swap: svg('<path d="M7 20V4M3.5 7.5 7 4l3.5 3.5M17 4v16M13.5 16.5 17 20l3.5-3.5"/>'),
    swapH: svg('<path d="M4 7h16M16.5 3.5 20 7l-3.5 3.5M20 17H4M7.5 13.5 4 17l3.5 3.5"/>'),
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
    map: svg('<path d="m9 4-6 2.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>'),
    board: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M8 4v16"/>'),
    edit: svg('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>'),
    cal: svg('<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
    msg: svg('<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>'),
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
    days: [], rt: false, dir: 'out', sel: { out: null, ret: null }, current: null,
    toCoord: null, searchSeq: 0, lastQuery: null, editing: false, showMore: false, cal: null,
    sort: store.get('sort', 'dep'), freeOnly: store.get('freeOnly', false),
    explore: null, exFilter: '',
  };
  const opts = Object.assign({ ter: true, nights: false, e_maxconn: '1' }, store.get('opts', {}));
  let mapOn = store.get('mapOn', false);
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
    const pad = isMobile() ? [28, 28] : [56, 56];
    map.fitBounds(L.latLngBounds(pts), { padding: pad, maxZoom });
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

  /* ================================================================== vues : accueil / résultats, carte affichée ou non */
  function hasResults() {
    return (state.tab === 'search' && state.days.length > 0) || (state.tab === 'explore' && !!state.explore);
  }
  function refreshView(fit = true) {
    const app = $('#app');
    const results = hasResults();
    app.dataset.view = results ? 'results' : 'home';
    app.dataset.map = mapOn ? 'on' : 'off';
    const editing = state.tab === 'search' && (!results || state.editing);
    $('#form-search').hidden = !editing;
    $('#search-sum').hidden = editing || state.tab !== 'search';
    if (!editing) renderSummary();
    if (results && mapOn) {
      ensureMap();
      requestAnimationFrame(() => { MAP.map.invalidateSize(); drawCurrent(fit); });
    }
  }
  function drawCurrent(fit = true) {
    if (!MAP.map) return;
    if (state.tab === 'search' && state.current) drawItinerary(state.current, fit);
    else if (state.tab === 'explore' && state.explore) drawExplore(state.explore, fit);
    else clearMap();
  }
  function ensureMap() { if (!MAP.map) initMap(); }
  function setMapOn(on) {
    mapOn = on;
    store.set('mapOn', on);
    refreshView();
    renderResultsHeadOnly();
  }
  const mapBtn = () => `<button class="btn ghost sm" type="button" data-map-toggle>${mapOn ? ICON.board : ICON.map}<span>${mapOn ? 'Masquer la carte' : 'Voir la carte'}</span></button>`;
  function renderResultsHeadOnly() { $$('[data-map-toggle]').forEach(b => { b.outerHTML = mapBtn(); }); }

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
        `<em class="tag ${it.max ? 'max' : 'ter'}">${it.max ? 'Max' : 'TER'}</em></li>`).join('');
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
        toast(`Gare Max la plus proche : ${r[0].name} (${r[0].km} km)`);
      } catch (e) { toast(e.message); }
    }, () => toast("Position refusée ou indisponible. Tape le nom de ta gare."), { timeout: 10000, maximumAge: 600000 });
  }

  /* ================================================================== options en pilules */
  const PILLS = {
    ter: { toggle: true, label: () => 'Compléter en TER' },
    nights: { toggle: true, label: () => 'Trajets de nuit' },
    e_maxconn: { cycle: ['0', '1', '2'], label: v => (v === '0' ? 'Trains directs' : plural(Number(v), 'correspondance', 'correspondances')) },
  };
  function renderPills() {
    for (const [name, p] of Object.entries(PILLS)) {
      const b = $(`.pill[data-pill="${name}"]`);
      if (!b) continue;
      const v = opts[name];
      if (p.toggle) {
        b.setAttribute('aria-pressed', String(!!v));
        b.innerHTML = `${esc(p.label(v))}<i>${v ? '✓' : '+'}</i>`;
        b.title = v ? 'Activé — toucher pour désactiver' : 'Désactivé — toucher pour activer';
      } else {
        b.setAttribute('aria-pressed', 'false');
        b.innerHTML = `${esc(p.label(v))}<i>↻</i>`;
        b.title = 'Toucher pour changer';
      }
    }
  }
  function clickPill(name) {
    const p = PILLS[name];
    if (p.toggle) opts[name] = !opts[name];
    else opts[name] = p.cycle[(p.cycle.indexOf(opts[name]) + 1) % p.cycle.length];
    store.set('opts', opts);
    renderPills();
  }

  /* ================================================================== dates, aller-retour */
  const meta = () => state.meta?.dates || {};
  function clampDate(iso) {
    const { start, end } = meta();
    if (!start) return iso;
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
  function setRT(on, fd, td) {
    state.rt = on;
    $('#when-ret').hidden = !on;
    $('#btn-add-ret').hidden = on;
    if (on) {
      const base = $('#s-td').value || $('#s-fd').value || todayISO();
      const a = clampDate(fd || $('#r-fd').value || addDays(base, 2));
      $('#r-fd').value = a < base ? clampDate(addDays(base, 1)) : a;
      $('#r-td').value = clampDate(td || ($('#r-td').value >= $('#r-fd').value ? $('#r-td').value : $('#r-fd').value));
    }
  }

  function formState() {
    const s = {
      f: $('#s-from').value.trim(), fl: $('#s-from').dataset.label || '',
      t: $('#s-to').value.trim(), tl: $('#s-to').dataset.label || '',
      du: $('#s-fd').value, au: $('#s-td').value, h1: $('#s-start').value, h2: $('#s-end').value,
      ter: opts.ter ? '1' : '0', n: opts.nights ? '1' : '0',
    };
    if (state.rt) Object.assign(s, { r: '1', rdu: $('#r-fd').value, rau: $('#r-td').value, rh1: $('#r-start').value, rh2: $('#r-end').value });
    return s;
  }
  function applyState(s) {
    if (s.f != null) setStation($('#s-from'), s.f, s.fl);
    if (s.t != null) setStation($('#s-to'), s.t, s.tl);
    if (s.du) setDates(s.du, s.au || s.du);
    $('#s-start').value = s.h1 || '';
    $('#s-end').value = s.h2 || '';
    if (s.ter != null) opts.ter = s.ter !== '0';
    if (s.n != null) opts.nights = s.n === '1';
    if (s.r === '1' && s.rdu) {
      setRT(true, s.rdu, s.rau || s.rdu);
      $('#r-start').value = s.rh1 || ''; $('#r-end').value = s.rh2 || '';
    } else setRT(false);
    renderPills();
    syncFav();
  }
  function shareURL() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(formState())) if (v !== '' && v != null) p.set(k, v);
    return `${location.origin}/?${p}`;
  }

  /* ================================================================== recherche */
  function daysBetween(fd, td) {
    if (td < fd) [fd, td] = [td, fd];
    const out = [];
    for (let d = fd; d <= td && out.length < 31; d = addDays(d, 1)) out.push(d);
    return out;
  }

  async function runSearch() {
    const fromIn = $('#s-from'), toIn = $('#s-to');
    const from = stationValue(fromIn), to = stationValue(toIn);
    if (!from || !to) { state.editing = true; refreshView(); toast("Indique une gare de départ et une gare d'arrivée."); (from ? toIn : fromIn).focus(); return; }
    const fd = $('#s-fd').value, td = $('#s-td').value || fd;
    if (!fd) { toast('Choisis une date de départ.'); return; }
    const legs = [{ dir: 'out', from, to, fromName: fromIn.value.trim(), toName: toIn.value.trim(), fd, td, start: $('#s-start').value, end: $('#s-end').value }];
    if (state.rt) {
      const rfd = $('#r-fd').value, rtd = $('#r-td').value || rfd;
      if (!rfd) { toast('Choisis une date de retour.'); return; }
      legs.push({ dir: 'ret', from: to, to: from, fromName: toIn.value.trim(), toName: fromIn.value.trim(), fd: rfd, td: rtd, start: $('#r-start').value, end: $('#r-end').value });
    }
    const common = {
      maxconn: 3, ter: opts.ter ? 1 : 0, ter_transfers: 3,
      nights: opts.nights ? 1 : 0, ...profileParams(),
    };
    const token = ++state.searchSeq;
    const queue = [];
    state.days = [];
    for (const leg of legs) {
      const days = daysBetween(leg.fd, leg.td);
      const first = days[0], last = days[days.length - 1];
      for (const d of days) {
        state.days.push({ dir: leg.dir, date: d, loading: true });
        const params = { ...common, from: leg.from, to: leg.to, from_date: d, to_date: d };
        if (d === first && leg.start) params.start = leg.start;
        if (d === last && leg.end) params.end = leg.end;
        queue.push({ dir: leg.dir, date: d, params });
      }
    }
    state.lastQuery = { legs, rt: state.rt };
    state.dir = 'out'; state.sel = { out: null, ret: null }; state.current = null; state.editing = false; state.showMore = false; state.showNight = false;
    closeCal();
    clearMap();
    renderResults();
    refreshView();
    store.set('last', formState());
    history.replaceState(null, '', shareURL().replace(location.origin, ''));
    document.activeElement?.blur();
    if (isMobile()) scrollTo({ top: 0, behavior: 'smooth' });
    else $('#panel').scrollTo({ top: 0 });

    const worker = async () => {
      while (queue.length) {
        const job = queue.shift();
        let day;
        try {
          const r = await api('/api/search', job.params);
          day = r.days[0];
          if (r.to_coord && job.dir === 'out') state.toCoord = r.to_coord;
        } catch (e) { day = { date: job.date, itineraries: [], error: e.message }; }
        if (token !== state.searchSeq) return;
        // trajets de nuit renvoyés à part : gardés sous le coude, affichés sur demande
        day.itineraries = [...(day.itineraries || []), ...(day.night_itineraries || []).map(x => ({ ...x, _night: true }))];
        Object.assign(state.days.find(x => x.dir === job.dir && x.date === job.date), day, { loading: false });
        renderResults();
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (token !== state.searchSeq) return;
    // sélection automatique du premier trajet de chaque sens pour que la carte montre tout de suite quelque chose
    for (const dir of state.rt ? ['out', 'ret'] : ['out']) {
      const list = visibleTrips(dir).filter(x => !isExtra(x.it));
      const first = list.find(x => !x.it.paid) || list[0] || visibleTrips(dir)[0];
      if (first && !state.sel[dir]) state.sel[dir] = first.key;
    }
    state.current = state.sel[state.dir] ? findTrip(state.sel[state.dir]) : null;
    renderResults();
    if (state.current) drawCurrent();
    else if (state.toCoord && MAP.map) fitTo([[state.toCoord.lat, state.toCoord.lon]]);
  }

  function tripSort(a, b) {
    const A = a.it, B = b.it;
    if (state.sort === 'dur') return (A.duration_min ?? 1e9) - (B.duration_min ?? 1e9) || toMin(A.departure) - toMin(B.departure);
    if (state.sort === 'price') return A.cost_eur - B.cost_eur || (A.duration_min ?? 1e9) - (B.duration_min ?? 1e9);
    return toMin(A.departure) - toMin(B.departure) || A.cost_eur - B.cost_eur;
  }
  function dayTrips(d) {
    let list = (d.itineraries || []).map((it, i) => ({ it, key: `${d.dir}|${d.date}#${i}`, date: d.date }));
    if (state.freeOnly) list = list.filter(x => !x.it.paid);
    if (!state.showNight) list = list.filter(x => !x.it._night);
    return list.sort(tripSort);
  }
  // trajets « en plus » : 2 changements ou plus, montrés seulement sur demande (ou s'il n'y a rien d'autre)
  const isExtra = it => (it.changes ?? it.legs.length - 1) >= 2;
  const visibleTrips = dir => state.days.filter(d => d.dir === dir).flatMap(d => (d.loading ? [] : dayTrips(d)));
  const findTrip = key => {
    const [dir, rest] = key.split('|');
    const [date, i] = rest.split('#');
    const d = state.days.find(x => x.dir === dir && x.date === date);
    return d?.itineraries?.[Number(i)] || null;
  };

  function whenText(leg) {
    const from = fmtDayS(leg.fd) + (leg.start ? ` dès ${leg.start}` : '');
    if (leg.td === leg.fd) return from + (leg.end ? ` jusqu'à ${leg.end}` : '');
    return `du ${from} au ${fmtDayS(leg.td)}${leg.end ? ` ${leg.end}` : ''}`;
  }
  function renderSummary() {
    const q = state.lastQuery;
    const box = $('#search-sum');
    if (!q) { box.innerHTML = ''; return; }
    const [out, ret] = q.legs;
    box.innerHTML = `<div class="ss-main">
        <span class="ss-od">${esc(out.fromName || out.from)}<i>${ret ? '⇄' : '→'}</i>${esc(out.toName || out.to)}</span>
        <span class="ss-when">Aller : ${esc(whenText(out))}${ret ? ` · Retour : ${esc(whenText(ret))}` : ''}</span>
      </div>
      <button class="btn" type="button" id="btn-sum-cal" aria-label="Calendrier du mois">${ICON.cal}<span>Calendrier</span></button>
      <button class="btn" type="button" id="btn-edit">${ICON.edit}<span>Modifier</span></button>`;
  }

  function renderResults() {
    const box = $('#results');
    if (!state.days.length) { box.innerHTML = ''; return; }
    const dirs = state.rt ? ['out', 'ret'] : ['out'];
    const shown = state.days.filter(d => d.dir === state.dir);
    const loaded = state.days.filter(d => !d.loading).length, total = state.days.length;
    const pool = d => (d.itineraries || []).filter(t => state.showNight || !t._night);
    const all = shown.flatMap(pool);
    const freeN = all.filter(t => !t.paid).length;
    const paid = all.filter(t => t.paid).map(t => t.cost_eur);
    const cheapest = paid.length ? Math.min(...paid) : null;
    const q = state.lastQuery;
    const leg = q.legs.find(l => l.dir === state.dir) || q.legs[0];

    let html = `<div class="res-head" id="res-head">`;
    if (state.rt) {
      html += `<div class="dir-tabs" role="group" aria-label="Sens du trajet">${dirs.map(dir => {
        const l = q.legs.find(x => x.dir === dir);
        const n = state.days.filter(d => d.dir === dir).flatMap(pool).length;
        return `<button class="dir-tab" type="button" data-dir="${dir}" aria-pressed="${state.dir === dir}">
          <b>${dir === 'out' ? 'Aller' : 'Retour'} · ${plural(n, 'trajet', 'trajets')}</b><small>${esc(l.fromName)} → ${esc(l.toName)}</small></button>`;
      }).join('')}</div>`;
    }
    html += `<div class="res-sum">${loaded < total ? `Recherche… ${loaded}/${total} jours · ` : ''}<b>${plural(all.length, 'trajet', 'trajets')}</b>`
      + (all.length ? ` · ${freeN ? `<b>${freeN}</b> à 0 €` : 'aucun à 0 €'}${cheapest != null ? ` · avec TER dès ${nf.format(cheapest)} €` : ''}` : '')
      + `<small>${esc(leg.fromName)} → ${esc(leg.toName)}</small></div>
      <div class="res-tools">${mapBtn()}
        <button class="btn ghost sm" type="button" id="btn-share">${ICON.share}<span>Partager</span></button>
      </div>
      <div class="res-opts">
        <div class="seg" id="sort" role="group" aria-label="Trier par">${[['dep', 'Départ'], ['dur', 'Durée'], ['price', 'Prix']]
          .map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${state.sort === v}">${l}</button>`).join('')}</div>
        <label class="switch"><input type="checkbox" id="free-only"${state.freeOnly ? ' checked' : ''}><span class="track"></span><span>100 % gratuits</span></label>
      </div>`;
    if (state.rt && state.sel.out && state.sel.ret) {
      const a = findTrip(state.sel.out), r = findTrip(state.sel.ret);
      if (a && r) {
        const sum = a.cost_eur + r.cost_eur;
        html += `<div class="rt-total">Aller-retour sélectionné : aller ${esc(a.departure)} → ${esc(a.arrival)}, retour ${esc(r.departure)} → ${esc(r.arrival)} · <b>${sum === 0 ? 'gratuit' : `≈ ${nf.format(sum)} €`}</b></div>`;
      }
    }
    if (loaded < total) html += `<div class="progress"><i style="width:${Math.round(loaded / total * 100)}%"></i></div>`;
    html += '</div>';

    let hiddenExtra = 0, extraTotal = 0, nightTotal = 0;
    for (const d of shown) {
      const all = d.loading ? [] : dayTrips(d);
      const main = all.filter(x => !isExtra(x.it) || x.it._night);   // nuit demandée : montrée telle quelle
      const openAll = state.showMore || !main.length;      // rien de simple ce jour-là : on montre tout
      const list = openAll ? all : main;
      const nights = (d.itineraries || []).filter(t => t._night).length;
      nightTotal += nights;
      extraTotal += all.length - main.length;
      if (!openAll) hiddenExtra += all.length - main.length;
      html += `<section class="day-block"><h3 class="day"><span>${fmtDay(d.date)}</span><small>${d.loading ? 'recherche…' : plural(list.length, 'trajet', 'trajets')}</small></h3>`;
      if (d.loading) { html += skeleton(2) + '</section>'; continue; }
      if (d.error) { html += `<p class="notice err">${esc(d.error)}</p></section>`; continue; }
      if (d.notice) html += `<p class="notice">${esc(d.notice)}</p>`;
      if (d.ter_notice) html += `<p class="notice">${esc(d.ter_notice)}</p>`;
      if (list.length) html += `<ul class="trips">${list.map(x => tripRow(x.it, x.key)).join('')}</ul>`;
      else if (!d.notice) {
        const why = state.freeOnly && (d.itineraries || []).length ? 'Pas de trajet 100 % gratuit ce jour-là.'
          : nights && !state.showNight ? 'Rien en journée ce jour-là.' : 'Aucun trajet ce jour-là.';
        html += `<p class="none">${why}</p>`;
      }
      if (nights && !state.showNight) {
        html += `<button class="night-more" type="button" data-night>${ICON.moon}<span>Voir ${nights > 1 ? `les ${nights} trajets` : 'le trajet'} de nuit<small>train de nuit, ou nuit à attendre en gare</small></span></button>`;
      }
      html += '</section>';
    }
    if (state.showNight && nightTotal) {
      html += `<button class="more" type="button" data-night>Masquer les trajets de nuit</button>`;
    }
    if (hiddenExtra) {
      html += `<button class="more" type="button" id="btn-more">Afficher plus de résultats<small>${plural(hiddenExtra, 'trajet', 'trajets')} avec 2 changements ou plus</small></button>`;
    } else if (state.showMore && extraTotal) {
      html += `<button class="more" type="button" id="btn-more">Masquer les trajets à 2 changements ou plus</button>`;
    }
    if (shown.every(d => !d.loading) && !all.length && !nightTotal) {
      html += `<div class="empty"><h2>Pas de train Max sur cette période</h2><p>Essaie d'autres dates : le bouton « Calendrier » montre les jours où il y a des trains à 0 € sur ce trajet.</p></div>`;
    }
    box.innerHTML = html;
    box.style.setProperty('--rh', `${$('#res-head').offsetHeight}px`);
  }

  function skeleton(n) {
    return Array.from({ length: n }, () => '<div class="skel" aria-hidden="true"><div><i></i><i></i></div><div><i></i><i></i></div><div><i></i></div></div>').join('');
  }

  function tripRow(it, key) {
    const sel = key === state.sel[state.dir];
    const first = it.legs[0], last = it.legs[it.legs.length - 1];
    const via = it.legs.slice(0, -1).map(l => l.to_name);
    const nconn = it.legs.length - 1;
    const nch = it.changes ?? nconn;
    const meta = [fmtDur(it.duration_min), nch ? plural(nch, 'changement', 'changements') : 'direct'];
    if (via.length) meta.push(`via ${via.join(', ')}`);
    const ic = it.legs.some(l => l.free && l.mode === 'Intercités');
    const est = it.legs.some(l => l.estimated_schedule);
    const badges = (ic ? '<em class="b ic">Intercités</em>' : '') + (it.paid ? '<em class="b ter">+ TER</em>' : '')
      + (est ? '<em class="b est">Horaire TER estimé</em>' : '')
      + (it.nocturnal ? `<em class="b night">${ICON.moon}Nuit</em>` : '');
    return `<li class="trip${sel ? ' is-sel' : ''}" data-key="${esc(key)}">
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
        body = `<div class="s-title"><b>${esc(l.mode)} ${esc(l.train)}</b><em class="b free">Max · 0 €</em></div>
          <div class="s-sub">${fmtDur(dur)} · 1 réservation Max</div>`;
      } else {
        const p = l.price || {};
        const steps = (l.steps || []).length > 1
          ? `<ul class="s-steps">${l.steps.map(s => `<li><b>${esc(s.dep)}</b> ${esc(s.from)} → ${esc(s.to)} <span>(${esc(s.mode)})</span></li>`).join('')}</ul>` : '';
        body = `<div class="s-title"><b>${esc(l.mode)}</b><em class="b paid">${fmtPrice(p.price)}</em></div>
          <div class="s-sub">${fmtDur(dur)}${l.transfers ? ` · ${plural(l.transfers, 'correspondance', 'correspondances')}` : ''}</div>
          ${steps}
          ${l.estimated_schedule ? '<div class="s-note est">Horaire estimé d\'après la semaine précédente : la SNCF ne l\'a pas encore publié.</div>' : ''}
          <div class="s-note">Estimation : ${p.base ? `tarif normal ≈ ${nf.format(p.base)} € · ` : ''}${esc(p.label || '')}. Les promos affichées par SNCF ne se cumulent pas avec les cartes.</div>`;
      }
      h += `<li class="leg${l.free ? '' : ' paid'}"><span class="s-time"></span><span class="s-node"></span><div class="s-body">${body}
        <a class="book" href="${esc(l.book_url)}" target="_blank" rel="noopener">Voir ce train sur SNCF Connect ${ICON.ext}</a></div></li>`;
    });
    const last = it.legs[it.legs.length - 1];
    h += `<li class="stop last"><span class="s-time">${esc(last.arr)}${last.arr_day ? `<sup>+${last.arr_day}</sup>` : ''}</span><span class="s-node"></span><span class="s-name">${esc(last.to_name)}<small>arrivée</small></span></li>`;
    return h + '</ol></div>';
  }

  function select(key, scroll = true) {
    const dir = key.split('|')[0];
    state.sel[dir] = state.sel[dir] === key ? null : key;
    state.current = state.sel[state.dir] ? findTrip(state.sel[state.dir]) : null;
    renderResults();
    if (state.current) {
      drawCurrent();
      // le trajet ouvert remonte en haut (sous l'en-tête du jour) pour se lire sans faire défiler
      if (scroll) $(`.trip[data-key="${CSS.escape(key)}"]`)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    } else clearMap();
  }
  function setDir(dir) {
    state.dir = dir;
    state.current = state.sel[dir] ? findTrip(state.sel[dir]) : null;
    renderResults();
    drawCurrent();
  }

  /* ================================================================== calendrier du mois */
  const WD = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];
  function closeCal() { $('#cal').hidden = true; $('#btn-cal').setAttribute('aria-expanded', 'false'); }
  async function openCal() {
    const from = stationValue($('#s-from')), to = stationValue($('#s-to'));
    const box = $('#cal');
    box.hidden = false;
    $('#btn-cal').setAttribute('aria-expanded', 'true');
    if (!from || !to) { box.innerHTML = `<p class="cal-msg">Indique d'abord un départ et une arrivée : le calendrier montre les jours avec des trains à 0 €.</p>`; return; }
    const key = `${from}|${to}|${opts.nights}|${profile.sub}`;
    if (state.cal?.key !== key) {
      box.innerHTML = `<p class="cal-msg">Recherche des trains à 0 € sur les 30 prochains jours…</p>`;
      try {
        const r = await api('/api/calendar', { from, to, nights: opts.nights ? 1 : 0, ...profileParams() });
        state.cal = { key, r };
      } catch (e) { box.innerHTML = `<p class="cal-msg err">${esc(e.message)}</p>`; return; }
    }
    renderCal();
  }
  function renderCal() {
    const { r } = state.cal, box = $('#cal');
    const days = r.days.filter(d => d.date);
    if (!days.length) { box.innerHTML = '<p class="cal-msg">Données indisponibles.</p>'; return; }
    const sel = $('#s-fd').value;
    const ter = r.ter_coverage?.end ? `${r.ter_coverage.end.slice(0, 4)}-${r.ter_coverage.end.slice(4, 6)}-${r.ter_coverage.end.slice(6, 8)}` : null;
    const best = Math.max(...days.map(d => d.n || 0));
    // grille lundi → dimanche, en commençant au lundi de la première semaine
    const first = noon(days[0].date), lead = (first.getDay() + 6) % 7;
    let cells = Array.from({ length: lead }, () => '<span class="cal-pad"></span>');
    let month = -1;
    for (const d of days) {
      const dt = noon(d.date);
      const n = d.n || 0;
      const lvl = !n ? 0 : n >= best * 0.66 ? 3 : n >= best * 0.33 ? 2 : 1;
      const title = d.blocked ? 'Max Senior : pas de 0 € le week-end' : n ? `${plural(n, 'trajet', 'trajets')} à 0 €${d.first ? ` · premier départ ${d.first}` : ''}${d.best_min ? ` · le plus rapide ${fmtDur(d.best_min)}` : ''}` : 'Aucun trajet à 0 €';
      const mlabel = dt.getMonth() !== month ? `<em>${MONTHS[dt.getMonth()]}</em>` : '';
      month = dt.getMonth();
      cells.push(`<button type="button" class="cal-day l${lvl}${d.date === sel ? ' is-sel' : ''}${ter && d.date > ter ? ' no-ter' : ''}" data-day="${d.date}" title="${esc(title)}" aria-label="${esc(fmtDay(d.date))} : ${esc(title)}">
        ${mlabel}<b>${dt.getDate()}</b><span>${n ? n : '–'}</span></button>`);
    }
    box.innerHTML = `<div class="cal-head"><b>Trains à 0 € par jour</b><small>100 % Max, sans TER · touche un jour pour voir les trains</small></div>
      <div class="cal-grid">${WD.map(w => `<span class="cal-wd">${w}</span>`).join('')}${cells.join('')}</div>
      ${ter ? `<p class="cal-msg">Jours hachurés : horaires TER pas encore publiés (complément TER indisponible).</p>` : ''}`;
  }

  /* ================================================================== accueil : idées */

  const EXAMPLES = [['Paris', 'paris', 'Lyon', 'lyon'], ['Paris', 'paris', 'Bordeaux', 'bordeaux'], ['Lille', 'lille', 'Marseille', 'marseille'],
    ['Paris', 'paris', 'Toulouse', 'toulouse'], ['Lyon', 'lyon', 'Montpellier', 'montpellier'], ['Paris', 'paris', 'Annecy', 'annecy']];
  function renderIdeas() {
    $('#ideas').innerHTML = `<h2>Idées pour demain</h2>
      <div class="idea-list">${EXAMPLES.map(([f, , t], i) => `<button class="idea" type="button" data-ex="${i}"><b>${esc(f)} → ${esc(t)}</b><span>Voir les trains à 0 €</span></button>`).join('')}</div>
      <div class="facts">
        <div class="fact"><b>Correspondances recomposées</b>Deux trains Max qui s'enchaînent, même quand SNCF Connect ne les propose pas ensemble.</div>
        <div class="fact"><b>TER pour finir</b>Pour les gares sans TGV : le TER depuis la gare Max la plus proche, prix estimé selon ta carte régionale.</div>
        <div class="fact"><b>Aller-retour</b>« Ajouter le retour » pour chercher les deux sens d'un coup, sur des plages de dates.</div>
      </div>`;
  }

  /* ================================================================== explorer */
  async function runExplore() {
    const input = $('#e-from');
    const from = stationValue(input), date = $('#e-date').value;
    if (!from) { toast('Indique une gare de départ.'); input.focus(); return; }
    const box = $('#explore-results');
    box.innerHTML = `<div class="trips">${skeleton(4)}</div>`;
    $('#btn-explore').disabled = true;
    document.activeElement?.blur();
    try {
      state.explore = await api('/api/explore', { from, date, maxconn: opts.e_maxconn, ...profileParams() });
      state.exFilter = '';
      renderExplore();
      refreshView();
      if (isMobile()) scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) { box.innerHTML = `<p class="notice err">${esc(e.message)}</p>`; }
    $('#btn-explore').disabled = false;
  }

  function renderExplore() {
    const data = state.explore, box = $('#explore-results');
    const direct = data.destinations.filter(d => !d.nconn).length;
    box.innerHTML = `<div class="res-head">
        <div class="res-sum"><b>${plural(direct, 'gare', 'gares')} en direct</b> · ${plural(data.destinations.length - direct, 'avec correspondance', 'avec correspondance')}
          <small>Depuis ${esc(data.origin.name)}, ${fmtDay(data.date)} · touche une gare pour voir les trains</small></div>
        <div class="res-tools">${mapBtn()}</div>
        <input class="ex-filter" id="ex-filter" type="search" placeholder="Filtrer les gares…" aria-label="Filtrer les gares">
      </div>
      ${data.notice ? `<p class="notice">${esc(data.notice)}</p>` : ''}
      <div class="day-block"><ul class="trips" id="ex-list"></ul></div>`;
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
    setRT(false);
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

  /* ================================================================== signalements */
  function openFeedback() {
    $('#fb-message').value = '';
    $('#dlg-feedback').showModal();
    $('#fb-message').focus();
  }
  async function sendFeedback(e) {
    e.preventDefault();
    const message = $('#fb-message').value.trim();
    if (message.length < 3) { toast('Écris quelques mots pour décrire le problème ou l\'idée.'); $('#fb-message').focus(); return; }
    const btn = $('#fb-send');
    btn.disabled = true;
    try {
      const res = await fetch('/api/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: $('#form-feedback input[name="kind"]:checked')?.value || 'autre',
          message, contact: $('#fb-contact').value.trim(), page: location.pathname + location.search,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Le serveur a répondu ${res.status}.`);
      $('#dlg-feedback').close();
      toast('Merci ! Ton message a bien été envoyé.');
    } catch (err) { toast(err.message || 'Envoi impossible, réessaie plus tard.'); }
    btn.disabled = false;
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

  /* ================================================================== onglets */
  function showTab(t) {
    state.tab = t;
    $$('.tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === t)));
    for (const v of ['search', 'explore', 'favs']) $('#view-' + v).hidden = v !== t;
    refreshView();
    if (!isMobile()) $('#panel').scrollTop = 0;
  }

  /* ================================================================== événements */
  function swapOD() {
    const a = $('#s-from'), b = $('#s-to');
    const [av, al] = [a.value, a.dataset.label];
    setStation(a, b.value, b.dataset.label);
    setStation(b, av, al);
    $('#btn-swap').classList.toggle('spin');
    syncFav();
    if (stationValue(a) && stationValue(b)) runSearch();   // relance directement dans l'autre sens
  }

  function bindUI() {
    $('#btn-swap').innerHTML = ICON.swap;
    $('#btn-search').innerHTML = `${ICON.search}<span>Rechercher</span>`;
    $('#btn-fav').innerHTML = ICON.star;
    $('#btn-cal').innerHTML = `${ICON.cal}<span><b>Calendrier du mois</b><small>Voir d'un coup d'œil les jours avec des trains à 0 €</small></span>`;
    $('#btn-feedback').innerHTML = `${ICON.msg}<span>Signaler</span>`;
    $$('[data-locate]').forEach(b => { b.innerHTML = ICON.locate; b.addEventListener('click', () => locate($('#' + b.dataset.locate))); });
    $$('.od-row>label').forEach(l => l.addEventListener('click', () => $('#' + l.htmlFor)?.focus()));

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

    $$('.pill[data-pill]').forEach(b => b.addEventListener('click', () => clickPill(b.dataset.pill)));
    $('#btn-swap').addEventListener('click', swapOD);
    $$('.chip[data-quick]').forEach(c => c.addEventListener('click', () => {
      setDates(...quickRange(c.dataset.quick));
      if (state.rt && $('#r-fd').value < $('#s-td').value) setRT(true, addDays($('#s-td').value, 1));
    }));
    $('#s-fd').addEventListener('change', () => {
      if (!$('#s-td').value || $('#s-td').value < $('#s-fd').value) $('#s-td').value = $('#s-fd').value;
      markQuick();
    });
    $('#s-td').addEventListener('change', markQuick);
    $('#r-fd').addEventListener('change', () => { if (!$('#r-td').value || $('#r-td').value < $('#r-fd').value) $('#r-td').value = $('#r-fd').value; });
    $('#btn-add-ret').addEventListener('click', () => { setRT(true); $('#r-fd').focus(); });
    $('#btn-cal').addEventListener('click', () => ($('#cal').hidden ? openCal() : closeCal()));
    $('#cal').addEventListener('click', e => {
      const b = e.target.closest('[data-day]');
      if (!b) return;
      setDates(b.dataset.day, b.dataset.day);
      $('#s-start').value = ''; $('#s-end').value = '';
      if (state.rt && $('#r-fd').value < b.dataset.day) setRT(true, addDays(b.dataset.day, 2));
      runSearch();
    });
    for (const id of ['#s-from', '#s-to']) $(id).addEventListener('change', () => { if (!$('#cal').hidden) openCal(); });
    $('#btn-rm-ret').addEventListener('click', () => setRT(false));

    $('#form-search').addEventListener('submit', e => { e.preventDefault(); runSearch(); });
    $('#form-explore').addEventListener('submit', e => { e.preventDefault(); runExplore(); });
    $('#btn-fav').addEventListener('click', toggleFav);
    $('#search-sum').addEventListener('click', e => {
      if (e.target.closest('#btn-edit')) { state.editing = true; refreshView(false); $('#s-from').focus(); }
      if (e.target.closest('#btn-sum-cal')) { state.editing = true; refreshView(false); openCal(); }
    });

    // délégation : boutons carte (résultats et explorer)
    document.addEventListener('click', e => { if (e.target.closest('[data-map-toggle]')) setMapOn(!mapOn); });

    // délégation : résultats
    $('#results').addEventListener('click', async e => {
      const hit = e.target.closest('.trip-hit');
      if (hit) { select(hit.closest('.trip').dataset.key); return; }
      const dirB = e.target.closest('[data-dir]');
      if (dirB) { setDir(dirB.dataset.dir); return; }
      if (e.target.closest('#btn-more')) { state.showMore = !state.showMore; renderResults(); return; }
      if (e.target.closest('[data-night]')) { state.showNight = !state.showNight; renderResults(); return; }
      const sortB = e.target.closest('#sort button');
      if (sortB) { state.sort = sortB.dataset.v; store.set('sort', state.sort); renderResults(); return; }
      if (e.target.closest('#btn-share')) {
        const url = shareURL();
        try {
          if (navigator.share && isMobile()) await navigator.share({ title: 'MaxPlan', text: 'Regarde ces trains à 0 €', url });
          else { await navigator.clipboard.writeText(url); toast('Lien copié : envoie-le à qui tu veux.'); }
        } catch { toast(url); }
      }
    });
    $('#results').addEventListener('change', e => {
      if (e.target.id === 'free-only') { state.freeOnly = e.target.checked; store.set('freeOnly', state.freeOnly); renderResults(); }
    });
    $('#ideas').addEventListener('click', e => {
      const ex = e.target.closest('[data-ex]');
      if (!ex) return;
      const [f, fl, t, tl] = EXAMPLES[Number(ex.dataset.ex)];
      setStation($('#s-from'), f, fl); setStation($('#s-to'), t, tl);
      setDates(...quickRange('tomorrow'));
      $('#s-start').value = ''; $('#s-end').value = '';
      setRT(false);
      showTab('search');
      runSearch();
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
    $$('#btn-feedback, [data-feedback]').forEach(b => b.addEventListener('click', openFeedback));
    $('#dlg-feedback [data-close]').addEventListener('click', () => $('#dlg-feedback').close());
    $('#form-feedback').addEventListener('submit', sendFeedback);
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
    let rt;
    addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => refreshView(), 200); });
  }

  /* ================================================================== démarrage */
  async function init() {
    applyTheme();
    bindUI();
    renderProfileChip();
    renderPills();
    renderIdeas();
    syncFav();
    renderFavs();
    refreshView();

    try { state.meta = await api('/api/meta'); }
    catch { $('#data-status').textContent = 'Données SNCF indisponibles pour le moment.'; return; }
    const { start, end } = state.meta.dates;
    if (start) {
      $('#data-status').textContent = `Places Max du ${fmtShort(start)} au ${fmtShort(end)} · mises à jour chaque jour`;
      for (const s of ['#s-fd', '#s-td', '#r-fd', '#r-td', '#e-date']) { $(s).min = start; $(s).max = end; }
    }
    setDates(...quickRange('tomorrow'));
    $('#e-date').value = clampDate(todayISO());

    const q = new URLSearchParams(location.search);
    if (q.get('f') && q.get('t')) {
      applyState(Object.fromEntries(q));
      runSearch();
    } else {
      const last = store.get('last', null);
      if (last) applyState({ ...last, du: null, au: null, h1: '', h2: '', r: null });
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
