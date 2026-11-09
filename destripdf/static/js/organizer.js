// Vue « Organiser les pages » : toutes les pages en grille, sélection multiple,
// déplacement par glisser, ajout de PDF (bouton ou dépôt depuis l'Explorateur),
// rotation et suppression. Les vignettes à gauche gardent les mêmes gestes.

import { el, iconEl, showMenu } from './ui.js';
import { PageSorter } from './pagesorter.js';

const SIZES = { s: 116, m: 160, l: 224 }; // largeur des cases, en pixels CSS
const SIZE_KEY = 'destripdf.organizer.size';

export class Organizer {
  constructor(app) {
    this.app = app;
    this.root = document.getElementById('organizer');
    this.bar = document.getElementById('org-bar');
    this.scroller = document.getElementById('org-scroll');
    this.grid = document.getElementById('org-grid');
    this.items = [];
    this.size = 'm';
    try { this.size = SIZES[localStorage.getItem(SIZE_KEY)] ? localStorage.getItem(SIZE_KEY) : 'm'; } catch { /* sans stockage */ }
    this.io = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) this.loadThumb(Number(entry.target.dataset.index));
    }, { root: this.scroller, rootMargin: '400px 0px' });
    this.sorter = new PageSorter(this.scroller, app.pageSelection, {
      layout: 'grid',
      item: '.org-card',
      clearOnEmpty: true,
      onOpen: (index) => this.openPage(index),
      onMove: (pages, before) => app.movePagesTo(pages, before),
      onFiles: (files, before) => app.addFiles(files, before),
      onDelete: (pages) => app.deletePages(pages),
      onContext: (index, node, pages) => this.contextMenu(index, node, pages),
    });
    app.pageSelection.addEventListener('change', () => { if (this.isOpen) this.renderBar(); });
  }

  get isOpen() {
    return !this.root.hidden;
  }

  open() {
    const doc = this.app.doc;
    if (!doc || this.isOpen) return;
    this.app.editor.close();
    this.app.tools.set('select');
    this.app.tools.deselect();
    this.root.hidden = false;
    document.body.classList.add('organizing');
    document.getElementById('btn-organize').setAttribute('aria-pressed', 'true');
    this.render(doc);
    const selection = this.app.pageSelection.list();
    this.sorter.focusItem(selection.length ? selection[0] : this.app.viewer.current);
  }

  close({ page = null } = {}) {
    if (!this.isOpen) return;
    this.root.hidden = true;
    document.body.classList.remove('organizing');
    document.getElementById('btn-organize').setAttribute('aria-pressed', 'false');
    this.io.disconnect();
    this.grid.textContent = '';
    this.items = [];
    const selection = this.app.pageSelection.list();
    const target = page ?? (selection.length ? selection[0] : null);
    if (target !== null && this.app.doc) this.app.viewer.scrollToPage(target);
    document.getElementById('viewer').focus();
  }

  toggle() {
    if (this.isOpen) this.close();
    else this.open();
  }

  openPage(index) {
    this.app.pageSelection.only(index);
    this.close({ page: index });
  }

  // --- Barre ---

  // Barre construite une fois ; seuls l'état des boutons et le compte changent ensuite
  // (le focus du clavier reste sur le bouton utilisé).
  buildBar() {
    const chosen = () => this.app.pageSelection.list();
    const button = (iconName, label, tip, action) => {
      const node = el('button', { class: 'icon-btn', type: 'button', 'data-tip': tip, 'data-needs-selection': '1' },
        iconEl(iconName), el('span', { class: 'sr-only', text: label }));
      node.addEventListener('click', () => { const pages = chosen(); if (pages.length) action(pages); });
      return node;
    };
    const add = el('button', { class: 'btn btn-secondary btn-sm', type: 'button', 'data-tip': 'PDF ou images, ajoutés à la fin du document (ou déposez-les entre deux pages)' },
      iconEl('addFiles'), el('span', { text: 'Ajouter des fichiers' }));
    add.addEventListener('click', () => this.app.addPdfs(this.app.doc ? this.app.doc.page_count : 0));
    this.status = el('span', { class: 'org-status', 'aria-live': 'polite', 'data-tip': 'Ctrl+clic ou Maj+clic pour choisir plusieurs pages, puis glissez-les pour les déplacer' });
    this.sizeButtons = {};
    const sizes = el('div', { class: 'seg', role: 'group', 'aria-label': 'Taille des vignettes' });
    for (const [id, label] of [['s', 'Petites'], ['m', 'Moyennes'], ['l', 'Grandes']]) {
      const b = el('button', { type: 'button', 'aria-pressed': 'false', text: label });
      b.addEventListener('click', () => this.setSize(id));
      this.sizeButtons[id] = b;
      sizes.append(b);
    }
    const done = el('button', { class: 'btn btn-primary btn-sm', type: 'button', 'data-tip': 'Revenir à la lecture (Échap)', text: 'Terminé' });
    done.addEventListener('click', () => this.close());
    this.bar.replaceChildren(
      el('span', { class: 'opt-title', text: 'Organiser les pages' }),
      add,
      el('div', { class: 'opt-group' },
        button('rotateLeft', 'Pivoter à gauche', 'Pivoter la sélection à gauche', (pages) => this.app.rotatePages(pages, -90)),
        button('rotate', 'Pivoter à droite', 'Pivoter la sélection à droite', (pages) => this.app.rotatePages(pages, 90)),
        button('trash', 'Supprimer', 'Supprimer la sélection (Suppr)', (pages) => this.app.deletePages(pages))),
      this.status,
      el('span', { class: 'opt-hint org-hint', text: 'Ctrl+clic ou Maj+clic : plusieurs pages · glisser : déplacer' }),
      el('div', { class: 'opt-group org-sizes' }, el('span', { class: 'opt-label', text: 'Vignettes' }), sizes),
      done,
    );
  }

  renderBar() {
    if (!this.status) this.buildBar();
    const count = this.app.doc ? this.app.doc.page_count : 0;
    const chosen = this.app.pageSelection.size;
    const plural = chosen > 1 ? 's' : '';
    this.status.textContent = chosen
      ? `${chosen} page${plural} sélectionnée${plural} sur ${count}`
      : `${count} page${count > 1 ? 's' : ''}`;
    for (const node of this.bar.querySelectorAll('[data-needs-selection]')) node.disabled = !chosen;
    for (const [id, node] of Object.entries(this.sizeButtons)) node.setAttribute('aria-pressed', String(this.size === id));
  }

  stepSize(direction) {
    const order = Object.keys(SIZES);
    const next = order[Math.max(0, Math.min(order.length - 1, order.indexOf(this.size) + direction))];
    if (next !== this.size) this.setSize(next);
  }

  setSize(size) {
    this.size = size;
    try { localStorage.setItem(SIZE_KEY, size); } catch { /* sans stockage */ }
    if (this.app.doc) this.render(this.app.doc);
    this.renderBar();
  }

  // --- Grille ---

  render(doc) {
    this.io.disconnect();
    const cell = SIZES[this.size];
    this.grid.style.setProperty('--org-cell', `${cell}px`);
    const box = { w: cell - 16, h: Math.round((cell - 16) * 1.3) };
    this.items = doc.pages.map((info, index) => {
      const fit = Math.min(box.w / info.w, box.h / info.h);
      const width = Math.max(1, Math.round(info.w * fit));
      const height = Math.max(1, Math.round(info.h * fit));
      const img = el('img', { class: 'org-img', alt: '', width: String(width), height: String(height), draggable: 'false' });
      const rotate = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Pivoter à droite' }, iconEl('rotate'), el('span', { class: 'sr-only', text: 'Pivoter à droite' }));
      rotate.addEventListener('click', () => this.app.rotatePages([index], 90));
      const remove = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Supprimer la page' }, iconEl('trash'), el('span', { class: 'sr-only', text: 'Supprimer la page' }));
      remove.addEventListener('click', () => this.app.deletePages([index]));
      const card = el('div', {
        class: 'org-card', role: 'option', tabindex: '-1', draggable: 'true', 'aria-selected': 'false',
        dataset: { index: String(index) }, 'aria-label': `Page ${index + 1}`,
      },
      el('div', { class: 'org-thumb' }, img, el('span', { class: 'org-check', 'aria-hidden': 'true' }, iconEl('check'))),
      el('span', { class: 'org-num', text: String(index + 1) }),
      el('div', { class: 'org-actions' }, rotate, remove));
      card.style.setProperty('--thumb-h', `${box.h}px`);
      return { card, img, v: -1, fit };
    });
    this.grid.replaceChildren(...this.items.map((item) => item.card));
    for (const item of this.items) this.io.observe(item.card);
    this.sorter.paint();
    this.renderBar();
  }

  update(doc, structural) {
    if (!this.isOpen) return;
    if (structural || this.items.length !== doc.page_count) {
      const top = this.scroller.scrollTop;
      this.render(doc);
      this.scroller.scrollTop = top;
      return;
    }
    doc.pages.forEach((info, i) => {
      const item = this.items[i];
      if (item && item.v !== info.v && item.v !== -1) this.loadThumb(i);
    });
    this.renderBar();
  }

  loadThumb(index) {
    const item = this.items[index];
    const info = this.app.doc?.pages[index];
    if (!item || !info || item.v === info.v) return;
    item.v = info.v;
    const scale = Math.round(item.fit * (window.devicePixelRatio || 1) * 1000) / 1000;
    item.img.src = `api/page/${index}/image?d=${this.app.doc.id}&s=${scale}&v=${info.v}`;
  }

  // Pages visées après un changement : choisies, visibles et sous le focus.
  reveal(start, count) {
    if (!this.isOpen) return;
    this.app.pageSelection.range(start, start + count - 1);
    this.app.pageSelection.anchor = start;
    this.sorter.focusItem(start);
  }

  contextMenu(index, node, pages) {
    const many = pages.length > 1;
    const label = (one, several) => (many ? `${several} (${pages.length} pages)` : one);
    showMenu(node, [
      { label: 'Ouvrir la page', icon: 'fitPage', action: () => this.openPage(index) },
      '-',
      { label: label('Pivoter à droite', 'Pivoter à droite'), icon: 'rotate', action: () => this.app.rotatePages(pages, 90) },
      { label: label('Pivoter à gauche', 'Pivoter à gauche'), icon: 'rotateLeft', action: () => this.app.rotatePages(pages, -90) },
      '-',
      { label: 'Insérer des fichiers avant', icon: 'insert', action: () => this.app.addPdfs(pages[0]) },
      { label: 'Insérer des fichiers après', icon: 'insert', action: () => this.app.addPdfs(pages[pages.length - 1] + 1) },
      '-',
      { label: label('Supprimer la page', 'Supprimer'), icon: 'trash', action: () => this.app.deletePages(pages) },
    ]);
  }
}
