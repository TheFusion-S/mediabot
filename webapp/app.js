/* MediaBot Mini App — vanilla JS, no build step.
 * Security: remote/user data is only ever rendered through textContent / attributes
 * built with createElement. No innerHTML, no eval, no inline handlers (CSP-safe).
 */
(function () {
  'use strict';

  /* ======================================================================
   * Environment
   * ==================================================================== */
  var TG = (window.Telegram && window.Telegram.WebApp) || null;
  var QS = new URLSearchParams(location.search);
  var MOCK = QS.get('mock') === '1';
  var IN_TG = !!(TG && TG.platform && TG.platform !== 'unknown');
  var INIT_DATA = (TG && typeof TG.initData === 'string') ? TG.initData : '';
  var API_BASE = '/api';
  var POLL_MS = 1000;
  var ROOT = document.documentElement;

  function tgv(ver) {
    try { return !!(IN_TG && TG.isVersionAtLeast && TG.isVersionAtLeast(ver)); } catch (e) { return false; }
  }
  function safe(fn) { try { return fn(); } catch (e) { return undefined; } }
  var store = {
    get: function (k) { return safe(function () { return localStorage.getItem('mb:' + k); }); },
    set: function (k, v) { safe(function () { localStorage.setItem('mb:' + k, v); }); }
  };

  /* ======================================================================
   * Static copy (Uzbek, Latin)
   * ==================================================================== */
  var SECTIONS = {
    instagram: {
      platform: 'instagram', name: 'Instagram', tab: 'tab-instagram',
      title: 'Instagram Reels va postlar',
      sub: 'Reels, post va karusellar — asl sifatda',
      placeholder: 'instagram.com/reel/…',
      example: 'instagram.com/reel/…',
      historyTitle: 'Instagram tarixi',
      guide: [
        ['Havolani nusxalang', 'Instagram’da “Ulashish” → “Havolani nusxalash”'],
        ['Joylang va tekshiring', '“Joylash” tugmasi havolani o‘zi qo‘yadi'],
        ['Chatga yuboriladi', 'Reels 9:16 formatda, karusel albom ko‘rinishida']
      ]
    },
    shorts: {
      platform: 'youtube', name: 'Shorts', tab: 'tab-shorts',
      title: 'YouTube Shorts',
      sub: 'Vertikal 9:16 format o‘zgarmaydi',
      placeholder: 'youtube.com/shorts/…',
      example: 'youtube.com/shorts/…',
      historyTitle: 'Shorts tarixi',
      guide: [
        ['Shorts havolasini oling', 'Ulashish → “Nusxa olish”'],
        ['Joylang va tekshiring', 'Bo‘lim avtomatik aniqlanadi'],
        ['Vertikal video chatda', 'Telegram uni Shorts kabi tik ko‘rsatadi']
      ]
    },
    videos: {
      platform: 'youtube', name: 'Videolar', tab: 'tab-videos',
      title: 'YouTube videolar',
      sub: '1080p gacha sifat yoki MP3 audio',
      placeholder: 'youtu.be/… yoki youtube.com/watch?v=…',
      example: 'youtube.com/watch?v=…',
      historyTitle: 'Videolar tarixi',
      guide: [
        ['Video havolasini oling', 'youtube.com/watch yoki youtu.be havolasi'],
        ['Sifatni tanlang', '1080p, 720p, 480p, 360p yoki MP3'],
        ['Chatga yuboriladi', 'Gorizontal 16:9, oqimli ko‘rish bilan']
      ]
    }
  };

  var KIND_LABEL = { reel: 'Reels', post: 'Post', short: 'Shorts', video: 'Video' };

  var ERRORS = {
    unauthorized: ['Sessiya tasdiqlanmadi', 'Ilovani bot orqali qayta oching'],
    forbidden: ['Ruxsat kerak', 'Botga /start yozib, egasidan ruxsat so‘rang.'],
    bad_request: ['So‘rov noto‘g‘ri', 'Sahifani yangilab, qayta urinib ko‘ring.'],
    invalid_url: ['Havola noto‘g‘ri', 'Instagram yoki YouTube video havolasini yuboring.'],
    unsupported: ['Qo‘llab-quvvatlanmaydi', 'Bu turdagi havola hozircha qo‘llab-quvvatlanmaydi.'],
    private: ['Yopiq kontent', 'Akkaunt yopiq yoki kontent faqat obunachilarga ochiq.'],
    not_found: ['Topilmadi', 'Kontent topilmadi — u o‘chirilgan yoki havola xato bo‘lishi mumkin.'],
    too_long: ['Video juda uzun', 'Bu video ruxsat etilgan davomiylikdan uzun.'],
    too_large: ['Fayl juda katta', 'Tanlangan sifat Telegram limitidan katta. Pastroq sifat yoki MP3 ni tanlang.'],
    rate_limited: ['Limit tugadi', 'Soatlik yuklash limiti tugadi. Birozdan so‘ng qayta urinib ko‘ring.'],
    busy: ['Faol yuklash bor', 'Avvalgi yuklash hali tugamagan. U tugashini kuting.'],
    internal: ['Serverda xatolik', 'Nimadir noto‘g‘ri ketdi. Birozdan so‘ng qayta urinib ko‘ring.'],
    network: ['Aloqa yo‘q', 'Internet aloqasini tekshirib, qayta urinib ko‘ring.'],
    timeout: ['Javob kechikdi', 'Server uzoq javob bermadi. Qayta urinib ko‘ring.']
  };

  var STATUS = {
    queued: { title: 'Navbatda', sub: 'Tez orada boshlanadi', emoji: '⏳' },
    downloading: { title: 'Yuklanmoqda', sub: 'Manbadan olinmoqda', emoji: '⬇️' },
    processing: { title: 'Ishlanmoqda', sub: 'Video Telegram uchun tayyorlanmoqda', emoji: '⚙️' },
    uploading: { title: 'Yuborilmoqda', sub: 'Chatingizga yuborilmoqda', emoji: '📤' }
  };
  var STEP_ORDER = ['queued', 'downloading', 'processing', 'uploading'];
  var STEP_META = [
    ['Navbat', 'clock'], ['Yuklash', 'download'], ['Ishlash', 'sparkle'], ['Yuborish', 'send']
  ];

  /* ======================================================================
   * DOM helpers (no innerHTML anywhere)
   * ==================================================================== */
  var SVGNS = 'http://www.w3.org/2000/svg';
  function $(id) { return document.getElementById(id); }

  function h(tag, props) {
    var el = document.createElement(tag);
    if (props) {
      for (var k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        var v = props[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = String(v);
        else if (k === 'style') { for (var s in v) el.style[s] = v[s]; }
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2), v);
        else if (k === 'dataset') { for (var d in v) el.dataset[d] = v[d]; }
        else if (k === 'checked' || k === 'disabled' || k === 'value') el[k] = v;
        else el.setAttribute(k, v === true ? '' : String(v));
      }
    }
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { append(el, x); }); return; }
    el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  }
  function icon(name, cls) {
    var s = document.createElementNS(SVGNS, 'svg');
    s.setAttribute('class', 'ic' + (cls ? ' ' + cls : ''));
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('focusable', 'false');
    var u = document.createElementNS(SVGNS, 'use');
    u.setAttribute('href', '#i-' + name);
    s.appendChild(u);
    return s;
  }
  function setIcon(svg, name) {
    var u = svg && svg.querySelector('use');
    if (u) u.setAttribute('href', '#i-' + name);
  }

  /* Only https: thumbnails (mock mode additionally allows its own generated data:image/svg+xml). */
  function safeImgUrl(u) {
    if (typeof u !== 'string' || !u || u.length > 4096) return null;
    if (MOCK && u.indexOf('data:image/svg+xml') === 0) return u;
    try {
      var p = new URL(u);
      return p.protocol === 'https:' ? p.href : null;
    } catch (e) { return null; }
  }
  function img(src, cls, onFail) {
    var url = safeImgUrl(src);
    if (!url) return null;
    var el = h('img', { class: cls || null, alt: '', decoding: 'async', loading: 'lazy', referrerpolicy: 'no-referrer', draggable: 'false' });
    el.referrerPolicy = 'no-referrer';
    if (onFail) el.addEventListener('error', function () { onFail(el); }, { once: true });
    el.src = url;
    return el;
  }

  /* ======================================================================
   * Formatting
   * ==================================================================== */
  function num(n, digits) {
    return Number(n).toFixed(digits).replace('.', ',');
  }
  function fmtSize(bytes) {
    if (typeof bytes !== 'number' || !isFinite(bytes) || bytes <= 0) return null;
    var mb = bytes / 1048576;
    if (mb >= 1024) return num(mb / 1024, 1) + ' GB';
    if (mb >= 100) return Math.round(mb) + ' MB';
    if (mb >= 0.1) return num(mb, 1) + ' MB';
    return Math.max(1, Math.round(bytes / 1024)) + ' KB';
  }
  function fmtDur(sec) {
    if (typeof sec !== 'number' || !isFinite(sec) || sec < 0) return null;
    sec = Math.round(sec);
    var hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
    var p2 = function (x) { return (x < 10 ? '0' : '') + x; };
    return hh ? hh + ':' + p2(mm) + ':' + p2(ss) : mm + ':' + p2(ss);
  }
  var MONTHS = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'];
  function relTime(iso) {
    var t = Date.parse(iso);
    if (!isFinite(t)) return '';
    var diff = (Date.now() - t) / 1000;
    if (diff < 60) return 'hozirgina';
    if (diff < 3600) return Math.floor(diff / 60) + ' daqiqa oldin';
    if (diff < 86400) return Math.floor(diff / 3600) + ' soat oldin';
    if (diff < 172800) return 'kecha';
    if (diff < 604800) return Math.floor(diff / 86400) + ' kun oldin';
    var d = new Date(t);
    return d.getDate() + '-' + MONTHS[d.getMonth()];
  }
  function aspectLabel(w, h2) {
    if (!w || !h2) return null;
    var r = w / h2;
    var known = [[9 / 16, '9:16'], [4 / 5, '4:5'], [3 / 4, '3:4'], [1, '1:1'], [4 / 3, '4:3'], [16 / 9, '16:9'], [21 / 9, '21:9']];
    for (var i = 0; i < known.length; i++) if (Math.abs(r - known[i][0]) / known[i][0] < 0.04) return known[i][1];
    return w + '×' + h2;
  }
  function fmtName(f) {
    if (f.id === 'auto') return 'Avto';
    if (f.id === 'audio') return 'MP3';
    return f.id + 'p';
  }
  /** For 'auto', show the tier it resolves to when that tier is also offered (avoids two identical-looking chips). */
  function fmtTag(f, formats) {
    if (f.id !== 'auto' || !f.height || !formats) return null;
    var same = formats.some(function (o) { return o.id !== 'auto' && String(o.id) === String(f.height); });
    return same ? f.height + 'p' : null;
  }
  function fmtShort(id) {
    if (id === 'auto') return 'Avto';
    if (id === 'audio') return 'MP3';
    if (/^\d+$/.test(String(id))) return id + 'p';
    return String(id || '');
  }

  /* ======================================================================
   * Link classification (mirrors server allowlist in SPEC)
   * ==================================================================== */
  var YT_HOSTS = { 'youtube.com': 1, 'www.youtube.com': 1, 'm.youtube.com': 1, 'music.youtube.com': 1, 'youtu.be': 1 };
  var IG_HOSTS = { 'instagram.com': 1, 'www.instagram.com': 1, 'm.instagram.com': 1 };
  var YT_ID = /^[A-Za-z0-9_-]{11}$/;
  var IG_CODE = /^[A-Za-z0-9_-]{5,64}$/;

  // Mirrors bot/platforms.py exactly (QA-L10): whitespace tokens, strict host/path/ID rules,
  // first SUPPORTED link wins. No URL normalisation (ports, trailing dots, extra segments are rejected).
  var ALLOWED_HOSTS = {};
  Object.keys(YT_HOSTS).concat(Object.keys(IG_HOSTS)).forEach(function (k) { ALLOWED_HOSTS[k] = 1; });
  var IG_USER = /^[A-Za-z0-9._]{1,30}$/;
  var IG_KINDS = { reel: 'reel', reels: 'reel', tv: 'reel', p: 'post' };
  var TOK_LEADING = '<([{"\'«“‘';
  var TOK_TRAILING = '>)]}"\'».,!?;:“”’';
  var MAX_URL_LEN = 2048;

  function stripSet(t, set, left, right) {
    var i = 0, j = t.length;
    if (left) while (i < j && set.indexOf(t.charAt(i)) >= 0) i++;
    if (right) while (j > i && set.indexOf(t.charAt(j - 1)) >= 0) j--;
    return t.slice(i, j);
  }

  /** Candidate URLs in order (same as backend _candidates); `schemeSeen` flags non-http(s) tokens. */
  function candidates(text) {
    var out = [];
    out.schemeSeen = false;
    text.slice(0, 8192).split(/\s+/).forEach(function (raw) {
      var tok = stripSet(stripSet(raw, TOK_LEADING, true, true), TOK_TRAILING, false, true);
      if (!tok) return;
      var low = tok.toLowerCase();
      if (low.indexOf('://') >= 0) {
        if (low.indexOf('http://') === 0 || low.indexOf('https://') === 0) out.push(tok);
        else out.schemeSeen = true;
        return;
      }
      var hostPart = low.split(/[/?#]/)[0];
      if (ALLOWED_HOSTS[hostPart]) out.push('https://' + tok);
    });
    return out;
  }

  function hostOnly(platform, segs) {
    var s0 = segs[0] || '';
    var reason;
    if (platform === 'youtube') reason = s0 === 'playlist' ? 'yt_playlist' : (/^@/.test(s0) || s0 === 'c' || s0 === 'channel' || s0 === 'user') ? 'yt_channel' : 'yt_path';
    else reason = s0.toLowerCase() === 'share' ? 'ig_share' : (s0 === 'stories' || s0 === 's') ? 'ig_stories' : 'ig_path';
    return { ok: false, reason: reason, platform: platform, rank: 3 };
  }

  function parseCandidate(url) {
    if (url.length > MAX_URL_LEN || !/^[\x21-\x7e]+$/.test(url) || url.indexOf('\\') >= 0) return { ok: false, reason: 'host', rank: 0 };
    var m = url.match(/^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)([^?#]*)(?:\?([^#]*))?(?:#.*)?$/);
    if (!m) return { ok: false, reason: 'host', rank: 0 };
    var scheme = m[1].toLowerCase(), netloc = m[2], path = m[3] || '/', query = m[4] || '';
    if (scheme !== 'http' && scheme !== 'https') return { ok: false, reason: 'scheme', rank: 1 };
    var host = netloc.toLowerCase();
    if (!netloc || /[@:[\]%]/.test(netloc) || !ALLOWED_HOSTS[host]) {
      // Allowlisted host spoiled by a port, userinfo or trailing dot: backend rejects it as invalid.
      var bare = host.replace(/^.*@/, '').replace(/:\d*$/, '').replace(/\.$/, '');
      return ALLOWED_HOSTS[bare] ? { ok: false, reason: 'malformed', rank: 2 } : { ok: false, reason: 'host', rank: 0 };
    }
    if (path.indexOf('//') >= 0) return { ok: false, reason: 'malformed', rank: 2 };
    var trimmed = path.replace(/^\/+/, '').replace(/\/+$/, '');
    var segs = trimmed ? trimmed.split('/') : [];

    if (YT_HOSTS[host]) {
      var id = null, kind = 'video';
      if (host === 'youtu.be') {
        if (segs.length === 1 && YT_ID.test(segs[0])) id = segs[0];
      } else if (segs.length === 1 && segs[0] === 'watch') {
        var v = null;
        try { v = new URLSearchParams(query).getAll('v')[0]; } catch (e) { v = null; }
        if (v && YT_ID.test(v)) id = v;
      } else if (segs.length === 2 && (segs[0] === 'shorts' || segs[0] === 'live' || segs[0] === 'embed') && YT_ID.test(segs[1])) {
        id = segs[1]; kind = segs[0] === 'shorts' ? 'short' : 'video';
      }
      if (!id) return hostOnly('youtube', segs);
      return {
        ok: true, platform: 'youtube', kind: kind, id: id,
        section: kind === 'short' ? 'shorts' : 'videos',
        url: kind === 'short' ? 'https://www.youtube.com/shorts/' + id : 'https://www.youtube.com/watch?v=' + id
      };
    }
    // Instagram. "/share/…" links are opaque tokens, not media codes: never guess.
    if (segs.length && segs[0].toLowerCase() === 'share') return hostOnly('instagram', segs);
    var s = segs;
    if (s.length === 3 && IG_USER.test(s[0]) && !IG_KINDS[s[0].toLowerCase()]) s = s.slice(1);
    if (s.length === 2 && IG_KINDS[s[0].toLowerCase()] && IG_CODE.test(s[1])) {
      var k = IG_KINDS[s[0].toLowerCase()];
      return {
        ok: true, platform: 'instagram', kind: k, id: s[1], section: 'instagram',
        url: 'https://www.instagram.com/' + (k === 'post' ? 'p' : 'reel') + '/' + s[1] + '/'
      };
    }
    return hostOnly('instagram', segs);
  }

  /** Returns {ok:true, platform, kind, section, id, url, raw} for the first supported link,
   *  or {ok:false, reason, platform?} describing the most specific failure. */
  function classify(text) {
    if (typeof text !== 'string' || !text.trim()) return { ok: false, reason: 'empty' };
    var cands = candidates(text);
    var best = cands.schemeSeen ? { ok: false, reason: 'scheme', rank: 1 } : null;
    for (var i = 0; i < cands.length; i++) {
      var r = parseCandidate(cands[i]);
      if (r.ok) { r.raw = cands[i]; return r; }
      if (!best || r.rank > best.rank) best = r;
    }
    return best || { ok: false, reason: 'host' };
  }

  /* ======================================================================
   * Telegram integration
   * ==================================================================== */
  var haptic = {
    sel: function () { if (tgv('6.1')) safe(function () { TG.HapticFeedback.selectionChanged(); }); },
    tap: function (style) { if (tgv('6.1')) safe(function () { TG.HapticFeedback.impactOccurred(style || 'light'); }); },
    note: function (type) { if (tgv('6.1')) safe(function () { TG.HapticFeedback.notificationOccurred(type); }); }
  };

  var ACCENT_HEX = { instagram: '#C13584', shorts: '#E00020', videos: '#E00020' };

  function applyTheme() {
    if (!IN_TG) return;
    ROOT.dataset.theme = TG.colorScheme === 'dark' ? 'dark' : 'light';
    if (tgv('6.1')) {
      safe(function () { TG.setHeaderColor('secondary_bg_color'); });
      safe(function () { TG.setBackgroundColor('secondary_bg_color'); });
    }
    if (tgv('7.10')) safe(function () { TG.setBottomBarColor('secondary_bg_color'); });
  }

  var mbState = { text: '', visible: false, active: false, progress: false, color: '' };
  function setMainButton(cfg) {
    if (!IN_TG || !TG.MainButton) return;
    var MB = TG.MainButton;
    var next = {
      text: cfg ? cfg.text : '', visible: !!cfg, active: cfg ? cfg.active !== false : false,
      progress: !!(cfg && cfg.progress), color: ACCENT_HEX[S.section]
    };
    if (!next.visible) { if (mbState.visible) safe(function () { MB.hideProgress(); MB.hide(); }); mbState = next; return; }
    if (next.text !== mbState.text || next.active !== mbState.active || next.color !== mbState.color || !mbState.visible) {
      safe(function () {
        MB.setParams({ text: next.text, color: next.color, text_color: '#FFFFFF', is_active: next.active, is_visible: true });
      });
    }
    if (next.progress !== mbState.progress) safe(function () { next.progress ? MB.showProgress(false) : MB.hideProgress(); });
    mbState = next;
  }

  var backVisible = false;
  function updateBackButton() {
    if (!tgv('6.1') || !TG.BackButton) return;
    var st = cur();
    var want = S.sheetOpen || st.phase === 'preview' || st.phase === 'probeError' || st.phase === 'done' || st.phase === 'jobError';
    if (want === backVisible) return;
    backVisible = want;
    safe(function () { want ? TG.BackButton.show() : TG.BackButton.hide(); });
  }

  /* ======================================================================
   * API layer
   * ==================================================================== */
  function ApiError(code, message, status) {
    this.code = code || 'internal';
    this.message = message || '';
    this.status = status || 0;
  }

  function codeFromStatus(s) {
    return ({ 400: 'bad_request', 401: 'unauthorized', 403: 'private', 404: 'not_found', 409: 'busy', 413: 'too_large', 429: 'rate_limited' })[s] || 'internal';
  }

  function api(method, path, body, timeoutMs) {
    if (MOCK) return Mock.handle(method, path, body);
    var headers = { 'Accept': 'application/json' };
    if (INIT_DATA) headers['X-Telegram-Init-Data'] = INIT_DATA;
    if (body) headers['Content-Type'] = 'application/json';
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs || 15000) : null;
    return fetch(API_BASE + path, {
      method: method, headers: headers, body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin', cache: 'no-store', signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok || !data || data.ok !== true) {
          var e = data && data.error && typeof data.error === 'object' ? data.error : {};
          throw new ApiError(typeof e.code === 'string' ? e.code : codeFromStatus(res.status), typeof e.message === 'string' ? e.message : '', res.status);
        }
        return data;
      });
    }, function (err) {
      throw new ApiError(err && err.name === 'AbortError' ? 'timeout' : 'network', '', 0);
    }).then(function (d) { if (timer) clearTimeout(timer); return d; }, function (e) {
      if (timer) clearTimeout(timer);
      if (!(e instanceof ApiError)) e = new ApiError('internal', '', 0);
      if (e.code === 'unauthorized') onUnauthorized();
      if (e.code === 'forbidden') onForbidden();
      throw e;
    });
  }

  function errCopy(err) {
    var code = (err && err.code) || 'internal';
    var base = ERRORS[code] || ERRORS.internal;
    var msg = base[1];
    if (code === 'too_long' && S.me.data && S.me.data.limits && S.me.data.limits.max_duration_min) {
      msg = 'Maksimal davomiylik — ' + S.me.data.limits.max_duration_min + ' daqiqa.';
    }
    var server = err && typeof err.message === 'string' ? err.message.trim() : '';
    if (server && server.length < 240 && code !== 'unauthorized' && code !== 'internal' && code !== 'too_large') msg = server;
    return { title: base[0], text: msg, code: code };
  }

  /* --- sanitizers: coerce remote JSON into known shapes --- */
  function str(v, max) { return typeof v === 'string' ? v.slice(0, max || 500) : ''; }
  function int(v) { return typeof v === 'number' && isFinite(v) ? Math.round(v) : null; }
  var FMT_IDS = { auto: 1, '1080': 1, '720': 1, '480': 1, '360': 1, audio: 1 };
  function sanitizeMedia(m) {
    m = m && typeof m === 'object' ? m : {};
    var section = SECTIONS[m.section] ? m.section : null;
    var w = int(m.width), hh = int(m.height);
    var orient = (m.orientation === 'vertical' || m.orientation === 'horizontal' || m.orientation === 'square') ? m.orientation
      : (w && hh ? (w > hh * 1.05 ? 'horizontal' : (hh > w * 1.05 ? 'vertical' : 'square')) : null);
    var formats = Array.isArray(m.formats) ? m.formats.filter(function (f) { return f && FMT_IDS[String(f.id)]; }).map(function (f) {
      return { id: String(f.id), label: str(f.label, 40), height: int(f.height), size: int(f.size), fits: f.fits !== false };
    }) : [];
    return {
      platform: m.platform === 'youtube' ? 'youtube' : 'instagram',
      kind: KIND_LABEL[m.kind] ? m.kind : 'video',
      section: section,
      id: str(m.id, 100), url: str(m.url, 300),
      title: str(m.title, 300) || 'Nomsiz', author: str(m.author, 120) || null,
      thumbnail: safeImgUrl(m.thumbnail), duration: int(m.duration),
      width: w, height: hh, orientation: orient,
      items_count: Math.max(1, int(m.items_count) || 1), formats: formats
    };
  }
  function sanitizeJob(j) {
    j = j && typeof j === 'object' ? j : {};
    var p = int(j.progress);
    return {
      id: str(j.id, 100),
      status: ['queued', 'downloading', 'processing', 'uploading', 'done', 'error'].indexOf(j.status) >= 0 ? j.status : 'queued',
      progress: p === null ? 0 : Math.max(0, Math.min(100, p)),
      format: str(j.format, 20),
      used_format: FMT_IDS[String(j.used_format)] ? String(j.used_format) : null,
      note: typeof j.note === 'string' && j.note.trim() ? j.note.trim().slice(0, 300) : null,
      error: j.error && typeof j.error === 'object' ? { code: str(j.error.code, 40), message: str(j.error.message, 300) } : null
    };
  }

  /* ======================================================================
   * State
   * ==================================================================== */
  function newSec() {
    return { url: '', phase: 'idle', link: null, media: null, fmt: null, job: null, error: null, actionError: null, notice: null, seq: 0, timer: 0, netFails: 0, refs: null };
  }
  var S = {
    section: 'instagram',
    ytSub: 'shorts',
    sec: { instagram: newSec(), shorts: newSec(), videos: newSec() },
    hist: { instagram: { items: null, loading: false, error: null }, shorts: { items: null, loading: false, error: null }, videos: { items: null, loading: false, error: null } },
    me: { data: null, loading: false, error: null },
    sheetOpen: false,
    authFailed: false,
    forbidden: false,
    offline: typeof navigator.onLine === 'boolean' ? !navigator.onLine : false
  };
  function cur() { return S.sec[S.section]; }

  /* ======================================================================
   * Elements
   * ==================================================================== */
  var el = {
    tabIg: $('tab-instagram'), tabYt: $('tab-youtube'), subtabs: $('subtabs'),
    tabShorts: $('tab-shorts'), tabVideos: $('tab-videos'), panel: $('panel'),
    title: $('secTitle'), sub: $('secSub'), form: $('linkForm'), field: $('field'), input: $('url'),
    clear: $('clearBtn'), hint: $('hint'), paste: $('pasteBtn'), check: $('checkBtn'),
    notice: $('notice'), ws: $('workspace'), histTitle: $('historyTitle'), histSub: $('historySub'),
    histList: $('historyList'), refresh: $('refreshBtn'), banners: $('banners'),
    profileBtn: $('profileBtn'), avatar: $('avatar'), demo: $('demoPill'),
    sheet: $('sheet'), sheetPanel: $('sheetPanel'), sheetBody: $('sheetBody'), sheetClose: $('sheetClose'), sheetBackdrop: $('sheetBackdrop'),
    toast: $('toast'), sr: $('srLive'), app: $('app')
  };

  function announce(text) {
    el.sr.textContent = '';
    setTimeout(function () { el.sr.textContent = text; }, 30);
  }
  var toastTimer = 0;
  function toast(text, kind) {
    clearTimeout(toastTimer);
    el.toast.replaceChildren(icon(kind === 'error' ? 'alert' : kind === 'info' ? 'info' : 'check-circle'), h('span', { text: text }));
    el.toast.className = 'toast' + (kind === 'error' ? ' is-error' : kind === 'info' ? ' is-info' : '');
    el.toast.hidden = false;
    toastTimer = setTimeout(function () { el.toast.hidden = true; }, 3200);
  }

  /* ======================================================================
   * Sections / tabs
   * ==================================================================== */
  function setSection(sec, opts) {
    opts = opts || {};
    if (!SECTIONS[sec]) return;
    var changed = sec !== S.section;
    S.section = sec;
    if (sec !== 'instagram') S.ytSub = sec;
    store.set('section', sec);
    ROOT.dataset.section = sec;

    var isYt = sec !== 'instagram';
    el.tabIg.setAttribute('aria-selected', String(!isYt));
    el.tabYt.setAttribute('aria-selected', String(isYt));
    el.tabIg.tabIndex = isYt ? -1 : 0;
    el.tabYt.tabIndex = isYt ? 0 : -1;
    el.subtabs.hidden = !isYt;
    el.tabShorts.setAttribute('aria-selected', String(sec === 'shorts'));
    el.tabVideos.setAttribute('aria-selected', String(sec === 'videos'));
    el.tabShorts.tabIndex = sec === 'shorts' ? 0 : -1;
    el.tabVideos.tabIndex = sec === 'videos' ? 0 : -1;
    el.panel.setAttribute('aria-labelledby', isYt ? 'tab-youtube ' + SECTIONS[sec].tab : 'tab-instagram');

    var meta = SECTIONS[sec];
    el.title.textContent = meta.title;
    el.sub.textContent = meta.sub;
    el.input.placeholder = meta.placeholder;
    el.input.value = cur().url;
    el.histTitle.textContent = meta.historyTitle;

    renderInputState();
    renderNotice();
    renderWorkspace(changed && !opts.noAnim);
    renderHistory();
    ensureHistory(sec);
    updateMainButton();
    updateBackButton();
    if (changed && IN_TG) safe(function () { if (mbState.visible) TG.MainButton.setParams({ color: ACCENT_HEX[sec] }); });
  }

  function onTabKey(e, tabs) {
    var i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    var n = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = tabs.length - 1;
    if (n === null) return;
    e.preventDefault();
    tabs[n].focus();
    tabs[n].click();
  }

  /* ======================================================================
   * Input + hints
   * ==================================================================== */
  function hintFor(sec, raw) {
    var meta = SECTIONS[sec];
    if (!raw.trim()) return { kind: 'neutral', icon: 'info', text: 'Masalan: ' + meta.example };
    var c = classify(raw);
    if (c.ok) {
      if (c.section !== sec) {
        return { kind: 'info', icon: 'swap', text: 'Bu ' + kindName(c) + ' havolasi — “' + SECTIONS[c.section].name + '” bo‘limida ochiladi' };
      }
      return { kind: 'ok', icon: 'check-circle', text: kindName(c) + ' havolasi aniqlandi', valid: true };
    }
    switch (c.reason) {
      case 'yt_playlist': return { kind: 'err', icon: 'alert', text: 'Playlistlar qo‘llab-quvvatlanmaydi — alohida video havolasini yuboring' };
      case 'yt_channel': return { kind: 'err', icon: 'alert', text: 'Bu kanal havolasi. Video havolasini yuboring: ' + meta.example };
      case 'yt_path': return { kind: 'err', icon: 'alert', text: 'YouTube video havolasi emas. Masalan: ' + (sec === 'instagram' ? 'youtube.com/watch?v=…' : meta.example) };
      case 'ig_stories': return { kind: 'err', icon: 'alert', text: 'Stories qo‘llab-quvvatlanmaydi — Reels yoki post havolasini yuboring' };
      case 'ig_path': return { kind: 'err', icon: 'alert', text: 'Reels yoki post havolasini yuboring: instagram.com/reel/… yoki /p/…' };
      case 'ig_share': return { kind: 'err', icon: 'alert', text: 'Instagram’dagi “Ulashish” havolasi qo‘llab-quvvatlanmaydi — Reels yoki postni oching va havolasini nusxalang' };
      case 'malformed': return { kind: 'err', icon: 'alert', text: 'Havola buzilgan ko‘rinishda (port, ortiqcha belgi). Uni ilovadan qaytadan nusxalang' };
      case 'scheme': return { kind: 'err', icon: 'alert', text: 'Faqat http(s) havolalar qabul qilinadi' };
      default: return { kind: 'err', icon: 'alert', text: 'Faqat Instagram va YouTube havolalari qo‘llab-quvvatlanadi' };
    }
  }
  function kindName(c) {
    if (c.platform === 'instagram') return c.kind === 'post' ? 'Instagram post' : 'Instagram Reels';
    return c.kind === 'short' ? 'YouTube Shorts' : 'YouTube video';
  }

  var hintTimer = 0;
  function renderInputState(strict) {
    var raw = el.input.value;
    var hnt = hintFor(S.section, raw);
    // While typing, soften errors until the user pauses or submits.
    var showErr = strict || raw.length > 12;
    if (hnt.kind === 'err' && !showErr) hnt = { kind: 'neutral', icon: 'info', text: 'Masalan: ' + SECTIONS[S.section].example };
    // After a failed check, a green "aniqlandi" hint would contradict the error card.
    if (cur().phase === 'probeError' && hnt.kind === 'ok') hnt = { kind: 'neutral', icon: 'info', text: 'Masalan: ' + SECTIONS[S.section].example };
    el.hint.className = 'hint' + (hnt.kind === 'neutral' ? '' : ' is-' + hnt.kind);
    el.hint.replaceChildren(icon(hnt.icon), h('span', { text: hnt.text }));
    el.field.classList.toggle('is-invalid', hnt.kind === 'err');
    el.field.classList.toggle('is-valid', !!hnt.valid);
    el.input.setAttribute('aria-invalid', String(hnt.kind === 'err'));
    var st = cur();
    var busy = st.phase === 'probing' || st.phase === 'starting' || st.phase === 'job';
    el.clear.hidden = !raw || busy;
    el.check.disabled = !raw.trim() || busy;
    // Only one primary action on screen: once a result card exists, "Tekshirish" steps back.
    var checkPrimary = st.phase === 'idle' || st.phase === 'probeError';
    el.check.classList.toggle('btn-primary', checkPrimary);
    el.check.classList.toggle('btn-secondary', !checkPrimary);
    el.paste.disabled = busy;
    el.input.readOnly = busy;
  }

  function isCoarse() {
    return !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
  }

  /** Move focus to a freshly rendered result (keyboard/screen-reader users keep their place). */
  function focusResult(selector) {
    if (S.sheetOpen) return;
    var node = el.ws.querySelector(selector);
    if (!node) return;
    if (!node.hasAttribute('tabindex')) node.setAttribute('tabindex', '-1');
    safe(function () { node.focus({ preventScroll: true }); });
  }

  function shakeField() {
    el.field.classList.remove('shake');
    void el.field.offsetWidth;
    el.field.classList.add('shake');
  }

  function routeLinkToSection(link, raw) {
    var from = S.section;
    var target = link.section;
    var tst = S.sec[target];
    tst.url = raw;
    tst.notice = { from: from, to: target, text: 'Bu ' + kindName(link) + ' havolasi edi — “' + SECTIONS[target].name + '” bo‘limiga o‘tkazildi.' };
    var fst = S.sec[from];
    if (fst.phase === 'idle' || fst.phase === 'probeError') { fst.url = ''; fst.phase = 'idle'; fst.error = null; }
    else fst.url = fst.media ? fst.media.url : '';
    haptic.note('warning');
    setSection(target);
    announce(tst.notice.text);
  }

  function check(opts) {
    opts = opts || {};
    var st = cur();
    var raw = el.input.value;
    if (st.phase === 'probing' || st.phase === 'starting' || st.phase === 'job') return;
    if (!raw.trim()) { shakeField(); el.input.focus(); return; }
    var link = classify(raw);
    if (!link.ok) {
      renderInputState(true);
      shakeField();
      haptic.note('error');
      return;
    }
    if (link.section !== S.section) { routeLinkToSection(link, raw); check({ keepNotice: true, blur: opts.blur }); return; }
    st.url = raw;
    if (!opts.keepNotice && st.notice) { st.notice = null; renderNotice(); }
    if (el.input === document.activeElement && opts.blur !== false && isCoarse()) el.input.blur();
    haptic.tap('light');
    probe(S.section, link);
  }

  function probe(sec, link) {
    var st = S.sec[sec];
    var seq = ++st.seq;
    st.phase = 'probing'; st.link = link; st.media = null; st.job = null; st.error = null; st.actionError = null;
    if (sec === S.section) { renderWorkspace(true); renderInputState(); updateMainButton(); updateBackButton(); }
    api('POST', '/probe', { url: link.url, section: sec }, 45000).then(function (data) {
      if (seq !== st.seq) return;
      var m = sanitizeMedia(data.media);
      if (!m.section) m.section = sec;
      if (!m.formats.length) m.formats = [{ id: 'auto', label: 'Avto', height: null, size: null, fits: true }];
      if (!m.url) m.url = link.url;
      if (m.section !== sec) {
        // Server re-classified (e.g. vertical ≤180s /watch → Shorts). Move the result.
        var tgt = S.sec[m.section];
        tgt.seq++; clearTimeout(tgt.timer);
        tgt.url = st.url; tgt.link = link; tgt.media = m; tgt.fmt = pickDefault(m); tgt.phase = 'preview';
        tgt.error = null; tgt.actionError = null; tgt.job = null;
        tgt.notice = {
          from: sec, to: m.section,
          text: m.section === 'shorts' ? 'Bu video vertikal va qisqa — “Shorts” bo‘limida ochildi.'
            : 'Bu havola “' + SECTIONS[m.section].name + '” bo‘limiga tegishli — o‘sha yerda ochildi.'
        };
        st.phase = 'idle'; st.url = ''; st.media = null; st.link = null;
        haptic.note('warning');
        setSection(m.section);
        announce(tgt.notice.text);
        focusResult('.media-title');
        setTimeout(revealWorkspace, 60);
        return;
      }
      st.media = m; st.fmt = pickDefault(m); st.phase = 'preview';
      haptic.note('success');
      if (sec === S.section) {
        renderWorkspace(true); renderInputState(); updateMainButton(); updateBackButton();
        announce('Topildi: ' + m.title);
        focusResult('.media-title');
        setTimeout(revealWorkspace, 60);
      }
    }, function (err) {
      if (seq !== st.seq) return;
      st.phase = 'probeError'; st.error = err;
      haptic.note('error');
      if (sec === S.section) {
        renderWorkspace(true); renderInputState(); updateMainButton(); updateBackButton();
        announce(errCopy(err).title + '. ' + errCopy(err).text);
        focusResult('.state');
        setTimeout(revealWorkspace, 60);
      }
    });
  }

  function pickDefault(m) {
    var fits = m.formats.filter(function (f) { return f.fits; });
    var auto = fits.filter(function (f) { return f.id === 'auto'; })[0];
    if (auto) return 'auto';
    var vids = fits.filter(function (f) { return /^\d+$/.test(f.id); }).sort(function (a, b) { return Number(b.id) - Number(a.id); });
    if (vids.length) return vids[0].id;
    if (fits.length) return fits[0].id;
    return null;
  }

  function resetSection(sec) {
    var st = S.sec[sec];
    st.seq++; clearTimeout(st.timer);
    st.phase = 'idle'; st.media = null; st.job = null; st.error = null; st.actionError = null; st.notice = null; st.fmt = null; st.link = null;
    if (sec === S.section) {
      renderWorkspace(true); renderNotice(); renderInputState(); updateMainButton(); updateBackButton();
    }
  }

  /* ======================================================================
   * Clipboard
   * ==================================================================== */
  function readClipboard() {
    var viaNav = function () {
      if (!navigator.clipboard || typeof navigator.clipboard.readText !== 'function') return Promise.reject(new Error('no-clipboard'));
      return navigator.clipboard.readText();
    };
    var viaTg = function () {
      return new Promise(function (resolve, reject) {
        if (!tgv('6.4') || typeof TG.readTextFromClipboard !== 'function') { reject(new Error('no-tg')); return; }
        var done = false;
        var t = setTimeout(function () { if (!done) { done = true; reject(new Error('timeout')); } }, 2500);
        try {
          TG.readTextFromClipboard(function (text) {
            if (done) return; done = true; clearTimeout(t);
            typeof text === 'string' && text ? resolve(text) : reject(new Error('denied'));
          });
        } catch (e) { done = true; clearTimeout(t); reject(e); }
      });
    };
    return viaNav().then(function (t) { if (!t) throw new Error('empty'); return t; }).catch(function () { return viaTg(); });
  }

  function onPaste() {
    haptic.tap('light');
    readClipboard().then(function (text) {
      var pc = classify(text);
      el.input.value = (pc.ok ? pc.raw : text).trim().slice(0, 2048);
      cur().url = el.input.value;
      renderInputState(true);
      var c = classify(el.input.value);
      if (c.ok) check({ blur: true });
      else { shakeField(); haptic.note('error'); }
    }, function () {
      el.hint.className = 'hint is-info';
      el.hint.replaceChildren(icon('info'), h('span', { text: 'Buferga ruxsat berilmadi. Maydonni bosib turing va “Qo‘yish”ni tanlang.' }));
      el.input.focus();
    });
  }

  /* ======================================================================
   * Download + job polling
   * ==================================================================== */
  function startDownload(sec) {
    sec = sec || S.section;
    var st = S.sec[sec];
    if (!st.media || !st.fmt || st.phase === 'starting' || st.phase === 'job') return;
    var seq = ++st.seq;
    st.phase = 'starting'; st.actionError = null;
    haptic.tap('medium');
    if (sec === S.section) { renderAction(); renderInputState(); updateMainButton(); updateBackButton(); }
    api('POST', '/download', { url: st.media.url, format: st.fmt }, 20000).then(function (data) {
      if (seq !== st.seq) return;
      st.job = sanitizeJob(data.job);
      st.job.format = st.job.format || st.fmt;
      st.phase = st.job.status === 'done' ? 'done' : st.job.status === 'error' ? 'jobError' : 'job';
      st.netFails = 0;
      if (st.phase === 'job') schedulePoll(sec, POLL_MS);
      if (st.phase === 'done') onJobDone(sec);
      else if (sec === S.section) { renderAction(); renderInputState(); updateMainButton(); updateBackButton(); announce(STATUS[st.job.status] ? STATUS[st.job.status].title : ''); }
    }, function (err) {
      if (seq !== st.seq) return;
      st.phase = 'preview'; st.actionError = err;
      haptic.note('error');
      if (sec === S.section) { renderAction(); renderInputState(); updateMainButton(); updateBackButton(); announce(errCopy(err).title); }
      if (err.code === 'rate_limited') loadMe();
    });
  }

  function schedulePoll(sec, delay) {
    var st = S.sec[sec];
    clearTimeout(st.timer);
    st.timer = setTimeout(function () { pollOnce(sec); }, delay);
  }

  function pollOnce(sec) {
    var st = S.sec[sec];
    if (st.phase !== 'job' || !st.job) return;
    var id = st.job.id, seq = st.seq;
    api('GET', '/jobs/' + encodeURIComponent(id), null, 10000).then(function (data) {
      if (seq !== st.seq || st.phase !== 'job') return;
      var prevStatus = st.job.status;
      var j = sanitizeJob(data.job);
      j.format = j.format || st.job.format;
      st.job = j; st.netFails = 0;
      if (j.status === 'done') { st.phase = 'done'; onJobDone(sec); return; }
      if (j.status === 'error') {
        st.phase = 'jobError'; st.error = j.error ? new ApiError(j.error.code, j.error.message) : new ApiError('internal');
        haptic.note('error');
        refreshAfterJob(sec);
        if (sec === S.section) { renderWorkspace(false); renderInputState(); updateMainButton(); updateBackButton(); announce(errCopy(st.error).title); }
        else toast(SECTIONS[sec].name + ': yuklashda xato', 'error');
        return;
      }
      if (prevStatus !== j.status) { haptic.sel(); if (sec === S.section && STATUS[j.status]) announce(STATUS[j.status].title); }
      updateProgress(sec);
      schedulePoll(sec, POLL_MS);
    }, function (err) {
      if (seq !== st.seq || st.phase !== 'job') return;
      if (err.code === 'unauthorized') return;
      if (err.code === 'not_found') {
        st.phase = 'jobError'; st.error = new ApiError('internal', 'Yuklash jarayoni topilmadi.');
        if (sec === S.section) { renderWorkspace(false); renderInputState(); updateMainButton(); updateBackButton(); }
        return;
      }
      st.netFails++;
      updateProgress(sec);
      schedulePoll(sec, Math.min(POLL_MS * Math.pow(2, st.netFails), 8000));
    });
  }

  function onJobDone(sec) {
    var st = S.sec[sec];
    haptic.note('success');
    refreshAfterJob(sec);
    if (sec === S.section) {
      renderWorkspace(false); renderInputState(); updateMainButton(); updateBackButton();
      announce('Chatga yuborildi');
      setTimeout(revealWorkspace, 60);
    } else {
      toast('Chatga yuborildi: ' + (st.media ? st.media.title : ''));
    }
  }
  function refreshAfterJob(sec) {
    loadHistory(sec);
    loadMe();
  }

  /* ======================================================================
   * Rendering — workspace
   * ==================================================================== */
  function renderNotice() {
    var st = cur();
    el.notice.replaceChildren();
    if (!st.notice) return;
    el.notice.appendChild(h('div', { class: 'notice', role: 'status' },
      icon('swap'),
      h('p', { class: 'notice-text', text: st.notice.text }),
      h('button', {
        type: 'button', class: 'icon-btn', 'aria-label': 'Xabarni yopish',
        onclick: function () { st.notice = null; renderNotice(); }
      }, icon('x'))
    ));
  }

  function revealWorkspace() {
    var card = el.ws.firstElementChild;
    if (!card || !card.getBoundingClientRect) return;
    // If a section-switch notice sits above the card, bring it into view too.
    var target = el.notice.firstElementChild || card;
    var r = target.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    if (r.top >= 0 && r.top < vh * 0.45) return;
    var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    safe(function () { window.scrollTo({ top: Math.max(0, window.scrollY + r.top - 12), behavior: reduce ? 'auto' : 'smooth' }); });
  }

  function renderWorkspace(animate) {
    var st = cur();
    st.refs = null;
    var node;
    switch (st.phase) {
      case 'idle': node = renderGuide(); break;
      case 'probing': node = renderSkeleton(st.link); break;
      case 'probeError': node = renderProbeError(st); break;
      default: node = renderMediaCard(st);
    }
    if (animate) node.classList.add('enter');
    el.ws.replaceChildren(node);
  }

  function renderGuide() {
    var meta = SECTIONS[S.section];
    var icons = ['link', 'paste', S.section === 'videos' ? 'monitor' : (S.section === 'shorts' ? 'phone' : 'send')];
    return h('div', { class: 'card guide', role: 'list', 'aria-label': 'Qanday ishlaydi' },
      meta.guide.map(function (g, i) {
        return h('div', { class: 'guide-step', role: 'listitem' },
          h('span', { class: 'guide-num', 'aria-hidden': 'true' }, icon(icons[i])),
          h('div', null, h('p', { class: 'guide-title', text: (i + 1) + '. ' + g[0] }), h('p', { class: 'guide-text', text: g[1] }))
        );
      })
    );
  }

  function guessOrientation(link) {
    if (!link) return 'horizontal';
    if (link.kind === 'post') return 'square';
    if (link.kind === 'reel' || link.kind === 'short') return 'vertical';
    return 'horizontal';
  }

  function renderSkeleton(link) {
    var o = guessOrientation(link);
    var frameStyle = o === 'vertical' ? { aspectRatio: '9 / 16' } : o === 'square' ? { aspectRatio: '1 / 1' } : null;
    return h('div', { class: 'card media-card', 'aria-busy': 'true', 'aria-label': 'Yuklanmoqda' },
      h('div', { class: 'skel-stage is-' + o }, h('div', { class: 'skel skel-frame', style: frameStyle })),
      h('div', { class: 'skel-lines' },
        h('div', { class: 'skel skel-line', style: { width: '88%', height: '15px' } }),
        h('div', { class: 'skel skel-line', style: { width: '62%', height: '15px' } }),
        h('div', { class: 'skel skel-line', style: { width: '40%', marginTop: '4px' } })
      ),
      h('div', { class: 'skel-chips' }, h('div', { class: 'skel skel-chip' }), h('div', { class: 'skel skel-chip' }), h('div', { class: 'skel skel-chip' })),
      h('p', { class: 'probe-status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), h('span', { text: 'Havola tekshirilmoqda…' }))
    );
  }

  var RETRYABLE = { internal: 1, network: 1, timeout: 1, rate_limited: 1, busy: 1 };
  function isRetryable(code) { return !!RETRYABLE[code]; }

  function renderProbeError(st) {
    var c = errCopy(st.error);
    var ic = c.code === 'network' || c.code === 'timeout' ? 'wifi-off' : c.code === 'private' ? 'lock' : 'alert';
    var actions = [];
    var retry = isRetryable(c.code);
    if (retry) {
      actions.push(h('button', { type: 'button', class: 'btn btn-primary', onclick: function () { check(); } }, icon('refresh'), h('span', { text: 'Qayta urinish' })));
    }
    actions.push(h('button', {
      type: 'button', class: 'btn ' + (retry ? 'btn-ghost' : 'btn-primary'),
      onclick: function () { el.input.value = ''; st.url = ''; resetSection(S.section); el.input.focus(); }
    }, retry ? null : icon('link'), h('span', { text: 'Boshqa havola' })));
    return h('div', { class: 'card state is-error', role: 'alert' },
      h('span', { class: 'state-ic' }, icon(ic)),
      h('p', { class: 'state-title', text: c.title }),
      h('p', { class: 'state-text', text: c.text }),
      actions
    );
  }

  function renderStage(m, done) {
    var o = m.orientation || 'horizontal';
    var stage = h('div', { class: 'stage is-' + o });
    var frame = h('div', { class: 'frame' });
    if (o !== 'horizontal') {
      var ratio = m.width && m.height ? m.width + ' / ' + m.height : (o === 'square' ? '1 / 1' : '9 / 16');
      frame.style.aspectRatio = ratio;
    } else if (m.width && m.height) {
      var r = m.width / m.height;
      if (r > 1.2 && r < 2.6) stage.style.aspectRatio = m.width + ' / ' + m.height;
    }
    var ph = function () {
      return h('div', { class: 'frame-ph' }, icon(m.platform === 'youtube' ? 'play' : 'image'));
    };
    var main = img(m.thumbnail, null, function (node) { node.replaceWith(ph()); if (bd) bd.remove(); });
    var bd = o !== 'horizontal' ? img(m.thumbnail, 'stage-backdrop', function (node) { node.remove(); }) : null;
    if (bd) { bd.setAttribute('aria-hidden', 'true'); stage.appendChild(bd); }
    frame.appendChild(main || ph());
    stage.appendChild(frame);

    var kind = m.kind === 'post' && m.items_count > 1 ? 'Karusel' : KIND_LABEL[m.kind];
    stage.appendChild(h('span', { class: 'badge badge-tl badge-kind' }, icon(m.platform === 'youtube' ? 'youtube-mono' : 'instagram-mono'), kind));
    if (m.items_count > 1) {
      stage.appendChild(h('span', { class: 'badge badge-tr', 'aria-label': m.items_count + ' ta media' }, icon('layers'), m.items_count + ' ta'));
    }
    var asp = aspectLabel(m.width, m.height) || (o === 'vertical' ? '9:16' : o === 'square' ? '1:1' : '16:9');
    stage.appendChild(h('span', { class: 'badge badge-bl', title: 'Asl format saqlanadi' }, asp));
    var d = fmtDur(m.duration);
    if (d) stage.appendChild(h('span', { class: 'badge badge-br', 'aria-label': 'Davomiyligi ' + d }, d));
    if (done) stage.appendChild(h('div', { class: 'done-overlay', 'aria-hidden': 'true' }, h('span', null, icon('check'))));
    return stage;
  }

  function renderMediaCard(st) {
    var m = st.media;
    var meta = [];
    if (m.author) meta.push(h('span', { class: 'media-author' }, icon(m.platform === 'youtube' ? 'youtube-mono' : 'instagram-mono'), (m.platform === 'instagram' && m.author.charAt(0) !== '@' ? '@' : '') + m.author));
    if (m.width && m.height) meta.push(h('span', null, icon(m.orientation === 'vertical' ? 'phone' : m.orientation === 'square' ? 'image' : 'monitor'), m.width + '×' + m.height));

    var action = h('div', { class: 'action' });
    var card = h('article', { class: 'card media-card', 'aria-label': m.title },
      renderStage(m, st.phase === 'done'),
      h('div', { class: 'media-body' },
        h('h2', { class: 'media-title', text: m.title }),
        meta.length ? h('div', { class: 'media-meta' }, meta) : null,
        h('div', { class: 'divider', 'aria-hidden': 'true' }),
        action
      )
    );
    st.refs = { action: action, card: card };
    fillAction(st, action);
    return card;
  }

  /** Re-render only the action area (keeps thumbnail images untouched). */
  function renderAction() {
    var st = cur();
    if (!st.refs || !st.refs.action || !st.media) { renderWorkspace(false); return; }
    fillAction(st, st.refs.action);
  }

  function fillAction(st, root) {
    root.replaceChildren();
    if (st.phase === 'preview' || st.phase === 'starting') root.appendChild(renderChooser(st));
    else if (st.phase === 'job') root.appendChild(renderProgress(st));
    else if (st.phase === 'done') root.appendChild(renderSuccess(st));
    else if (st.phase === 'jobError') root.appendChild(renderJobError(st));
  }

  function maxUploadMb() {
    return (S.me.data && S.me.data.limits && S.me.data.limits.max_upload_mb) || 50;
  }

  function renderSingleFormat(st) {
    var m = st.media, f = m.formats[0];
    var size = fmtSize(f.size);
    var text = m.kind === 'post' && m.items_count > 1
      ? m.items_count + ' ta media asl sifatda, albom ko‘rinishida yuboriladi'
      : (f.id === 'audio' ? 'MP3 audio yuboriladi' : 'Asl sifat va formatda yuboriladi');
    var root = h('div', null,
      h('p', { class: 'single-fmt' + (f.fits ? '' : ' is-blocked') },
        icon(f.fits ? (m.items_count > 1 ? 'layers' : 'sparkle') : 'lock'),
        h('span', { class: 'single-fmt-text', text: f.fits ? text : 'Fayl Telegram limitidan (' + maxUploadMb() + ' MB) katta' }),
        size ? h('span', { class: 'single-fmt-size', text: '~' + size }) : null
      )
    );
    appendDlArea(st, root);
    return root;
  }

  function appendDlArea(st, root) {
    var dl = h('div', { class: 'dl-area' });
    if (st.actionError) dl.appendChild(renderAlert(st.actionError));
    // Inside Telegram the MainButton is the download action; the in-page button is hidden (.tg-dup).
    var btn = h('button', { type: 'button', class: 'btn btn-primary btn-lg btn-block tg-dup', id: 'dlBtn', onclick: function () { startDownload(); } });
    dl.appendChild(btn);
    root.appendChild(dl);
    st.refs.dlBtn = btn;
    updateDlButton(st);
  }

  function renderChooser(st) {
    var m = st.media;
    if (m.formats.length === 1) return renderSingleFormat(st);
    var starting = st.phase === 'starting';
    var anyBlocked = m.formats.some(function (f) { return !f.fits; });
    var n = m.formats.length;
    var group = h('fieldset', { class: 'chips' + (n === 2 || n === 4 ? ' is-cols-2' : ''), 'aria-describedby': anyBlocked ? 'fitsNote' : null });
    group.appendChild(h('legend', { class: 'sr-only', text: 'Sifatni tanlang' }));
    m.formats.forEach(function (f) {
      var size = fmtSize(f.size);
      var tag = fmtTag(f, m.formats);
      var input = h('input', {
        type: 'radio', name: 'fmt-' + S.section, value: f.id, checked: st.fmt === f.id, disabled: !f.fits || starting,
        'aria-label': fmtName(f) + (tag ? ' (' + tag + ')' : '') + (size ? ', taxminan ' + size : '') + (f.fits ? '' : ', Telegram limitiga sig‘maydi')
      });
      input.addEventListener('change', function () {
        if (!input.checked) return;
        st.fmt = f.id; st.actionError = null;
        haptic.sel();
        updateDlButton(st);
        updateMainButton();
        var al = root2.querySelector('.alert'); if (al) al.remove();
        renderInputState();
      });
      group.appendChild(h('label', { class: 'chip' + (f.id === 'audio' ? ' is-audio' : '') },
        input,
        h('span', { class: 'chip-face', 'aria-hidden': 'true' },
          h('span', { class: 'chip-top' }, f.id === 'audio' ? icon('music') : null, fmtName(f), tag ? h('span', { class: 'chip-tag', text: tag }) : null),
          f.fits
            ? h('span', { class: 'chip-size', text: size ? '~' + size : (f.id === 'auto' ? 'Asl o‘lcham' : '—') })
            : h('span', { class: 'chip-size' }, icon('lock'), 'Sig‘maydi'),
          h('span', { class: 'chip-check' }, icon('check'))
        )
      ));
    });

    var root2 = h('div', null,
      h('div', { class: 'label-row' },
        h('span', { class: 'label', id: 'fmtLabel', text: 'Sifat' }),
        h('span', { class: 'label-aside', text: m.platform === 'youtube' && m.section === 'videos' ? 'Hajm taxminiy' : 'Asl format saqlanadi' })
      ),
      group,
      anyBlocked ? h('p', { class: 'fits-note', id: 'fitsNote' }, icon('info'), h('span', { text: '“Sig‘maydi” — fayl Telegram limitidan (' + maxUploadMb() + ' MB) katta, shuning uchun o‘chirilgan.' })) : null
    );

    appendDlArea(st, root2);
    return root2;
  }

  function selectedFormat(st) {
    if (!st.media) return null;
    return st.media.formats.filter(function (f) { return f.id === st.fmt; })[0] || null;
  }

  function updateDlButton(st) {
    var btn = st.refs && st.refs.dlBtn;
    if (!btn) return;
    var f = selectedFormat(st);
    var starting = st.phase === 'starting';
    btn.disabled = !f || starting;
    btn.replaceChildren();
    if (starting) {
      btn.appendChild(h('span', { class: 'spinner', 'aria-hidden': 'true' }));
      btn.appendChild(h('span', { text: 'Boshlanmoqda…' }));
      btn.setAttribute('aria-busy', 'true');
      return;
    }
    btn.removeAttribute('aria-busy');
    if (!f) { btn.appendChild(h('span', { text: 'Mos sifat yo‘q' })); return; }
    btn.appendChild(icon(f.id === 'audio' ? 'music' : 'download'));
    btn.appendChild(h('span', { text: f.id === 'audio' ? 'MP3 yuklab olish' : 'Yuklab olish' }));
    var size = fmtSize(f.size);
    btn.appendChild(h('span', { class: 'btn-sep', 'aria-hidden': 'true' }));
    btn.appendChild(h('span', { class: 'btn-meta', text: fmtName(f) + (size ? ' · ' + size : '') }));
  }

  function renderAlert(err) {
    var c = errCopy(err);
    var warn = c.code === 'busy' || c.code === 'rate_limited';
    return h('div', { class: 'alert' + (warn ? ' is-warn' : ''), role: 'alert' },
      icon(warn ? 'clock' : 'alert'),
      h('div', null, h('p', { class: 'alert-title', text: c.title }), h('p', { class: 'alert-text', text: c.text }))
    );
  }

  function renderProgress(st) {
    var steps = h('ol', { class: 'steps', 'aria-hidden': 'true' });
    var stepEls = STEP_META.map(function (s) {
      var li = h('li', { class: 'step' }, h('span', { class: 'step-dot' }, icon(s[1])), h('span', { class: 'step-label', text: s[0] }));
      steps.appendChild(li);
      return li;
    });
    var title = h('p', { class: 'prog-title' });
    var sub = h('p', { class: 'prog-sub' });
    var pct = h('span', { class: 'prog-pct', 'aria-hidden': 'true' });
    var fill = h('span', { class: 'bar-fill' });
    var bar = h('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': 'Yuklash jarayoni' }, fill);
    var note = h('p', { class: 'prog-note' });
    st.refs.prog = { steps: stepEls, title: title, sub: sub, pct: pct, bar: bar, fill: fill, note: note };
    var box = h('div', { class: 'progress-box' },
      steps,
      h('div', { class: 'prog-head' }, h('div', null, title, sub), pct),
      bar,
      note
    );
    paintProgress(st);
    return box;
  }

  function progressModel(job) {
    var s = job.status;
    var info = STATUS[s] || STATUS.queued;
    var determinate = s === 'downloading';
    return { info: info, idx: Math.max(0, STEP_ORDER.indexOf(s)), determinate: determinate, pct: determinate ? job.progress : null };
  }

  function paintProgress(st) {
    var r = st.refs && st.refs.prog;
    if (!r || !st.job) return;
    var pm = progressModel(st.job);
    r.steps.forEach(function (li, i) {
      li.classList.toggle('is-done', i < pm.idx);
      li.classList.toggle('is-active', i === pm.idx);
      setIcon(li.querySelector('svg'), i < pm.idx ? 'check' : STEP_META[i][1]);
    });
    r.title.textContent = pm.info.title;
    var f = st.media && st.media.formats.filter(function (x) { return x.id === st.job.format; })[0];
    r.sub.textContent = pm.info.sub + (st.job.format ? ' · ' + (f ? fmtName(f) : fmtShort(st.job.format)) : '');
    r.pct.textContent = pm.determinate ? pm.pct + '%' : '';
    r.bar.classList.toggle('is-indeterminate', !pm.determinate);
    r.fill.style.width = (pm.determinate ? pm.pct : 0) + '%';
    if (pm.determinate) { r.bar.setAttribute('aria-valuenow', String(pm.pct)); }
    else r.bar.removeAttribute('aria-valuenow');
    r.bar.setAttribute('aria-valuetext', pm.info.title + (pm.determinate ? ' ' + pm.pct + '%' : ''));
    r.note.replaceChildren();
    if (st.netFails > 0) {
      r.note.className = 'prog-note is-warn';
      r.note.append(icon('wifi-off'), h('span', { text: 'Aloqa uzildi, qayta ulanmoqda…' }));
    } else {
      r.note.className = 'prog-note';
      r.note.append(icon('info'), h('span', { text: 'Ilovani yopishingiz mumkin — fayl baribir chatga yuboriladi.' }));
    }
  }

  function updateProgress(sec) {
    if (sec === S.section) { paintProgress(S.sec[sec]); updateMainButton(); }
  }

  function renderSuccess(st) {
    var m = st.media;
    // Describe what was ACTUALLY delivered: the backend may downgrade auto/1080 to fit the limit.
    var job = st.job || {};
    var fmtId = job.used_format || job.format || st.fmt;
    var text;
    if (m.kind === 'post' && m.items_count > 1) text = 'Bot ' + m.items_count + ' ta mediani albom ko‘rinishida shaxsiy chatingizga yubordi.';
    else if (fmtId === 'audio') text = 'Bot MP3 audioni shaxsiy chatingizga yubordi.';
    else if (job.note) text = 'Bot videoni shaxsiy chatingizga yubordi.'; // the note already names the quality
    else if (!fmtId || fmtId === 'auto') text = 'Bot videoni asl sifatda shaxsiy chatingizga yubordi.';
    else text = 'Bot videoni ' + fmtShort(fmtId) + ' sifatda shaxsiy chatingizga yubordi.';
    // Inside Telegram "Chatga o‘tish" lives on the MainButton, so the in-page copy is hidden (.tg-dup).
    var actions = h('div', { class: 'btn-row' + (IN_TG ? ' is-stack' : '') },
      h('button', { type: 'button', class: 'btn btn-primary tg-dup', onclick: goToChat }, icon('arrow-out'), h('span', { text: 'Chatga o‘tish' })),
      h('button', { type: 'button', class: 'btn btn-secondary', onclick: again }, icon('link'), h('span', { text: 'Yangi havola' }))
    );
    return h('div', { class: 'success', role: 'status' },
      h('p', { class: 'success-title', text: '✅ Chatga yuborildi' }),
      h('p', { class: 'success-text', text: text }),
      job.note ? h('p', { class: 'success-note' }, icon('info'), h('span', { text: job.note })) : null,
      actions
    );
  }

  /** Primary recovery for a failed job (shared by the in-page button and the MainButton). */
  function jobErrorAction(st) {
    var c = errCopy(st.error);
    if (isRetryable(c.code)) return { text: 'Qayta urinish', icon: 'refresh', run: function () { st.phase = 'preview'; startDownload(); } };
    var hasAudio = st.media && st.media.formats.some(function (f) { return f.id === 'audio' && f.fits; }) && st.fmt !== 'audio';
    if (c.code === 'too_large' && hasAudio) return { text: 'MP3 olish', icon: 'music', run: function () { st.fmt = 'audio'; st.phase = 'preview'; startDownload(); } };
    return null;
  }

  function renderJobError(st) {
    var row = h('div', { class: 'btn-row' });
    var pa = jobErrorAction(st);
    if (pa) row.appendChild(h('button', { type: 'button', class: 'btn btn-primary', onclick: pa.run }, icon(pa.icon), h('span', { text: pa.text })));
    row.appendChild(h('button', { type: 'button', class: 'btn btn-secondary', onclick: function () { st.phase = 'preview'; st.actionError = null; renderAction(); renderInputState(); updateMainButton(); updateBackButton(); } }, h('span', { text: 'Boshqa sifat' })));
    if (row.children.length === 1) row.classList.add('is-stack');
    return h('div', null, renderAlert(st.error), row);
  }

  function goToChat() {
    haptic.tap('light');
    if (IN_TG) safe(function () { TG.close(); });
    else toast('Telegram ichida chat ochiladi', 'info');
  }
  function again() {
    haptic.tap('light');
    var st = cur();
    st.url = ''; el.input.value = '';
    resetSection(S.section);
    renderInputState();
    el.input.focus({ preventScroll: true });
    safe(function () { window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); });
  }

  /* ======================================================================
   * MainButton orchestration
   * ==================================================================== */
  function updateMainButton() {
    if (!IN_TG) return;
    if (S.sheetOpen) { setMainButton(null); return; }
    var st = cur();
    switch (st.phase) {
      case 'idle': {
        var c = classify(el.input.value);
        setMainButton(c.ok ? { text: 'Tekshirish' } : null);
        break;
      }
      case 'probing': setMainButton({ text: 'Tekshirilmoqda…', active: false, progress: true }); break;
      case 'probeError': setMainButton(null); break;
      case 'preview': {
        var f = selectedFormat(st);
        if (!f) { setMainButton(null); break; }
        var size = fmtSize(f.size);
        setMainButton({ text: (f.id === 'audio' ? 'MP3 yuklab olish' : 'Yuklab olish') + ' · ' + fmtName(f) + (size ? ' (' + size + ')' : '') });
        break;
      }
      case 'starting': setMainButton({ text: 'Boshlanmoqda…', active: false, progress: true }); break;
      case 'job': {
        var pm = progressModel(st.job);
        var t = pm.info.emoji + ' ' + pm.info.title + (pm.determinate ? ' ' + pm.pct + '%' : '…');
        setMainButton({ text: t, active: false });
        break;
      }
      case 'done': setMainButton({ text: 'Chatga o‘tish' }); break;
      case 'jobError': { var ja = jobErrorAction(st); setMainButton(ja ? { text: ja.text } : null); break; }
    }
  }

  function onMainButton() {
    var st = cur();
    if (S.sheetOpen) return;
    if (st.phase === 'idle') check();
    else if (st.phase === 'preview') startDownload();
    else if (st.phase === 'done') goToChat();
    else if (st.phase === 'jobError') { var ja = jobErrorAction(st); if (ja) ja.run(); }
  }

  function onBack() {
    if (S.sheetOpen) { closeSheet(); return; }
    var st = cur();
    if (st.phase === 'preview' || st.phase === 'probeError' || st.phase === 'jobError') { haptic.tap('light'); resetSection(S.section); }
    else if (st.phase === 'done') again();
  }

  /* ======================================================================
   * History
   * ==================================================================== */
  function ensureHistory(sec) {
    var hs = S.hist[sec];
    if (!hs.items && !hs.loading && !hs.error) loadHistory(sec);
  }
  function loadHistory(sec) {
    var hs = S.hist[sec];
    if (hs.loading) return;
    hs.loading = true;
    if (sec === S.section) renderHistory();
    api('GET', '/history?section=' + encodeURIComponent(sec) + '&limit=20', null, 12000).then(function (data) {
      hs.loading = false; hs.error = null;
      hs.items = Array.isArray(data.items) ? data.items.slice(0, 50).map(function (it) {
        it = it && typeof it === 'object' ? it : {};
        return {
          id: str(it.id, 100), section: SECTIONS[it.section] ? it.section : sec, kind: KIND_LABEL[it.kind] ? it.kind : null,
          title: str(it.title, 300) || 'Nomsiz', thumbnail: safeImgUrl(it.thumbnail), url: str(it.url, 300),
          format: str(it.format, 20), status: str(it.status, 20), created_at: str(it.created_at, 40)
        };
      }) : [];
      if (sec === S.section) renderHistory();
    }, function (err) {
      hs.loading = false; hs.error = err;
      if (sec === S.section) renderHistory();
    });
  }

  function renderHistory() {
    var sec = S.section;
    var hs = S.hist[sec];
    var list = el.histList;
    el.refresh.classList.toggle('is-spinning', hs.loading);
    el.refresh.disabled = hs.loading;
    list.setAttribute('aria-busy', String(hs.loading));
    var count = hs.items ? hs.items.length : 0;
    el.histSub.textContent = hs.items && count ? count + ' ta so‘nggi yuklama' : 'So‘nggi yuklamalaringiz';

    if (!hs.items && (hs.loading || !hs.error)) {
      var sk = h('div', { class: 'card hist-list', 'aria-label': 'Tarix yuklanmoqda' });
      for (var i = 0; i < 3; i++) {
        sk.appendChild(h('div', { class: 'skel-row', 'aria-hidden': 'true' },
          h('div', { class: 'skel skel-thumb' }),
          h('div', { class: 'skel-lines' }, h('div', { class: 'skel skel-line', style: { width: (70 - i * 12) + '%' } }), h('div', { class: 'skel skel-line', style: { width: '38%', height: '10px' } }))
        ));
      }
      list.replaceChildren(sk);
      return;
    }
    if (!hs.items && hs.error) {
      var c = errCopy(hs.error);
      list.replaceChildren(h('div', { class: 'card state is-error is-compact', role: 'alert' },
        h('span', { class: 'state-ic' }, icon(c.code === 'network' || c.code === 'timeout' ? 'wifi-off' : 'alert')),
        h('p', { class: 'state-title', text: 'Tarixni yuklab bo‘lmadi' }),
        h('p', { class: 'state-text', text: c.text }),
        c.code !== 'unauthorized' ? h('button', { type: 'button', class: 'btn btn-secondary', onclick: function () { loadHistory(sec); } }, icon('refresh'), h('span', { text: 'Qayta urinish' })) : null
      ));
      return;
    }
    if (!hs.items.length) {
      list.replaceChildren(h('div', { class: 'card state is-compact' },
        h('span', { class: 'state-ic' }, icon('history')),
        h('p', { class: 'state-title', text: 'Hali hech narsa yuklanmagan' }),
        h('p', { class: 'state-text', text: 'Birinchi havolani yuqoriga joylang — yuklamalar shu yerda ko‘rinadi.' })
      ));
      return;
    }
    var ul = h('ul', { class: 'card hist-list' });
    hs.items.forEach(function (it) {
      var o = it.kind === 'reel' || it.kind === 'short' ? 'vertical' : it.kind === 'video' ? 'horizontal' : 'square';
      var thumb = h('span', { class: 'hist-thumb is-' + o, 'aria-hidden': 'true' });
      var phIcon = function () { return icon(it.format === 'audio' ? 'music' : sec === 'instagram' ? 'image' : 'play'); };
      var im = img(it.thumbnail, null, function (node) { node.replaceWith(phIcon()); });
      thumb.appendChild(im || phIcon());
      var pill;
      if (it.status === 'done') pill = h('span', { class: 'pill is-done' }, icon('check'), 'Yuborildi');
      else if (it.status === 'error') pill = h('span', { class: 'pill is-error' }, icon('alert'), 'Xato');
      else pill = h('span', { class: 'pill is-active' }, icon('clock'), 'Jarayonda');
      var meta = h('p', { class: 'hist-meta' });
      if (it.format) { meta.appendChild(h('span', { text: fmtShort(it.format) })); meta.appendChild(h('span', { class: 'dot', 'aria-hidden': 'true' })); }
      meta.appendChild(h('span', { text: relTime(it.created_at) }));
      var canOpen = classify(it.url).ok;
      ul.appendChild(h('li', null, h('button', {
        type: 'button', class: 'hist-item', disabled: !canOpen,
        'aria-label': it.title + '. ' + (it.status === 'done' ? 'Yuborildi' : it.status === 'error' ? 'Xato' : 'Jarayonda') + '. Qayta ochish',
        onclick: function () { openFromHistory(it); }
      },
        h('span', { class: 'hist-box' }, thumb),
        h('span', { class: 'hist-main' }, h('p', { class: 'hist-title', text: it.title }), meta),
        pill
      )));
    });
    list.replaceChildren(ul);
  }

  function openFromHistory(it) {
    var c = classify(it.url);
    if (!c.ok) return;
    var st = S.sec[c.section];
    if (st.phase === 'job' || st.phase === 'starting') { toast('Avvalgi yuklash hali tugamagan', 'error'); return; }
    haptic.tap('light');
    st.url = it.url; st.notice = null;
    if (c.section !== S.section) setSection(c.section);
    el.input.value = it.url;
    safe(function () { window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); });
    check({ blur: false });
  }

  /* ======================================================================
   * Profile / stats sheet
   * ==================================================================== */
  function loadMe() {
    if (S.me.loading) return;
    S.me.loading = true;
    if (S.sheetOpen) renderSheet();
    api('GET', '/me', null, 10000).then(function (data) {
      S.me.loading = false; S.me.error = null;
      var u = data.user || {}, s = data.stats || {}, l = data.limits || {};
      S.me.data = {
        user: { id: int(u.id), first_name: str(u.first_name, 64), username: str(u.username, 64) },
        stats: { total: int(s.total) || 0, instagram: int(s.instagram) || 0, shorts: int(s.shorts) || 0, videos: int(s.videos) || 0 },
        limits: { max_upload_mb: int(l.max_upload_mb), max_duration_min: int(l.max_duration_min), hourly_limit: int(l.hourly_limit), hourly_used: int(l.hourly_used) || 0 }
      };
      renderAvatar();
      if (S.sheetOpen) renderSheet();
    }, function (err) {
      S.me.loading = false; S.me.error = err;
      if (S.sheetOpen) renderSheet();
    });
  }

  function userInfo() {
    var tu = IN_TG && TG.initDataUnsafe && TG.initDataUnsafe.user ? TG.initDataUnsafe.user : null;
    var mu = S.me.data && S.me.data.user;
    return {
      name: (mu && mu.first_name) || (tu && str(tu.first_name, 64)) || '',
      username: (mu && mu.username) || (tu && str(tu.username, 64)) || '',
      photo: tu ? safeImgUrl(tu.photo_url) : null
    };
  }
  function initialOf(name) {
    var ch = (name || '').trim().charAt(0);
    return ch ? ch.toUpperCase() : '';
  }
  function avatarNode(u) {
    var p = u.photo ? img(u.photo, null, function (node) { node.replaceWith(document.createTextNode(initialOf(u.name) || '?')); }) : null;
    if (p) return p;
    var ini = initialOf(u.name);
    return ini ? document.createTextNode(ini) : icon('chart');
  }
  function renderAvatar() {
    el.avatar.replaceChildren(avatarNode(userInfo()));
  }

  var lastFocus = null;
  function openSheet() {
    if (S.sheetOpen) return;
    S.sheetOpen = true;
    lastFocus = document.activeElement;
    haptic.tap('light');
    el.sheet.hidden = false;
    el.sheet.classList.remove('is-closing');
    el.app.inert = true;
    el.app.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = 'hidden';
    renderSheet();
    loadMe();
    setTimeout(function () { el.sheetPanel.focus({ preventScroll: true }); }, 30);
    updateMainButton();
    updateBackButton();
  }
  function closeSheet() {
    if (!S.sheetOpen) return;
    S.sheetOpen = false;
    el.app.inert = false;
    el.app.removeAttribute('aria-hidden');
    document.body.style.overflow = '';
    var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.sheet.classList.add('is-closing');
    setTimeout(function () { if (!S.sheetOpen) { el.sheet.hidden = true; el.sheet.classList.remove('is-closing'); } }, reduce ? 0 : 210);
    if (lastFocus && lastFocus.focus) safe(function () { lastFocus.focus({ preventScroll: true }); });
    updateMainButton();
    updateBackButton();
  }

  function renderSheet() {
    var body = el.sheetBody;
    var md = S.me.data;
    if (!md && S.me.error) {
      var c = errCopy(S.me.error);
      body.replaceChildren(h('div', { class: 'card state is-error', role: 'alert' },
        h('span', { class: 'state-ic' }, icon(c.code === 'network' ? 'wifi-off' : 'alert')),
        h('p', { class: 'state-title', text: 'Statistikani yuklab bo‘lmadi' }),
        h('p', { class: 'state-text', text: c.text }),
        c.code !== 'unauthorized' ? h('button', { type: 'button', class: 'btn btn-secondary', onclick: loadMe }, icon('refresh'), h('span', { text: 'Qayta urinish' })) : null
      ));
      return;
    }
    if (!md) {
      body.replaceChildren(
        h('div', { class: 'card profile', 'aria-hidden': 'true' }, h('div', { class: 'skel', style: { width: '54px', height: '54px', borderRadius: '50%' } }),
          h('div', { class: 'skel-lines', style: { flex: '1', padding: '0' } }, h('div', { class: 'skel skel-line', style: { width: '50%' } }), h('div', { class: 'skel skel-line', style: { width: '30%' } }))),
        h('div', { class: 'card', 'aria-hidden': 'true' }, h('div', { class: 'skel', style: { width: '40%', height: '36px', marginBottom: '14px' } }), h('div', { class: 'skel', style: { height: '10px' } })),
        h('div', { class: 'card', 'aria-hidden': 'true' }, h('div', { class: 'skel', style: { height: '64px' } })),
        h('p', { class: 'sr-only', text: 'Yuklanmoqda…' })
      );
      return;
    }
    var u = userInfo();
    var s = md.stats, l = md.limits;
    var parts = [['instagram', 'Instagram', 'c-ig'], ['shorts', 'Shorts', 'c-shorts'], ['videos', 'Videolar', 'c-videos']];
    var sum = s.instagram + s.shorts + s.videos;
    var stack = h('div', { class: 'stack-bar', role: 'img', 'aria-label': 'Instagram ' + s.instagram + ', Shorts ' + s.shorts + ', Videolar ' + s.videos });
    parts.forEach(function (p) { if (s[p[0]] > 0) stack.appendChild(h('span', { class: p[2], style: { flexGrow: String(s[p[0]]) } })); });

    var hourlyLimit = l.hourly_limit || 0;
    var used = Math.min(l.hourly_used, hourlyLimit || l.hourly_used);
    var ratio = hourlyLimit ? used / hourlyLimit : 0;
    var left = Math.max(0, hourlyLimit - used);
    var limitBar = h('div', {
      class: 'bar limit-bar' + (ratio >= 0.9 ? ' is-high' : ratio >= 0.7 ? ' is-mid' : ''),
      role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(hourlyLimit || 0), 'aria-valuenow': String(used),
      'aria-label': 'Soatlik limitdan foydalanish', 'aria-valuetext': used + ' / ' + hourlyLimit
    }, h('span', { class: 'bar-fill', style: { width: Math.round(ratio * 100) + '%' } }));

    body.replaceChildren(
      h('div', { class: 'card profile' },
        h('span', { class: 'avatar', 'aria-hidden': 'true' }, avatarNode(u)),
        h('div', { style: { minWidth: '0' } },
          h('p', { class: 'profile-name', text: u.name || 'Foydalanuvchi' }),
          u.username ? h('p', { class: 'profile-user', text: '@' + u.username }) : h('p', { class: 'profile-user', text: 'Telegram foydalanuvchisi' })
        )
      ),
      h('section', { class: 'card', 'aria-labelledby': 'statTitle' },
        h('h3', { class: 'card-title', id: 'statTitle', text: 'Yuklamalar' }),
        h('div', { class: 'total' },
          h('div', null, h('p', { class: 'total-num', text: String(s.total) }), h('p', { class: 'total-label', text: 'jami yuklab olingan' }))
        ),
        sum > 0 ? stack : null,
        h('div', { class: 'legend' }, parts.map(function (p) {
          var v = s[p[0]];
          return h('div', { class: 'legend-row' },
            h('span', { class: 'legend-sw ' + p[2], 'aria-hidden': 'true' }),
            h('span', { class: 'legend-name', text: p[1] }),
            h('span', { class: 'legend-val', text: String(v) }),
            h('span', { class: 'legend-pct', text: sum ? Math.round(v / sum * 100) + '%' : '—' })
          );
        }))
      ),
      h('section', { class: 'card', 'aria-labelledby': 'limTitle' },
        h('div', { class: 'limit-head' },
          h('h3', { class: 'limit-title', id: 'limTitle', text: 'Bu soatdagi yuklamalar' }),
          h('span', { class: 'limit-val' }, String(used), h('small', { text: ' / ' + (hourlyLimit || '∞') }))
        ),
        limitBar,
        h('p', { class: 'limit-note', text: !hourlyLimit ? 'Limit belgilanmagan' : left > 0 ? 'Yana ' + left + ' ta yuklash mumkin' : 'Limit tugadi — keyingi soatda yangilanadi' })
      ),
      h('section', { class: 'card', 'aria-labelledby': 'limsTitle' },
        h('h3', { class: 'card-title', id: 'limsTitle', text: 'Cheklovlar' }),
        h('ul', { class: 'kv' },
          kv('file', 'Maksimal fayl hajmi', l.max_upload_mb ? l.max_upload_mb + ' MB' : '—'),
          kv('clock', 'Maksimal davomiylik', l.max_duration_min ? l.max_duration_min + ' daqiqa' : '—'),
          kv('bolt', 'Soatlik limit', hourlyLimit ? hourlyLimit + ' ta' : '—')
        )
      ),
      h('p', { class: 'foot', text: 'Katta videolar avtomatik ravishda pastroq sifatga tushiriladi.' })
    );
  }
  function kv(ic, k, v) {
    return h('li', null, h('span', { class: 'kv-ic', 'aria-hidden': 'true' }, icon(ic)), h('span', { class: 'kv-k', text: k }), h('span', { class: 'kv-v', text: v }));
  }

  /* ======================================================================
   * Banners
   * ==================================================================== */
  function onForbidden() {
    if (S.forbidden) return;
    S.forbidden = true;
    renderBanners();
    haptic.note('error');
  }
  function onUnauthorized() {
    if (S.authFailed) return;
    S.authFailed = true;
    renderBanners();
    haptic.note('error');
  }
  function renderBanners() {
    var list = [];
    if (S.forbidden) {
      list.push(h('div', { class: 'banner is-error', role: 'alert' }, icon('lock'),
        h('div', null, h('p', { class: 'banner-title', text: '🔒 Ruxsat kerak' }),
          h('p', { class: 'banner-text', text: 'Bot hozir yopiq rejimda. Botga /start yozing va “🔑 Ruxsat so‘rash” tugmasini bosing — egasi ruxsat bergach ilova ochiladi.' }))));
    } else if (S.authFailed) {
      list.push(h('div', { class: 'banner is-error', role: 'alert' }, icon('lock'),
        h('div', null, h('p', { class: 'banner-title', text: 'Ilovani bot orqali qayta oching' }),
          h('p', { class: 'banner-text', text: 'Sessiya tasdiqlanmadi yoki muddati tugagan. Botdagi “📱 Mini App” tugmasini bosing.' }))));
    } else if (!MOCK && !INIT_DATA) {
      list.push(h('div', { class: 'banner is-info', role: 'status' }, icon('info'),
        h('div', null, h('p', { class: 'banner-title', text: 'Ilova Telegram tashqarisida ochildi' }),
          h('p', { class: 'banner-text', text: 'To‘liq ishlashi uchun uni bot orqali oching — fayllar Telegram chatingizga yuboriladi.' }),
          h('a', { href: '?mock=1', text: 'Demo rejimni ko‘rish →' }))));
    }
    if (S.offline) {
      list.push(h('div', { class: 'banner is-warn', role: 'status' }, icon('wifi-off'),
        h('div', null, h('p', { class: 'banner-title', text: 'Internet aloqasi yo‘q' }),
          h('p', { class: 'banner-text', text: 'Aloqa tiklanishi bilan davom etadi.' }))));
    }
    el.banners.replaceChildren.apply(el.banners, list);
  }

  /* ======================================================================
   * Mock backend (?mock=1)
   * ==================================================================== */
  var Mock = (function () {
    function svgUri(svg) { return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); }
    var THUMBS = {
      reel: svgUri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 160" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b1055"/><stop offset=".45" stop-color="#d4418e"/><stop offset=".75" stop-color="#ff9a5a"/><stop offset="1" stop-color="#ffd27f"/></linearGradient><radialGradient id="s" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fff6d5"/><stop offset="1" stop-color="#ffcf70" stop-opacity="0"/></radialGradient></defs><rect width="90" height="160" fill="url(#a)"/><circle cx="45" cy="56" r="30" fill="url(#s)"/><circle cx="45" cy="56" r="11" fill="#fff3c4"/><path d="M0 104h90v56H0z" fill="#3a1c4a"/><path d="M8 104V80h6l2-6 2 6h6v24zM30 104V70a15 15 0 0 1 30 0v34zM66 104V80h6l2-6 2 6h6v24z" fill="#4a2259"/><path d="M33 104V76a12 12 0 0 1 24 0v28z" fill="#2a1238"/><path d="M0 120h90v40H0z" fill="#25102f"/><path d="M0 121h90" stroke="#ffb27a" stroke-opacity=".35"/><g fill="#ffd9a8" fill-opacity=".5"><rect x="12" y="128" width="20" height="1.2" rx=".6"/><rect x="50" y="134" width="28" height="1.2" rx=".6"/><rect x="26" y="142" width="18" height="1.2" rx=".6"/></g></svg>'),
      post: svgUri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><linearGradient id="b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f6d365"/><stop offset="1" stop-color="#fda085"/></linearGradient></defs><rect width="100" height="100" fill="url(#b)"/><circle cx="50" cy="54" r="34" fill="#fff" fill-opacity=".92"/><circle cx="50" cy="54" r="27" fill="#f3e3c3"/><g fill="#e0a040"><circle cx="42" cy="48" r="4"/><circle cx="55" cy="45" r="3.5"/><circle cx="58" cy="58" r="4"/><circle cx="44" cy="61" r="3.6"/><circle cx="50" cy="53" r="3.2"/></g><g fill="#c0582d"><rect x="38" y="52" width="6" height="3" rx="1.5"/><rect x="52" y="62" width="7" height="3" rx="1.5"/><rect x="56" y="50" width="5" height="3" rx="1.5"/></g><g fill="#5e9b4a"><circle cx="47" cy="44" r="1.4"/><circle cx="61" cy="55" r="1.4"/><circle cx="41" cy="57" r="1.4"/></g><rect x="12" y="10" width="34" height="7" rx="3.5" fill="#fff" fill-opacity=".7"/></svg>'),
      short: svgUri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 160" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="n" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#050816"/><stop offset=".6" stop-color="#1b1f4b"/><stop offset="1" stop-color="#3b1d5e"/></linearGradient></defs><rect width="90" height="160" fill="url(#n)"/><g fill="#fff" fill-opacity=".7"><circle cx="12" cy="14" r=".6"/><circle cx="70" cy="22" r=".5"/><circle cx="40" cy="9" r=".4"/><circle cx="82" cy="40" r=".6"/><circle cx="25" cy="32" r=".4"/></g><circle cx="68" cy="30" r="7" fill="#fdf2c4" fill-opacity=".9"/><g fill="#0c0f2a"><rect x="0" y="92" width="14" height="68"/><rect x="14" y="78" width="12" height="82"/><rect x="26" y="60" width="10" height="100"/><rect x="36" y="84" width="16" height="76"/><rect x="52" y="52" width="11" height="108"/><path d="M57.5 38 63 52H52z"/><rect x="63" y="88" width="12" height="72"/><rect x="75" y="72" width="15" height="88"/></g><g fill="#ffcc66"><rect x="3" y="98" width="2" height="2"/><rect x="8" y="106" width="2" height="2"/><rect x="17" y="84" width="2" height="2"/><rect x="21" y="96" width="2" height="2"/><rect x="29" y="66" width="2" height="2"/><rect x="29" y="80" width="2" height="2"/><rect x="40" y="92" width="2" height="2"/><rect x="46" y="104" width="2" height="2"/><rect x="55" y="60" width="2" height="2"/><rect x="58" y="74" width="2" height="2"/><rect x="55" y="94" width="2" height="2"/><rect x="66" y="96" width="2" height="2"/><rect x="79" y="80" width="2" height="2"/><rect x="84" y="92" width="2" height="2"/></g><g fill="#7ad7ff" fill-opacity=".8"><rect x="31" y="72" width="2" height="2"/><rect x="69" y="104" width="2" height="2"/><rect x="11" y="116" width="2" height="2"/></g><rect y="140" width="90" height="20" fill="#e00020" fill-opacity=".18"/></svg>'),
      video: svgUri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><defs><linearGradient id="k" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8ec5fc"/><stop offset="1" stop-color="#e0c3fc"/></linearGradient><linearGradient id="l" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9fb8d9"/><stop offset="1" stop-color="#5f7fa8"/></linearGradient></defs><rect width="160" height="90" fill="url(#k)"/><circle cx="120" cy="24" r="9" fill="#fff" fill-opacity=".85"/><path d="M0 62 28 30l14 14 22-26 30 34 16-14 30 26 20-14v40H0z" fill="#6c86b3"/><path d="M28 30l6 7-4 1-4 4-4-3zM64 18l8 9-5 0-5 5-4-4z" fill="#fff"/><path d="M0 70 22 52l18 12 26-20 28 22 22-14 24 18 20-10v30H0z" fill="#3e5c87"/><path d="M0 74h160v16H0z" fill="url(#l)" fill-opacity=".9"/><path d="M8 80h40M70 84h50M112 78h30" stroke="#fff" stroke-opacity=".45" stroke-width=".8"/><g fill="#24395a"><path d="M14 74l4-10 4 10zM24 74l3-8 3 8zM132 74l4-11 4 11zM142 74l3-7 3 7z"/></g></svg>'),
      vertical2: svgUri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 160" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="q" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#11998e"/><stop offset="1" stop-color="#38ef7d"/></linearGradient></defs><rect width="90" height="160" fill="url(#q)"/><circle cx="45" cy="70" r="22" fill="#fff" fill-opacity=".2"/><path d="M38 60v20l17-10z" fill="#fff"/></svg>')
    };
    var MB = 1048576;
    var MEDIA = {
      reel: {
        platform: 'instagram', kind: 'reel', section: 'instagram', title: 'Samarqand tongi — Registon maydonida quyosh chiqishi 🌅',
        author: 'travel.uzbekistan', thumbnail: THUMBS.reel, duration: 28, width: 1080, height: 1920, orientation: 'vertical', items_count: 1,
        formats: [
          { id: 'auto', label: 'Avto', height: 1920, size: 14.2 * MB, fits: true },
          { id: 'audio', label: 'MP3', height: null, size: 0.7 * MB, fits: true }
        ]
      },
      post: {
        platform: 'instagram', kind: 'post', section: 'instagram', title: 'Toshkentdagi eng mazali osh markazlari — 5 ta tavsiya 🍚',
        author: 'toshkent.food', thumbnail: THUMBS.post, duration: null, width: 1080, height: 1080, orientation: 'square', items_count: 5,
        formats: [{ id: 'auto', label: 'Avto', height: 1080, size: 9.6 * MB, fits: true }]
      },
      short: {
        platform: 'youtube', kind: 'short', section: 'shorts', title: 'Toshkent tunda: 60 soniyada butun shahar ✨',
        author: 'Shahar Ritmi', thumbnail: THUMBS.short, duration: 58, width: 1080, height: 1920, orientation: 'vertical', items_count: 1,
        formats: [
          { id: 'auto', label: 'Avto', height: 1920, size: 24.8 * MB, fits: true },
          { id: '1080', label: '1080p', height: 1920, size: 24.8 * MB, fits: true },
          { id: '720', label: '720p', height: 1280, size: 13.1 * MB, fits: true },
          { id: '480', label: '480p', height: 854, size: 6.4 * MB, fits: true },
          { id: 'audio', label: 'MP3', height: null, size: 1.4 * MB, fits: true }
        ]
      },
      video: {
        platform: 'youtube', kind: 'video', section: 'videos', title: 'Chimyon tog‘lari: dron bilan qishki sayohat | To‘liq film',
        author: 'Safar Vlog', thumbnail: THUMBS.video, duration: 252, width: 1920, height: 1080, orientation: 'horizontal', items_count: 1,
        formats: [
          { id: 'auto', label: 'Avto', height: 720, size: 38.9 * MB, fits: true },
          { id: '1080', label: '1080p', height: 1080, size: 71.3 * MB, fits: false },
          { id: '720', label: '720p', height: 720, size: 38.9 * MB, fits: true },
          { id: '480', label: '480p', height: 480, size: 19.7 * MB, fits: true },
          { id: '360', label: '360p', height: 360, size: 11.2 * MB, fits: true },
          { id: 'audio', label: 'MP3', height: null, size: 5.9 * MB, fits: true }
        ]
      },
      vshort: {
        platform: 'youtube', kind: 'short', section: 'shorts', title: 'Vertikal video /watch havolasi orqali',
        author: 'Demo Kanal', thumbnail: THUMBS.vertical2, duration: 41, width: 1080, height: 1920, orientation: 'vertical', items_count: 1,
        formats: [
          { id: 'auto', label: 'Avto', height: 1920, size: 11.5 * MB, fits: true },
          { id: '720', label: '720p', height: 1280, size: 6.2 * MB, fits: true },
          { id: 'audio', label: 'MP3', height: null, size: 0.9 * MB, fits: true }
        ]
      }
    };
    var ago = function (min) { return new Date(Date.now() - min * 60000).toISOString(); };
    var emptyHistory = QS.get('history') === 'empty';
    var HISTORY = emptyHistory ? [] : [
      { id: 'h1', section: 'instagram', kind: 'reel', title: 'Chorsu bozori — ertalabki kayfiyat', thumbnail: THUMBS.reel, url: 'https://www.instagram.com/reel/C7aBcDeFgHi/', format: 'auto', status: 'done', created_at: ago(14) },
      { id: 'h2', section: 'instagram', kind: 'post', title: 'Buxoro: eski shahar bo‘ylab 8 ta surat', thumbnail: THUMBS.post, url: 'https://www.instagram.com/p/C6xYz12AbCd/', format: 'auto', status: 'done', created_at: ago(190) },
      { id: 'h3', section: 'instagram', kind: 'reel', title: 'Yopiq akkauntdagi video', thumbnail: null, url: 'https://www.instagram.com/reel/C5qWeRtYuIo/', format: 'auto', status: 'error', created_at: ago(60 * 26) },
      { id: 'h4', section: 'shorts', kind: 'short', title: 'Tog‘dagi sharshara — 30 soniya sokinlik', thumbnail: THUMBS.vertical2, url: 'https://www.youtube.com/shorts/aBcDeFgHiJk', format: 'auto', status: 'done', created_at: ago(42) },
      { id: 'h5', section: 'shorts', kind: 'short', title: 'Toshkent metrosi: eng chiroyli bekatlar', thumbnail: THUMBS.short, url: 'https://www.youtube.com/shorts/ZyXwVuTsRqP', format: '720', status: 'done', created_at: ago(60 * 50) },
      { id: 'h6', section: 'videos', kind: 'video', title: 'O‘zbek oshi: to‘liq retsept (1 soatlik master-klass)', thumbnail: THUMBS.video, url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', format: '720', status: 'done', created_at: ago(95) },
      { id: 'h7', section: 'videos', kind: 'video', title: 'Lo-fi musiqa — dars qilish uchun', thumbnail: null, url: 'https://www.youtube.com/watch?v=jfKfPfyJRdk', format: 'audio', status: 'done', created_at: ago(60 * 24 * 4) }
    ];
    var ME = {
      user: { id: 1, first_name: 'Dilshod', username: 'dilshod_uz' },
      stats: { total: 47, instagram: 21, shorts: 17, videos: 9 },
      limits: { max_upload_mb: 50, max_duration_min: 120, hourly_limit: 30, hourly_used: 7 }
    };
    var JOBS = {};
    var PROBED = {};
    var activeJobId = null;
    var jobSeq = 0;

    function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
    function fail(code, msg) { return Promise.reject(new ApiError(code, msg || '', 0)); }
    function clone(o) { return JSON.parse(JSON.stringify(o)); }

    function pickMedia(url) {
      var c = classify(url);
      if (!c.ok) return null;
      var m;
      if (c.platform === 'instagram') m = clone(c.kind === 'post' ? MEDIA.post : MEDIA.reel);
      else if (c.kind === 'short') m = clone(MEDIA.short);
      else m = clone(/^VERTICAL/i.test(c.id) ? MEDIA.vshort : MEDIA.video);
      m.id = c.id;
      m.url = m.section === 'shorts' && c.kind === 'video' ? 'https://www.youtube.com/shorts/' + c.id : c.url;
      return m;
    }

    function jobState(job) {
      var t = (Date.now() - job.t0) / 1000;
      var audio = job.format === 'audio';
      var tq = 0.9, td = audio ? 2.2 : 4.6, tp = audio ? 0.9 : 1.4, tu = 1.3;
      var out = { id: job.id, format: job.format, used_format: null, note: null, error: null, media: job.media, created_at: job.created_at };
      if (t < tq) { out.status = 'queued'; out.progress = 0; }
      else if (t < tq + td) {
        var x = (t - tq) / td;
        out.status = 'downloading'; out.progress = Math.min(99, Math.round(100 * (1 - Math.pow(1 - x, 1.6))));
        if (job.failAt && x > 0.55) { out.status = 'error'; out.progress = 55; out.error = { code: 'too_large', message: '' }; }
      }
      else if (t < tq + td + tp) { out.status = 'processing'; out.progress = 100; }
      else if (t < tq + td + tp + tu) { out.status = 'uploading'; out.progress = 100; }
      else {
        out.status = 'done'; out.progress = 100;
        // Mirrors the backend: auto on a 16:9 video is downgraded to the first tier that fits.
        if (job.format === 'auto' && job.media.kind === 'video') { out.used_format = '720'; out.note = 'Hajm limiti sababli 720p sifatda yuborildi'; }
        else if (job.format === 'auto' && job.media.kind === 'short') out.used_format = '1080';
        else out.used_format = job.format;
      }
      if ((out.status === 'done' || out.status === 'error') && !job.finished) {
        job.finished = true;
        if (activeJobId === job.id) activeJobId = null;
        HISTORY.unshift({
          id: job.id, section: job.media.section, kind: job.media.kind, title: job.media.title, thumbnail: job.media.thumbnail,
          url: job.url, format: job.format, status: out.status, created_at: job.created_at
        });
        if (out.status === 'done') { ME.stats.total++; ME.stats[job.media.section]++; }
      }
      return out;
    }

    function handle(method, path, body) {
      var p = path.split('?')[0];
      var q = new URLSearchParams(path.split('?')[1] || '');
      if (method === 'POST' && p === '/probe') {
        return delay(850 + Math.random() * 500).then(function () {
          var url = String(body && body.url || '');
          var low = url.toLowerCase();
          if (low.indexOf('private') >= 0) return fail('private', 'Bu akkaunt yopiq. Faqat ochiq akkauntlardagi kontentni yuklash mumkin.');
          if (low.indexOf('toolong') >= 0) return fail('too_long', 'Video juda uzun (maksimal 120 daqiqa).');
          if (low.indexOf('error') >= 0) return fail('not_found', 'Kontent topilmadi yoki o‘chirilgan.');
          var m = pickMedia(url);
          if (!m) return fail('invalid_url', 'Havola noto‘g‘ri.');
          PROBED[m.url] = m;
          return { ok: true, media: m };
        });
      }
      if (method === 'POST' && p === '/download') {
        return delay(450).then(function () {
          var url = String(body && body.url || '');
          var m = PROBED[url] || pickMedia(url);
          if (!m) return fail('invalid_url');
          if (!m.formats.some(function (f) { return f.id === body.format && f.fits; })) return fail('too_large', 'Bu sifat Telegram limitiga sig‘maydi.');
          if (activeJobId && JOBS[activeJobId] && !JOBS[activeJobId].finished) return fail('busy', 'Sizda faol yuklash bor. U tugashini kuting.');
          if (ME.limits.hourly_used >= ME.limits.hourly_limit) return fail('rate_limited', 'Soatlik limit (' + ME.limits.hourly_limit + ' ta) tugadi.');
          ME.limits.hourly_used++;
          var id = 'mock-' + (++jobSeq) + '-' + Date.now().toString(36);
          JOBS[id] = {
            id: id, t0: Date.now(), format: body.format, url: m.url, finished: false, failAt: url.toLowerCase().indexOf('fail') >= 0,
            media: { title: m.title, thumbnail: m.thumbnail, kind: m.kind, section: m.section }, created_at: new Date().toISOString()
          };
          activeJobId = id;
          return { ok: true, job: jobState(JOBS[id]) };
        });
      }
      var jm = p.match(/^\/jobs\/(.+)$/);
      if (method === 'GET' && jm) {
        return delay(120).then(function () {
          var job = JOBS[decodeURIComponent(jm[1])];
          if (!job) return fail('not_found');
          return { ok: true, job: jobState(job) };
        });
      }
      if (method === 'GET' && p === '/history') {
        return delay(500 + Math.random() * 400).then(function () {
          var sec = q.get('section') || 'all';
          var lim = Math.min(50, Number(q.get('limit')) || 20);
          return { ok: true, items: clone(HISTORY.filter(function (x) { return sec === 'all' || x.section === sec; }).slice(0, lim)) };
        });
      }
      if (method === 'GET' && p === '/me') {
        return delay(350).then(function () { return { ok: true, user: clone(ME.user), stats: clone(ME.stats), limits: clone(ME.limits) }; });
      }
      return fail('not_found');
    }
    return { handle: handle };
  })();

  /* ======================================================================
   * Wire up
   * ==================================================================== */
  function bind() {
    el.tabIg.addEventListener('click', function () { if (S.section !== 'instagram') { haptic.sel(); setSection('instagram'); } });
    el.tabYt.addEventListener('click', function () { if (S.section === 'instagram') { haptic.sel(); setSection(S.ytSub); } });
    el.tabShorts.addEventListener('click', function () { if (S.section !== 'shorts') { haptic.sel(); setSection('shorts'); } });
    el.tabVideos.addEventListener('click', function () { if (S.section !== 'videos') { haptic.sel(); setSection('videos'); } });
    var ptabs = [el.tabIg, el.tabYt], stabs = [el.tabShorts, el.tabVideos];
    ptabs.forEach(function (t) { t.addEventListener('keydown', function (e) { onTabKey(e, ptabs); }); });
    stabs.forEach(function (t) { t.addEventListener('keydown', function (e) { onTabKey(e, stabs); }); });

    el.form.addEventListener('submit', function (e) { e.preventDefault(); check(); });
    el.input.addEventListener('input', function () {
      cur().url = el.input.value;
      clearTimeout(hintTimer);
      renderInputState(false);
      hintTimer = setTimeout(function () { renderInputState(true); }, 900);
      updateMainButton();
    });
    el.input.addEventListener('paste', function () {
      setTimeout(function () {
        cur().url = el.input.value;
        renderInputState(true);
        if (classify(el.input.value).ok) check();
      }, 0);
    });
    el.clear.addEventListener('click', function () {
      el.input.value = ''; cur().url = '';
      var st = cur();
      if (st.phase === 'probeError' || st.phase === 'preview' || st.phase === 'done' || st.phase === 'jobError') resetSection(S.section);
      renderInputState(); updateMainButton();
      el.input.focus();
    });
    el.paste.addEventListener('click', onPaste);
    el.refresh.addEventListener('click', function () { haptic.tap('light'); loadHistory(S.section); });
    el.profileBtn.addEventListener('click', openSheet);
    el.sheetClose.addEventListener('click', closeSheet);
    el.sheetBackdrop.addEventListener('click', closeSheet);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && S.sheetOpen) { e.preventDefault(); closeSheet(); }
      if (e.key === 'Tab' && S.sheetOpen) trapFocus(e);
    });
    window.addEventListener('online', function () { S.offline = false; renderBanners(); });
    window.addEventListener('offline', function () { S.offline = true; renderBanners(); });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState !== 'visible') return;
      var st = cur();
      if (st.phase === 'job') schedulePoll(S.section, 0);
    });
  }

  function trapFocus(e) {
    var f = el.sheetPanel.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])');
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === el.sheetPanel)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function initTelegram() {
    if (!IN_TG) return;
    ROOT.classList.add('in-tg');
    safe(function () { TG.ready(); });
    safe(function () { TG.expand(); });
    applyTheme();
    safe(function () { TG.onEvent('themeChanged', applyTheme); });
    if (TG.MainButton) safe(function () { TG.MainButton.onClick(onMainButton); });
    if (tgv('6.1') && TG.BackButton) safe(function () { TG.BackButton.onClick(onBack); });
  }

  function initialSection() {
    var q = QS.get('section');
    if (SECTIONS[q]) return q;
    var sp = IN_TG && TG.initDataUnsafe ? TG.initDataUnsafe.start_param : null;
    if (SECTIONS[sp]) return sp;
    var saved = store.get('section');
    return SECTIONS[saved] ? saved : 'instagram';
  }

  function init() {
    el.demo.hidden = !MOCK;
    initTelegram();
    bind();
    var first = initialSection();
    if (first !== 'instagram') S.ytSub = first;
    S.section = first === 'instagram' ? 'videos' : 'instagram'; // force a full render
    setSection(first, { noAnim: true });
    renderBanners();
    renderAvatar();
    loadMe();
    // Support a prefilled link via ?url= (handy for demos/deep links). Treated as plain user text.
    var pre = QS.get('url');
    if (pre) { el.input.value = pre.slice(0, 2048); cur().url = el.input.value; renderInputState(true); check({ blur: false }); }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
