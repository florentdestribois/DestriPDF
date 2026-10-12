// Visionneuse : pages empilées, rendu à la demande des pages visibles, zoom ancré,
// calques (texte sélectionnable, annotations, champs, recherche, outils).

import { Api } from './api.js';
import { el, clamp } from './ui.js';

export const PT = 96 / 72; // pixels CSS par point à 100 %
const BASE = 2; // calques construits à 2 px par point, puis mis à l'échelle
const GAP = 16;
const PAD_TOP = 18;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 6;
const KEEP_AROUND = 10; // pages conservées en mémoire autour de la page courante

const measureCtx = document.createElement('canvas').getContext('2d');

function cssFamily(family) {
  const safe = String(family || '').replace(/["\\]/g, '');
  return safe ? `"${safe}", Arial, sans-serif` : 'Arial, sans-serif';
}

class PageView {
  constructor(viewer, index, info) {
    this.viewer = viewer;
    this.index = index;
    this.w = info.w;
    this.h = info.h;
    this.v = info.v;
    this.el = el('div', { class: 'page', dataset: { index: String(index) }, 'aria-label': `Page ${index + 1}` });
    this.img = el('img', { class: 'page-img loading', alt: '', draggable: 'false' });
    this.layers = {
      search: el('div', { class: 'layer search-layer' }),
      text: el('div', { class: 'layer text-layer' }),
      annot: el('div', { class: 'layer annot-layer' }),
      field: el('div', { class: 'layer field-layer' }),
      tool: el('div', { class: 'layer tool-layer' }),
    };
    this.el.append(this.img, this.layers.search, this.layers.text, this.layers.annot, this.layers.field, this.layers.tool);
    this.loadedKey = '';
    this.pendingKey = '';
    this.textV = -1;
    this.annotV = -1;
    this.textData = null;
    this.annotData = null;
    this.visible = false;
  }

  scaledLayer(layer) {
    layer.style.width = `${this.w * BASE}px`;
    layer.style.height = `${this.h * BASE}px`;
    layer.style.transformOrigin = '0 0';
    layer.style.transform = `scale(${this.viewer.scale / BASE})`;
  }

  layout(scale) {
    this.el.style.width = `${Math.round(this.w * scale)}px`;
    this.el.style.height = `${Math.round(this.h * scale)}px`;
    for (const name of ['search', 'text', 'annot', 'field']) this.scaledLayer(this.layers[name]);
  }

  imageKey() {
    return `${this.v}@${this.viewer.renderScale()}`;
  }

  ensure() {
    const key = this.imageKey();
    if (key !== this.loadedKey && key !== this.pendingKey) this.loadImage(key);
    if (this.textV !== this.v) this.loadText();
    if (this.annotV !== this.v) this.loadAnnots();
  }

  loadImage(key) {
    this.pendingKey = key;
    const scale = this.viewer.renderScale();
    // L'identifiant du document fait partie de l'adresse : deux documents ouverts
    // successivement ne partagent jamais une image mise en cache.
    const url = `api/page/${this.index}/image?d=${this.viewer.doc.id}&s=${scale}&v=${this.v}`;
    const next = new Image();
    next.decoding = 'async';
    next.src = url;
    next.decode().then(() => {
      if (this.pendingKey !== key) return;
      this.img.src = url;
      this.img.classList.remove('loading');
      this.loadedKey = key;
      this.pendingKey = '';
      this.viewer.dispatchEvent(new CustomEvent('pagerendered', { detail: { index: this.index } }));
    }).catch(() => {
      if (this.pendingKey === key) this.pendingKey = '';
    });
  }

  async loadText() {
    const v = this.v;
    this.textV = v;
    try {
      const data = await Api.get(`api/page/${this.index}/text?v=${v}`);
      if (this.v !== v) return;
      this.textData = data;
      this.buildText();
      this.viewer.dispatchEvent(new CustomEvent('textready', { detail: { index: this.index } }));
    } catch (err) {
      if (this.v === v) this.textV = -1;
    }
  }

  buildText() {
    const layer = this.layers.text;
    layer.textContent = '';
    if (!this.textData) return;
    const frag = document.createDocumentFragment();
    for (const line of this.textData.lines) {
      const [x0, y0, x1, y1] = line.bbox;
      const seg = document.createElement('div');
      seg.className = line.editable ? 'tl-seg editable' : 'tl-seg';
      seg.dataset.line = String(line.id);
      const height = (y1 - y0) * BASE;
      seg.style.left = `${x0 * BASE}px`;
      seg.style.top = `${y0 * BASE}px`;
      seg.style.height = `${height}px`;
      seg.style.lineHeight = `${height}px`;
      let natural = 0;
      for (const span of line.spans) {
        const node = document.createElement('span');
        node.textContent = span.text;
        const size = span.size * BASE;
        const weight = span.bold ? 700 : 400;
        const style = span.italic ? 'italic' : 'normal';
        node.style.fontSize = `${size}px`;
        node.style.fontFamily = cssFamily(span.family);
        if (span.bold) node.style.fontWeight = '700';
        if (span.italic) node.style.fontStyle = 'italic';
        measureCtx.font = `${style} ${weight} ${size}px ${cssFamily(span.family)}`;
        natural += measureCtx.measureText(span.text).width;
        seg.append(node);
      }
      const target = (x1 - x0) * BASE;
      if (Math.abs(line.angle) > 0.5) {
        seg.style.transform = `rotate(${line.angle}deg)`;
      } else if (natural > 0) {
        seg.style.transform = `scaleX(${target / natural})`;
      }
      frag.append(seg, document.createElement('br'));
    }
    layer.append(frag);
  }

  async loadAnnots() {
    const v = this.v;
    this.annotV = v;
    try {
      const data = await Api.get(`api/page/${this.index}/annots?v=${v}`);
      if (this.v !== v) return;
      this.annotData = data;
      this.viewer.dispatchEvent(new CustomEvent('annotsready', { detail: { index: this.index, page: this } }));
    } catch {
      if (this.v === v) this.annotV = -1;
    }
  }

  release() {
    if (!this.loadedKey && !this.pendingKey && !this.textData) return;
    this.img.removeAttribute('src');
    this.img.classList.add('loading');
    this.loadedKey = '';
    this.pendingKey = '';
    this.layers.text.textContent = '';
    this.layers.annot.textContent = '';
    this.layers.field.textContent = '';
    this.textV = -1;
    this.annotV = -1;
    this.textData = null;
    this.annotData = null;
  }

  invalidate(v) {
    this.v = v;
  }
}

export class Viewer extends EventTarget {
  constructor(scroller, container) {
    super();
    this.scroller = scroller;
    this.container = container;
    this.doc = null;
    this.views = [];
    this.zoom = 1;
    this.fit = 'width';
    this.current = 0;
    this.searchHits = [];
    this.searchIndex = -1;
    this.offsets = [];
    this._renderTimer = null;
    this._scrollRaf = 0;
    this.io = new IntersectionObserver((entries) => this.onIntersect(entries), { root: scroller, rootMargin: '120% 0px' });
    scroller.addEventListener('scroll', () => {
      if (this._scrollRaf) return;
      this._scrollRaf = requestAnimationFrame(() => {
        this._scrollRaf = 0;
        this.updateCurrent();
      });
    }, { passive: true });
    this.resizeObserver = new ResizeObserver(() => {
      if (this.doc && this.fit) this.applyFit(true);
    });
    this.resizeObserver.observe(scroller);
    scroller.addEventListener('wheel', (event) => {
      if (!event.ctrlKey || !this.doc) return;
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0022);
      this.setZoom(this.zoom * factor, { clientX: event.clientX, clientY: event.clientY });
    }, { passive: false });
  }

  get scale() {
    return this.zoom * PT;
  }

  renderScale() {
    const dpr = window.devicePixelRatio || 1;
    return Math.round(this.scale * dpr * 1000) / 1000;
  }

  load(doc) {
    this.doc = doc;
    this.rebuild();
    // Ouverture : largeur de la fenêtre, sans dépasser 150 % sur un grand écran.
    this.fit = doc.pages.some((p) => p.w > p.h) && doc.page_count === 1 ? 'page' : 'auto';
    this.applyFit(false);
    this.scroller.scrollTop = 0;
    this.current = 0;
    this.updateCurrent(true);
  }

  rebuild() {
    this.io.disconnect();
    this.container.textContent = '';
    this.views = this.doc.pages.map((info, index) => new PageView(this, index, info));
    for (const view of this.views) {
      this.container.append(view.el);
      this.io.observe(view.el);
    }
    this.relayout();
  }

  // Met à jour l'affichage après une modification ; reconstruit si la structure a changé.
  update(doc) {
    const old = this.doc;
    this.doc = doc;
    const structural = !old || old.page_count !== doc.page_count
      || doc.pages.some((p, i) => !old.pages[i] || old.pages[i].w !== p.w || old.pages[i].h !== p.h || old.pages[i].rot !== p.rot);
    if (structural) {
      const keep = Math.min(this.current, doc.page_count - 1);
      const offsetInPage = this.scroller.scrollTop - (this.offsets[this.current] ?? 0);
      this.rebuild();
      if (this.fit) this.applyFit(false);
      this.scroller.scrollTop = (this.offsets[keep] ?? 0) + Math.max(0, offsetInPage);
      this.updateCurrent(true);
      this.dispatchEvent(new CustomEvent('structure'));
      return;
    }
    for (const [i, info] of doc.pages.entries()) {
      const view = this.views[i];
      if (view && view.v !== info.v) {
        view.invalidate(info.v);
        if (view.visible) view.ensure();
      }
    }
  }

  relayout() {
    const scale = this.scale;
    let top = PAD_TOP;
    this.offsets = [];
    for (const view of this.views) {
      view.layout(scale);
      this.offsets.push(top);
      top += Math.round(view.h * scale) + GAP;
    }
    this.dispatchEvent(new CustomEvent('zoomchange', { detail: { zoom: this.zoom, fit: this.fit } }));
  }

  availableSize() {
    const style = getComputedStyle(this.container);
    const padX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    return {
      width: this.scroller.clientWidth - padX - 2,
      height: this.scroller.clientHeight - PAD_TOP - GAP,
    };
  }

  applyFit(keepPosition) {
    if (!this.doc || !this.views.length) return;
    const { width, height } = this.availableSize();
    const ref = this.views[this.current] || this.views[0];
    const maxW = Math.max(...this.views.map((v) => v.w));
    let zoom = this.zoom;
    if (this.fit === 'width' || this.fit === 'auto') zoom = width / (maxW * PT);
    else if (this.fit === 'page') zoom = Math.min(width / (ref.w * PT), height / (ref.h * PT));
    if (this.fit === 'auto') zoom = Math.min(zoom, 1.5);
    zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    if (Math.abs(zoom - this.zoom) < 0.001 && this.offsets.length) return;
    this.setZoom(zoom, keepPosition ? {} : null, true);
  }

  setFit(fit) {
    this.fit = fit;
    this.applyFit(true);
  }

  setZoom(zoom, anchor = {}, keepFit = false) {
    zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    if (!keepFit) this.fit = null;
    if (!this.doc) {
      this.zoom = zoom;
      return;
    }
    const scroller = this.scroller;
    const box = scroller.getBoundingClientRect();
    const ax = anchor && anchor.clientX !== undefined ? anchor.clientX - box.left : scroller.clientWidth / 2;
    const ay = anchor && anchor.clientY !== undefined ? anchor.clientY - box.top : scroller.clientHeight / 2;
    // Point du document sous l'ancre, en coordonnées de page.
    const hit = this.pageAtClient(box.left + ax, box.top + ay, true);
    this.zoom = zoom;
    this.relayout();
    if (hit && anchor !== null) {
      const view = this.views[hit.index];
      const rect = view.el.getBoundingClientRect();
      const nx = rect.left - box.left + hit.x * this.scale;
      const ny = rect.top - box.top + hit.y * this.scale;
      scroller.scrollLeft += nx - ax;
      scroller.scrollTop += ny - ay;
    }
    this.scheduleRender();
    this.updateCurrent(true);
  }

  zoomStep(direction) {
    const steps = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6];
    const z = this.zoom;
    const next = direction > 0 ? steps.find((s) => s > z + 0.005) : [...steps].reverse().find((s) => s < z - 0.005);
    this.setZoom(next ?? z);
  }

  scheduleRender() {
    clearTimeout(this._renderTimer);
    this._renderTimer = setTimeout(() => {
      for (const view of this.views) if (view.visible) view.ensure();
    }, 140);
  }

  onIntersect(entries) {
    for (const entry of entries) {
      const view = this.views[Number(entry.target.dataset.index)];
      if (!view) continue;
      view.visible = entry.isIntersecting;
      if (view.visible) view.ensure();
    }
    this.releaseFar();
  }

  releaseFar() {
    for (const view of this.views) {
      if (!view.visible && Math.abs(view.index - this.current) > KEEP_AROUND) view.release();
    }
  }

  updateCurrent(force = false) {
    if (!this.views.length) return;
    const mid = this.scroller.scrollTop + this.scroller.clientHeight * 0.35;
    let lo = 0;
    let hi = this.offsets.length - 1;
    while (lo < hi) {
      const m = (lo + hi + 1) >> 1;
      if (this.offsets[m] <= mid) lo = m;
      else hi = m - 1;
    }
    if (lo !== this.current || force) {
      this.current = lo;
      this.dispatchEvent(new CustomEvent('pagechange', { detail: { index: lo } }));
    }
  }

  scrollToPage(index, { y = null, smooth = false } = {}) {
    index = clamp(index, 0, this.views.length - 1);
    const top = this.offsets[index] + (y !== null ? y * this.scale - 40 : -PAD_TOP / 2);
    this.scroller.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
    this.current = index;
    this.dispatchEvent(new CustomEvent('pagechange', { detail: { index } }));
  }

  scrollToRect(index, rect) {
    const view = this.views[index];
    if (!view) return;
    const scale = this.scale;
    const top = this.offsets[index] + rect[1] * scale;
    const bottom = this.offsets[index] + rect[3] * scale;
    const viewTop = this.scroller.scrollTop;
    const viewBottom = viewTop + this.scroller.clientHeight;
    if (top < viewTop + 40 || bottom > viewBottom - 40) {
      this.scroller.scrollTop = Math.max(0, top - this.scroller.clientHeight * 0.3);
    }
    const left = view.el.offsetLeft + rect[0] * scale;
    if (left < this.scroller.scrollLeft || left > this.scroller.scrollLeft + this.scroller.clientWidth - 40) {
      this.scroller.scrollLeft = Math.max(0, left - 60);
    }
  }

  // Page et coordonnées (points) sous un point de l'écran.
  pageAtClient(clientX, clientY, nearest = false) {
    let best = null;
    let bestDist = Infinity;
    for (const view of this.views) {
      const rect = view.el.getBoundingClientRect();
      if (clientY >= rect.top && clientY <= rect.bottom && clientX >= rect.left && clientX <= rect.right) {
        return { index: view.index, view, x: (clientX - rect.left) / this.scale, y: (clientY - rect.top) / this.scale };
      }
      if (nearest) {
        const dy = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0;
        if (dy < bestDist) {
          bestDist = dy;
          best = view;
        }
      }
    }
    if (!best) return null;
    const rect = best.el.getBoundingClientRect();
    return {
      index: best.index,
      view: best,
      x: clamp((clientX - rect.left) / this.scale, 0, best.w),
      y: clamp((clientY - rect.top) / this.scale, 0, best.h),
    };
  }

  pointInView(view, clientX, clientY) {
    const rect = view.el.getBoundingClientRect();
    return {
      x: clamp((clientX - rect.left) / this.scale, 0, view.w),
      y: clamp((clientY - rect.top) / this.scale, 0, view.h),
    };
  }

  // --- Recherche ---

  setSearch(hits, index) {
    this.searchHits = hits;
    this.searchIndex = index;
    for (const view of this.views) view.layers.search.textContent = '';
    hits.forEach((hit, i) => {
      const view = this.views[hit.page];
      if (!view) return;
      const [x0, y0, x1, y1] = hit.rect;
      const node = el('div', { class: i === index ? 'search-hit current' : 'search-hit' });
      node.style.left = `${x0 * BASE}px`;
      node.style.top = `${y0 * BASE}px`;
      node.style.width = `${(x1 - x0) * BASE}px`;
      node.style.height = `${(y1 - y0) * BASE}px`;
      view.layers.search.append(node);
    });
    if (index >= 0 && hits[index]) this.scrollToRect(hits[index].page, hits[index].rect);
  }

  // Coordonnées « couche » (BASE px par point) pour les calques mis à l'échelle.
  static layerStyle(node, rect) {
    const [x0, y0, x1, y1] = rect;
    node.style.left = `${x0 * BASE}px`;
    node.style.top = `${y0 * BASE}px`;
    node.style.width = `${Math.max(1, (x1 - x0) * BASE)}px`;
    node.style.height = `${Math.max(1, (y1 - y0) * BASE)}px`;
  }

  // Coordonnées en pixels réels du calque d'outils (non mis à l'échelle).
  placeInTool(node, view, rect) {
    const s = this.scale;
    const [x0, y0, x1, y1] = rect;
    node.style.left = `${x0 * s}px`;
    node.style.top = `${y0 * s}px`;
    node.style.width = `${(x1 - x0) * s}px`;
    node.style.height = `${(y1 - y0) * s}px`;
  }
}

export { BASE };
