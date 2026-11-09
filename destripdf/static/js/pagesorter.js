// Sélection de pages et glisser-déposer, partagés par les vignettes et la vue
// « Organiser » : clic (une page), Ctrl+clic (ajoute ou retire), Maj+clic (plage
// depuis la dernière page cliquée), Ctrl+Maj+clic (ajoute la plage). Glisser déplace
// les pages choisies ; un PDF déposé depuis l'Explorateur s'insère à l'endroit montré.

import { el } from './ui.js';

const PAGES_TYPE = 'application/x-destripdf-pages';
let activeDrag = null; // { pages } : pages en cours de déplacement, quelle que soit la liste

// PDF ou image (convertie en page PDF par le serveur).
export const isImageFile = (file) => /\.(jpe?g|jpe|jfif|png|tiff?|bmp|gif|jp2|jpx|webp)$/i.test(file.name || '')
  || /^image\/(jpeg|png|tiff|bmp|gif|jp2|jpx|webp)$/.test(file.type || '');
export const isPdfFile = (file) => /\.pdf$/i.test(file.name || '') || file.type === 'application/pdf' || isImageFile(file);

// Ordre de l'Explorateur : sans casse, « 2 - plan » avant « 10 - annexe ».
export const byName = (a, b) => (a.name || '').localeCompare(b.name || '', 'fr', { numeric: true, sensitivity: 'base' });

// Pages choisies, partagées par toutes les listes de pages.
export class PageSelection extends EventTarget {
  constructor() {
    super();
    this.pages = new Set();
    this.anchor = null; // départ d'une plage (Maj+clic)
  }

  get size() { return this.pages.size; }

  has(index) { return this.pages.has(index); }

  list() { return [...this.pages].sort((a, b) => a - b); }

  set(pages, anchor = null) {
    this.pages = new Set(pages);
    this.anchor = anchor ?? (pages.length ? pages[0] : null);
    this.changed();
  }

  only(index) { this.set([index], index); }

  toggle(index) {
    if (this.pages.has(index)) this.pages.delete(index);
    else this.pages.add(index);
    this.anchor = index;
    this.changed();
  }

  range(from, to, add = false) {
    const next = add ? new Set(this.pages) : new Set();
    for (let i = Math.min(from, to); i <= Math.max(from, to); i += 1) next.add(i);
    this.pages = next;
    if (this.anchor === null) this.anchor = from;
    this.changed();
  }

  clear() { this.set([], null); }

  // Une page seule suit la page affichée ; une sélection de plusieurs pages reste.
  follow(index) {
    if (this.pages.size > 1 || (this.pages.size === 1 && this.pages.has(index))) return;
    this.set([index], index);
  }

  clamp(count) {
    const kept = [...this.pages].filter((i) => i < count);
    if (kept.length === this.pages.size && (this.anchor === null || this.anchor < count)) return;
    this.pages = new Set(kept);
    if (this.anchor !== null && this.anchor >= count) this.anchor = kept.length ? Math.max(...kept) : null;
    this.changed();
  }

  changed() { this.dispatchEvent(new CustomEvent('change')); }
}

// Comportement d'une liste de pages (`container` : élément qui défile, pages
// `[data-index]`). `layout` : 'list' (une colonne) ou 'grid'.
export class PageSorter {
  constructor(container, selection, options = {}) {
    this.container = container;
    this.selection = selection;
    this.options = { layout: 'list', item: '[data-index]', ...options };
    this.marker = null; // { node, side, gap }
    this.focusIndex = null;
    container.classList.add('sorter-zone');
    // Maj+clic : sélection de pages, jamais de texte.
    container.addEventListener('mousedown', (e) => { if (e.shiftKey && this.itemOf(e.target)) e.preventDefault(); });
    container.addEventListener('click', (e) => this.onClick(e));
    container.addEventListener('dblclick', (e) => {
      const node = this.itemOf(e.target);
      if (node && !e.target.closest('button') && this.options.onOpen) this.options.onOpen(this.indexOf(node));
    });
    container.addEventListener('keydown', (e) => this.onKey(e));
    container.addEventListener('contextmenu', (e) => {
      const node = this.itemOf(e.target);
      if (!node || !this.options.onContext) return;
      e.preventDefault();
      const index = this.indexOf(node);
      this.options.onContext(index, node, this.targets(index));
    });
    container.addEventListener('dragstart', (e) => this.onDragStart(e));
    container.addEventListener('dragover', (e) => this.onDragOver(e));
    container.addEventListener('dragleave', (e) => { if (!container.contains(e.relatedTarget)) this.hideMarker(); });
    container.addEventListener('drop', (e) => this.onDrop(e));
    container.addEventListener('dragend', () => this.endDrag());
    selection.addEventListener('change', () => this.paint());
  }

  items() { return [...this.container.querySelectorAll(this.options.item)]; }

  itemOf(target) {
    const node = target?.closest?.(this.options.item);
    return node && this.container.contains(node) ? node : null;
  }

  indexOf(node) { return Number(node.dataset.index); }

  // Pages visées par une action sur `index` : la sélection si la page en fait partie.
  targets(index) {
    if (this.selection.has(index)) return this.selection.list();
    this.selection.only(index);
    return [index];
  }

  paint() {
    const items = this.items();
    this.container.classList.toggle('multi', this.selection.size > 1);
    let focus = this.focusIndex;
    if (focus === null || focus >= items.length) focus = this.selection.size ? this.selection.list()[0] : 0;
    for (const node of items) {
      const index = this.indexOf(node);
      const selected = this.selection.has(index);
      node.classList.toggle('selected', selected);
      node.setAttribute('aria-selected', String(selected));
      node.tabIndex = index === focus ? 0 : -1; // une seule page dans l'ordre de tabulation
    }
  }

  focusItem(index, scroll = true) {
    const node = this.items()[index];
    if (!node) return;
    this.focusIndex = index;
    this.paint();
    node.focus({ preventScroll: !scroll });
    if (scroll) node.scrollIntoView({ block: 'nearest' });
  }

  onClick(e) {
    if (e.target.closest('button, input, select, a')) return; // boutons d'action de la vignette
    const node = this.itemOf(e.target);
    if (!node) {
      if (this.options.clearOnEmpty && !e.ctrlKey && !e.shiftKey && !e.metaKey) this.selection.clear();
      return;
    }
    const index = this.indexOf(node);
    const ctrl = e.ctrlKey || e.metaKey;
    this.focusIndex = index;
    if (e.shiftKey) this.selection.range(this.selection.anchor ?? index, index, ctrl);
    else if (ctrl) this.selection.toggle(index);
    else {
      this.selection.only(index);
      this.options.onActivate?.(index);
    }
    node.focus({ preventScroll: true });
  }

  columns(items) {
    if (this.options.layout !== 'grid' || items.length < 2) return 1;
    const top = items[0].offsetTop;
    let cols = 0;
    while (cols < items.length && items[cols].offsetTop === top) cols += 1;
    return Math.max(1, cols);
  }

  onKey(e) {
    const node = this.itemOf(e.target);
    if (!node || e.target !== node) return;
    const items = this.items();
    const index = this.indexOf(node);
    const ctrl = e.ctrlKey || e.metaKey;
    const key = e.key;
    const stop = () => { e.preventDefault(); e.stopPropagation(); };
    if (ctrl && key.toLowerCase() === 'a') {
      stop();
      this.selection.set(items.map((n) => this.indexOf(n)), 0);
      return;
    }
    if (key === 'Delete') {
      stop();
      this.options.onDelete?.(this.targets(index));
      return;
    }
    if (key === 'Enter') {
      stop();
      if (this.options.onOpen) this.options.onOpen(index);
      else { this.selection.only(index); this.options.onActivate?.(index); }
      return;
    }
    if (key === ' ') {
      stop();
      if (ctrl) this.selection.toggle(index);
      else { this.selection.only(index); this.options.onActivate?.(index); }
      return;
    }
    const cols = this.columns(items);
    const steps = this.options.layout === 'grid'
      ? { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }
      : { ArrowUp: -1, ArrowDown: 1, ArrowLeft: -1, ArrowRight: 1 };
    let next = null;
    if (key in steps) next = index + steps[key];
    else if (key === 'Home') next = 0;
    else if (key === 'End') next = items.length - 1;
    if (next === null) return;
    stop();
    next = Math.max(0, Math.min(items.length - 1, next));
    if (e.shiftKey) this.selection.range(this.selection.anchor ?? index, next, ctrl);
    else if (!ctrl) {
      this.selection.only(next);
      this.options.onActivate?.(next);
    }
    this.focusItem(next);
  }

  // --- Glisser-déposer ---

  onDragStart(e) {
    const node = this.itemOf(e.target);
    if (!node) return;
    const index = this.indexOf(node);
    if (!this.selection.has(index)) this.selection.only(index);
    const pages = this.selection.list();
    activeDrag = { pages };
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData(PAGES_TYPE, pages.join(','));
    if (pages.length > 1) {
      // Image du glisser : la page saisie et le nombre de pages déplacées.
      const img = node.querySelector('img');
      const ghost = el('div', { class: 'drag-ghost' },
        img?.src ? el('img', { src: img.src, alt: '' }) : null,
        el('span', { class: 'drag-ghost-count', text: `${pages.length} pages` }));
      document.body.append(ghost);
      e.dataTransfer.setDragImage(ghost, 24, 24);
      setTimeout(() => ghost.remove(), 0);
    }
    requestAnimationFrame(() => {
      for (const item of this.items()) item.classList.toggle('dragging', pages.includes(this.indexOf(item)));
    });
  }

  // Ce qui est glissé, d'après les types du glisser lui-même : un ancien glisser de
  // pages resté en mémoire (liste reconstruite pendant le geste) ne prend jamais
  // la place d'un PDF venu de l'Explorateur.
  dragKind(e) {
    const types = [...(e.dataTransfer?.types || [])];
    if (types.includes(PAGES_TYPE)) return activeDrag && this.options.onMove ? 'pages' : null;
    activeDrag = null;
    return types.includes('Files') && this.options.onFiles ? 'files' : null;
  }

  onDragOver(e) {
    const kind = this.dragKind(e);
    if (!kind) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = kind === 'pages' ? 'move' : 'copy';
    this.showMarker(this.gapAt(e.clientX, e.clientY));
    this.autoScroll(e.clientY);
  }

  onDrop(e) {
    const kind = this.dragKind(e);
    if (!kind) return;
    e.preventDefault();
    e.stopPropagation(); // déposé ici : inséré à cet endroit, jamais ouvert à la place du document
    const gap = (this.marker || this.gapAt(e.clientX, e.clientY)).gap;
    this.hideMarker();
    if (kind === 'pages') {
      const { pages } = activeDrag;
      this.endDrag();
      this.options.onMove(pages, gap);
    } else {
      this.options.onFiles([...e.dataTransfer.files], gap);
    }
  }

  endDrag() {
    activeDrag = null;
    this.hideMarker();
    for (const item of this.container.querySelectorAll('.dragging')) item.classList.remove('dragging');
  }

  // Place d'insertion sous le pointeur : avant ou après la page la plus proche.
  gapAt(x, y) {
    const grid = this.options.layout === 'grid';
    const box = this.container.getBoundingClientRect();
    let best = null;
    let bestDist = Infinity;
    for (const node of this.items()) {
      const r = node.getBoundingClientRect();
      if (r.bottom < box.top - 300 || r.top > box.bottom + 300) continue;
      const dx = x < r.left ? r.left - x : x > r.right ? x - r.right : 0;
      const dy = y < r.top ? r.top - y : y > r.bottom ? y - r.bottom : 0;
      const dist = grid ? dy * 8 + dx : dy; // grille : la rangée sous le pointeur d'abord
      if (dist < bestDist) {
        bestDist = dist;
        best = { node, r };
      }
    }
    if (!best) return { gap: this.items().length, node: null, side: 'after' };
    const index = this.indexOf(best.node);
    const after = grid ? x > best.r.left + best.r.width / 2 : y > best.r.top + best.r.height / 2;
    return { gap: after ? index + 1 : index, node: best.node, side: after ? 'after' : 'before' };
  }

  showMarker(marker) {
    if (this.marker && this.marker.node === marker.node && this.marker.side === marker.side) return;
    this.hideMarker();
    this.marker = marker;
    marker.node?.classList.add(marker.side === 'after' ? 'drop-after' : 'drop-before');
  }

  hideMarker() {
    if (this.marker?.node) this.marker.node.classList.remove('drop-before', 'drop-after');
    this.marker = null;
  }

  // Défilement quand le pointeur approche du bord de la liste pendant le glisser.
  autoScroll(y) {
    const box = this.container.getBoundingClientRect();
    const edge = Math.min(64, box.height / 4);
    if (y < box.top + edge) this.container.scrollTop -= Math.ceil((box.top + edge - y) / 3);
    else if (y > box.bottom - edge) this.container.scrollTop += Math.ceil((y - (box.bottom - edge)) / 3);
  }
}
