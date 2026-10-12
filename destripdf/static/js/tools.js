// Outils d'édition : sélection, modification du texte, texte libre, notes, surlignage,
// dessin, formes, effacement, placement de la signature et de la signature manuscrite.

import { Api } from './api.js';
import { el, iconEl, toast, formatDate, clamp } from './ui.js';
import { Viewer, BASE } from './viewer.js';

// `short` : libellé de la barre d'outils ; `label` : nom complet (infobulle, barre d'options).
export const TOOLS = [
  { id: 'select', short: 'Sélection', label: 'Sélection', icon: 'select', key: 'v' },
  { id: 'edit', short: 'Modifier', label: 'Modifier le texte', icon: 'edit', key: 'e' },
  { id: 'text', short: 'Texte', label: 'Ajouter du texte', icon: 'text', key: 't' },
  { id: 'note', short: 'Note', label: 'Note', icon: 'note', key: 'n' },
  { id: 'highlight', short: 'Surligner', label: 'Surligner', icon: 'highlight', key: 'h' },
  { id: 'draw', short: 'Dessin', label: 'Dessiner', icon: 'draw', key: 'd' },
  { id: 'shape', short: 'Formes', label: 'Formes', icon: 'shape', key: 'r' },
  { id: 'erase', short: 'Effacer', label: 'Effacer une zone', icon: 'erase', key: 'x' },
];

const MODES = ['select', 'edit', 'text', 'note', 'highlight', 'draw', 'shape', 'erase', 'sign', 'stamp'];

const COLORS = {
  highlight: [['#f5d04a', 'Jaune'], ['#9fe08a', 'Vert'], ['#8fd3f4', 'Bleu'], ['#f7a8c6', 'Rose'], ['#f6b26b', 'Orange']],
  pen: [['#c0392b', 'Rouge'], ['#1f5fa8', 'Bleu'], ['#29323a', 'Noir'], ['#287a5d', 'Vert'], ['#a95d37', 'Cuivre']],
  text: [['#000000', 'Noir'], ['#1f5fa8', 'Bleu'], ['#c0392b', 'Rouge'], ['#287a5d', 'Vert']],
  note: [['#f5d04a', 'Jaune'], ['#9fe08a', 'Vert'], ['#8fd3f4', 'Bleu'], ['#f7a8c6', 'Rose']],
};

const DEFAULT_OPTS = {
  hlType: 'highlight', hlColor: '#f5d04a',
  penColor: '#c0392b', penWidth: 2,
  shape: 'rect', shapeColor: '#c0392b', shapeWidth: 2,
  textSize: 12, textColor: '#000000',
  noteColor: '#f5d04a',
};

function loadOpts() {
  try {
    const raw = JSON.parse(localStorage.getItem('destripdf.tools') || '{}');
    return { ...DEFAULT_OPTS, ...(raw && typeof raw === 'object' ? raw : {}) };
  } catch {
    return { ...DEFAULT_OPTS };
  }
}

function saveOpts(opts) {
  try {
    localStorage.setItem('destripdf.tools', JSON.stringify(opts));
  } catch {
    /* stockage indisponible : réglages de la session seulement */
  }
}

export class ToolManager extends EventTarget {
  constructor(app) {
    super();
    this.app = app;
    this.viewer = app.viewer;
    this.tool = 'select';
    this.opts = loadOpts();
    this.selected = null; // { page, id }
    this.press = null; // geste en cours
    this.free = null; // éditeur de texte libre ouvert
    this.popover = null;
    this.annotBar = null;
    this.signFrame = null; // { page, rect }
    const root = this.viewer.container;
    root.addEventListener('pointerdown', (e) => this.onPointerDown(e));
    root.addEventListener('dblclick', (e) => this.onDoubleClick(e));
    window.addEventListener('pointermove', (e) => this.onPointerMove(e));
    window.addEventListener('pointerup', (e) => this.onPointerUp(e));
    this.viewer.addEventListener('annotsready', (e) => this.buildPageOverlays(e.detail.page));
    this.viewer.addEventListener('structure', () => { this.deselect(); this.signFrame = null; this.dispatchEvent(new CustomEvent('signframe')); });
    this.viewer.addEventListener('zoomchange', () => this.onZoom());
  }

  // --- Choix de l'outil ---

  set(tool) {
    if (!MODES.includes(tool)) tool = 'select';
    this.cancelTransient();
    if (this.app.editor.isOpen) this.app.editor.commit();
    this.tool = tool;
    document.body.classList.remove(...MODES.map((m) => `mode-${m}`));
    document.body.classList.add(`mode-${tool}`);
    for (const button of document.querySelectorAll('#tools .tool')) {
      button.setAttribute('aria-pressed', String(button.dataset.tool === tool));
    }
    if (tool !== 'select') this.deselect();
    this.renderOptions();
    this.updateHints();
    this.dispatchEvent(new CustomEvent('toolchange', { detail: { tool } }));
  }

  cancelTransient() {
    if (this.free) this.closeFree(false);
    if (this.popover) this.closePopover();
    if (this.press?.preview) this.press.preview.remove();
    this.press = null;
  }

  onZoom() {
    if (this.app.editor.isOpen) this.app.editor.close();
    if (this.free) this.closeFree(true);
    if (this.popover) this.closePopover();
    this.placeSignFrame();
    this.placeAnnotBar();
  }

  // --- Barre d'options ---

  renderOptions() {
    const bar = document.getElementById('options-bar');
    bar.textContent = '';
    const o = this.opts;
    const add = (...nodes) => bar.append(...nodes);
    const group = (label, ...nodes) => el('div', { class: 'opt-group' }, el('span', { class: 'opt-label', text: label }), ...nodes);
    const swatches = (palette, key) => palette.map(([color, name]) => {
      const button = el('button', { class: 'swatch', type: 'button', 'aria-pressed': String(o[key] === color), 'aria-label': name, 'data-tip': name });
      button.style.background = color;
      button.addEventListener('click', () => { o[key] = color; saveOpts(o); this.renderOptions(); });
      return button;
    });
    const seg = (items, key) => {
      const wrap = el('div', { class: 'seg', role: 'group' });
      for (const [value, label, iconName] of items) {
        const button = el('button', { type: 'button', 'aria-pressed': String(o[key] === value) }, iconName ? iconEl(iconName) : null, el('span', { text: label }));
        button.addEventListener('click', () => { o[key] = value; saveOpts(o); this.renderOptions(); });
        wrap.append(button);
      }
      return wrap;
    };
    const widths = (key) => seg([[1, 'Fin'], [2, 'Moyen'], [4, 'Épais']], key);
    const hint = (text) => el('span', { class: 'opt-hint', text });
    const names = { sign: 'Cadre de signature', stamp: 'Signature manuscrite' };
    const name = names[this.tool] || TOOLS.find((t) => t.id === this.tool)?.label;
    if (this.tool !== 'select' && name) {
      const done = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', 'data-tip': 'Revenir à la sélection (Échap)', text: 'Terminé' });
      done.addEventListener('click', () => this.set('select'));
      add(el('span', { class: 'opt-title', text: name }));
      bar.dataset.done = '1';
      this._doneButton = done;
    } else {
      this._doneButton = null;
    }

    switch (this.tool) {
      case 'edit':
        add(hint(''));
        bar.lastChild.append('Cliquez sur une ligne. ', el('kbd', { text: 'Entrée' }), ' valide, ', el('kbd', { text: 'Échap' }), ' annule, ', el('kbd', { text: 'Tab' }), ' passe à la suivante.');
        break;
      case 'text': {
        const size = el('input', { class: 'num-input', type: 'number', min: '4', max: '144', step: '1', value: String(o.textSize), 'aria-label': 'Taille du texte' });
        size.addEventListener('change', () => { const v = Number(size.value); if (v >= 4 && v <= 144) { o.textSize = v; saveOpts(o); } });
        add(group('Taille', size), group('Couleur', ...swatches(COLORS.text, 'textColor')), hint("Cliquez à l'endroit où écrire. Ctrl+Entrée valide."));
        break;
      }
      case 'note':
        add(group('Couleur', ...swatches(COLORS.note, 'noteColor')), hint('Cliquez pour placer une note.'));
        break;
      case 'highlight':
        add(group('Marque', seg([['highlight', 'Surligner'], ['underline', 'Souligner'], ['strikeout', 'Barrer']], 'hlType')),
          group('Couleur', ...swatches(COLORS.highlight.concat([['#c0392b', 'Rouge']]), 'hlColor')),
          hint('Sélectionnez le texte à marquer.'));
        break;
      case 'draw':
        add(group('Couleur', ...swatches(COLORS.pen, 'penColor')), group('Trait', widths('penWidth')), hint('Dessinez à main levée.'));
        break;
      case 'shape':
        add(group('Forme', seg([['rect', 'Rectangle', 'rect'], ['ellipse', 'Ellipse', 'ellipse'], ['arrow', 'Flèche', 'arrow']], 'shape')),
          group('Couleur', ...swatches(COLORS.pen, 'shapeColor')), group('Trait', widths('shapeWidth')), hint('Tracez la forme sur la page.'));
        break;
      case 'erase':
        add(hint('Tracez un cadre : texte, images et tracés recouverts sont supprimés. Ctrl+Z pour annuler.'));
        break;
      case 'sign':
        add(hint('Tracez le cadre de la signature, ou cliquez pour le placer.'));
        break;
      case 'stamp':
        add(hint('Cliquez ou tracez un cadre pour apposer votre signature manuscrite.'));
        break;
      default:
        break;
    }
    if (this._doneButton) add(this._doneButton);
    bar.hidden = !bar.childNodes.length;
  }

  // Indication sur les pages sans texte en mode « Modifier le texte ».
  updateHints() {
    for (const view of this.viewer.views) this.pageHint(view);
  }

  pageHint(view) {
    view.el.querySelector('.page-hint')?.remove();
    if (this.tool !== 'edit' || !view.textData) return;
    if (view.textData.lines.length === 0) {
      view.el.append(el('div', { class: 'page-hint', text: 'Aucun texte modifiable : page numérisée. Utilisez « Effacer une zone » puis « Ajouter du texte ».' }));
    }
  }

  // --- Calques d'annotations et de champs ---

  buildPageOverlays(view) {
    this.buildAnnots(view);
    this.buildFields(view);
    this.pageHint(view);
    if (this.selected && this.selected.page === view.index) {
      const still = view.annotData?.annots.some((a) => a.id === this.selected.id);
      if (still) this.highlightSelected();
      else this.deselect();
    }
  }

  buildAnnots(view) {
    const layer = view.layers.annot;
    layer.textContent = '';
    for (const annot of view.annotData?.annots || []) {
      if (annot.type === 'Popup' || annot.type === 'Link') continue;
      const node = el('div', { class: `annot-hit${annot.movable ? ' movable' : ''}`, dataset: { id: String(annot.id), type: annot.type } });
      const [x0, y0, x1, y1] = annot.rect;
      const pad = annot.type === 'Line' || annot.type === 'Ink' ? 2 : 0;
      Viewer.layerStyle(node, [x0 - pad, y0 - pad, x1 + pad, y1 + pad]);
      if (annot.type === 'Text' && (annot.content || annot.author)) {
        node.dataset.tip = `${annot.author ? `${annot.author} : ` : ''}${annot.content || ''}`.slice(0, 400);
      }
      layer.append(node);
    }
  }

  buildFields(view) {
    const layer = view.layers.field;
    layer.textContent = '';
    for (const field of view.annotData?.fields || []) {
      if (field.readonly) continue;
      const [x0, y0, x1, y1] = field.rect;
      const height = (y1 - y0) * BASE;
      let node;
      if (field.type === 'CheckBox' || field.type === 'RadioButton') {
        const frame = el('div', { class: 'field-check-frame' });
        Viewer.layerStyle(frame, field.rect);
        node = el('input', { class: 'field-check', type: 'checkbox', 'aria-label': field.label || field.name });
        node.checked = Boolean(field.checked);
        Viewer.layerStyle(node, field.rect);
        node.addEventListener('change', () => this.setField(view, field, node.checked));
        layer.append(frame);
      } else if (field.type === 'ComboBox' || field.type === 'ListBox') {
        node = el('select', { class: 'field-input', 'aria-label': field.label || field.name });
        for (const choice of field.choices || []) node.append(el('option', { value: choice, text: choice }));
        node.value = field.value || '';
        Viewer.layerStyle(node, field.rect);
        node.style.fontSize = `${Math.min(height * 0.62, 13 * BASE)}px`;
        node.addEventListener('change', () => this.setField(view, field, node.value));
      } else if (field.type === 'Text') {
        node = el(field.multiline ? 'textarea' : 'input', { class: 'field-input', 'aria-label': field.label || field.name, spellcheck: 'false' });
        node.value = field.value || '';
        Viewer.layerStyle(node, field.rect);
        const size = field.fontsize > 0 ? field.fontsize * BASE : Math.min(height * 0.66, 12 * BASE);
        node.style.fontSize = `${size}px`;
        const commit = () => { if (node.value !== (field.value || '')) this.setField(view, field, node.value); };
        node.addEventListener('change', commit);
        node.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' && !field.multiline) { event.preventDefault(); node.blur(); }
          if (event.key === 'Escape') { node.value = field.value || ''; node.blur(); }
        });
      } else {
        continue;
      }
      node.dataset.fieldId = String(field.id);
      layer.append(node);
    }
  }

  async setField(view, field, value) {
    try {
      const data = await Api.post('api/field', { page: view.index, id: field.id, value });
      await this.app.applyDoc(data.doc);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // --- Sélection d'une annotation ---

  selectAnnot(page, id) {
    this.selected = { page, id };
    this.highlightSelected();
    this.dispatchEvent(new CustomEvent('selection', { detail: this.selected }));
  }

  annotData(page, id) {
    return this.viewer.views[page]?.annotData?.annots.find((a) => a.id === id) || null;
  }

  highlightSelected() {
    document.querySelectorAll('.annot-hit.selected').forEach((n) => n.classList.remove('selected'));
    if (!this.selected) return;
    const view = this.viewer.views[this.selected.page];
    const node = view?.layers.annot.querySelector(`.annot-hit[data-id="${this.selected.id}"]`);
    if (node) node.classList.add('selected');
    this.showAnnotBar();
  }

  deselect() {
    this.selected = null;
    document.querySelectorAll('.annot-hit.selected').forEach((n) => n.classList.remove('selected'));
    this.annotBar?.remove();
    this.annotBar = null;
    this.viewer.views.forEach((v) => v.el.classList.remove('raised'));
  }

  showAnnotBar() {
    this.annotBar?.remove();
    const annot = this.selected && this.annotData(this.selected.page, this.selected.id);
    if (!annot) return;
    const view = this.viewer.views[this.selected.page];
    const bar = el('div', { class: 'annot-bar', role: 'toolbar', 'aria-label': annot.label });
    if (['Text', 'FreeText'].includes(annot.type) || annot.editable) {
      const edit = el('button', { class: 'icon-btn', type: 'button', 'data-tip': annot.type === 'FreeText' ? 'Modifier le texte' : 'Modifier le commentaire' }, iconEl('pen'), el('span', { class: 'sr-only', text: 'Modifier' }));
      edit.addEventListener('click', () => this.editAnnotContent(view, annot));
      bar.append(edit);
    }
    const remove = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Supprimer (Suppr)' }, iconEl('trash'), el('span', { class: 'sr-only', text: 'Supprimer' }));
    remove.addEventListener('click', () => this.deleteSelected());
    bar.append(remove);
    view.layers.tool.append(bar);
    view.el.classList.add('raised');
    this.annotBar = bar;
    this.placeAnnotBar();
  }

  placeAnnotBar() {
    if (!this.annotBar || !this.selected) return;
    const annot = this.annotData(this.selected.page, this.selected.id);
    if (!annot) return;
    const s = this.viewer.scale;
    const [x0, y0, x1] = annot.rect;
    const top = y0 * s - 42;
    this.annotBar.style.left = `${Math.max(0, x1 * s - 70)}px`;
    this.annotBar.style.top = `${top < -30 ? annot.rect[3] * s + 6 : top}px`;
  }

  async deleteSelected() {
    if (!this.selected) return;
    const { page, id } = this.selected;
    this.deselect();
    try {
      const data = await Api.post('api/annot/delete', { page, id });
      await this.app.applyDoc(data.doc);
      toast('Annotation supprimée.', 'ok', { action: 'Annuler', onAction: () => this.app.undo() });
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  editAnnotContent(view, annot) {
    const s = this.viewer.scale;
    const [x0, , , y1] = annot.rect;
    const title = annot.type === 'FreeText' ? 'Texte' : annot.type === 'Text' ? 'Note' : `Commentaire — ${annot.label}`;
    this.openPopover(view, { x: x0 * s, y: y1 * s + 6 }, {
      title,
      meta: [annot.author, formatDate(annot.modified)].filter(Boolean).join(' · '),
      value: annot.content,
      confirm: 'Enregistrer',
      onConfirm: async (value) => {
        const data = await Api.post('api/annot/update', { page: view.index, id: annot.id, changes: { content: value } });
        await this.app.applyDoc(data.doc);
      },
    });
  }

  // --- Gestes ---

  eventPage(event) {
    const pageEl = event.target.closest?.('.page');
    if (!pageEl) return null;
    return this.viewer.views[Number(pageEl.dataset.index)] || null;
  }

  onPointerDown(event) {
    if (event.button !== 0) return;
    const view = this.eventPage(event);
    if (!view) {
      if (this.tool === 'select') this.deselect();
      return;
    }
    if (event.target.closest('.te-box, .te-bar, .free-editor, .popover, .annot-bar, .field-input, .field-check')) return;
    const point = this.viewer.pointInView(view, event.clientX, event.clientY);
    switch (this.tool) {
      case 'select': {
        const hit = event.target.closest('.annot-hit');
        if (!hit) {
          this.deselect();
          return;
        }
        event.preventDefault();
        const id = Number(hit.dataset.id);
        this.selectAnnot(view.index, id);
        const annot = this.annotData(view.index, id);
        if (annot?.movable) {
          hit.setPointerCapture?.(event.pointerId);
          this.press = { kind: 'move', view, hit, startX: event.clientX, startY: event.clientY, moved: false, annot };
        }
        return;
      }
      case 'edit': {
        event.preventDefault();
        const editor = this.app.editor;
        const seg = event.target.closest('.tl-seg');
        if (!seg) {
          if (editor.isOpen) editor.commit();
          return;
        }
        const line = view.textData?.lines.find((l) => String(l.id) === seg.dataset.line);
        if (!line) return;
        if (editor.isOpen) {
          // Valider la ligne en cours ; n'ouvrir la suivante que si la validation a réussi.
          editor.commit().then(() => { if (!editor.isOpen) editor.open(view, line, event); });
        } else {
          editor.open(view, line, event);
        }
        return;
      }
      case 'highlight':
        this.press = { kind: 'highlight', view, startX: event.clientX, startY: event.clientY, start: point };
        return;
      case 'text':
        event.preventDefault();
        if (this.free) {
          this.closeFree(true);
          return;
        }
        this.openFree(view, point);
        return;
      case 'note':
        event.preventDefault();
        if (this.popover) {
          this.closePopover();
          return;
        }
        this.openNote(view, point);
        return;
      case 'draw': {
        event.preventDefault();
        const svg = this.svgOverlay(view);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', this.opts.penColor);
        path.setAttribute('stroke-width', String(this.opts.penWidth * this.viewer.scale));
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        svg.append(path);
        event.target.setPointerCapture?.(event.pointerId);
        this.press = { kind: 'draw', view, points: [[point.x, point.y]], svg, path };
        this.drawPath();
        return;
      }
      case 'shape':
      case 'erase':
      case 'sign':
      case 'stamp': {
        event.preventDefault();
        event.target.setPointerCapture?.(event.pointerId);
        let preview;
        if (this.tool === 'shape' && this.opts.shape === 'arrow') {
          const svg = this.svgOverlay(view);
          preview = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          preview.setAttribute('stroke', this.opts.shapeColor);
          preview.setAttribute('stroke-width', String(this.opts.shapeWidth * this.viewer.scale));
          preview.setAttribute('stroke-linecap', 'round');
          svg.append(preview);
          preview._svg = svg;
        } else {
          preview = el('div', { class: `draft-rect${this.tool === 'erase' ? ' erase' : ''}` });
          if (this.tool === 'shape') {
            preview.style.borderStyle = 'solid';
            preview.style.borderColor = this.opts.shapeColor;
            preview.style.borderWidth = `${Math.max(1, this.opts.shapeWidth * this.viewer.scale)}px`;
            preview.style.background = 'transparent';
            if (this.opts.shape === 'ellipse') preview.style.borderRadius = '50%';
          }
          view.layers.tool.append(preview);
        }
        this.press = { kind: this.tool, view, start: point, end: point, preview };
        this.updateDraft();
        return;
      }
      default:
        break;
    }
  }

  onPointerMove(event) {
    const press = this.press;
    if (!press) return;
    if (press.kind === 'move') {
      const dx = event.clientX - press.startX;
      const dy = event.clientY - press.startY;
      if (!press.moved && Math.hypot(dx, dy) < 3) return;
      press.moved = true;
      press.hit.classList.add('dragging');
      const k = BASE / this.viewer.scale;
      press.hit.style.transform = `translate(${dx * k}px, ${dy * k}px)`;
      return;
    }
    if (press.kind === 'draw') {
      const p = this.viewer.pointInView(press.view, event.clientX, event.clientY);
      const last = press.points[press.points.length - 1];
      if (Math.hypot(p.x - last[0], p.y - last[1]) * this.viewer.scale < 1.2) return;
      press.points.push([p.x, p.y]);
      this.drawPath();
      return;
    }
    if (['shape', 'erase', 'sign', 'stamp'].includes(press.kind)) {
      press.end = this.viewer.pointInView(press.view, event.clientX, event.clientY);
      this.updateDraft();
    }
  }

  async onPointerUp(event) {
    const press = this.press;
    if (!press) return;
    this.press = null;
    const view = press.view;
    try {
      if (press.kind === 'move') {
        press.hit.classList.remove('dragging');
        if (!press.moved) return;
        const dx = (event.clientX - press.startX) / this.viewer.scale;
        const dy = (event.clientY - press.startY) / this.viewer.scale;
        const data = await Api.post('api/annot/update', { page: view.index, id: press.annot.id, changes: { offset: [dx, dy] } });
        await this.app.applyDoc(data.doc, { waitPage: view.index });
        press.hit.style.transform = '';
        return;
      }
      if (press.kind === 'highlight') {
        await this.finishHighlight(press, event);
        return;
      }
      if (press.kind === 'draw') {
        if (press.points.length < 2) {
          press.svg.remove();
          return;
        }
        const data = await Api.post('api/annot/add', {
          page: view.index,
          annot: { type: 'ink', strokes: [press.points.map(([x, y]) => [round(x), round(y)])], color: this.opts.penColor, width: this.opts.penWidth },
        });
        await this.app.applyDoc(data.doc, { waitPage: view.index });
        press.svg.remove();
        return;
      }
      const rect = normRect(press.start, press.end);
      const small = (rect[2] - rect[0]) < 4 && (rect[3] - rect[1]) < 4;
      if (press.preview?._svg) press.preview._svg.remove();
      else press.preview?.remove();
      if (press.kind === 'shape') {
        if (small) return;
        const annot = this.opts.shape === 'arrow'
          ? { type: 'arrow', from: [round(press.start.x), round(press.start.y)], to: [round(press.end.x), round(press.end.y)] }
          : { type: this.opts.shape, rect: rect.map(round) };
        Object.assign(annot, { color: this.opts.shapeColor, width: this.opts.shapeWidth });
        const data = await Api.post('api/annot/add', { page: view.index, annot });
        await this.app.applyDoc(data.doc, { waitPage: view.index });
      } else if (press.kind === 'erase') {
        if (small) return;
        const data = await Api.post('api/erase', { page: view.index, rect: rect.map(round) });
        await this.app.applyDoc(data.doc, { waitPage: view.index });
        toast('Zone effacée.', 'ok', { action: 'Annuler', onAction: () => this.app.undo() });
      } else if (press.kind === 'sign') {
        const frame = small ? this.defaultRect(view, press.start, 200, 64) : rect;
        if (!small && ((frame[2] - frame[0]) < 40 || (frame[3] - frame[1]) < 18)) {
          toast('Cadre trop petit : tracez au moins 40 × 18 points, ou cliquez simplement.', 'error');
          return;
        }
        this.setSignFrame(view.index, frame.map(round));
      } else if (press.kind === 'stamp') {
        const frame = small ? this.defaultRect(view, press.start, 170, 60) : rect;
        const data = await Api.post('api/annot/add', { page: view.index, annot: { type: 'stamp_image', rect: frame.map(round) } });
        await this.app.applyDoc(data.doc, { waitPage: view.index });
        this.set('select');
      }
    } catch (err) {
      toast(err.message, 'error');
      if (press.svg) press.svg.remove();
      if (press.hit) {
        press.hit.classList.remove('dragging');
        press.hit.style.transform = '';
      }
    }
  }

  onDoubleClick(event) {
    if (this.tool !== 'select') return;
    const hit = event.target.closest('.annot-hit');
    const view = this.eventPage(event);
    if (!hit || !view) return;
    const annot = this.annotData(view.index, Number(hit.dataset.id));
    if (annot && (annot.type === 'Text' || annot.type === 'FreeText' || annot.editable)) {
      event.preventDefault();
      this.editAnnotContent(view, annot);
    }
  }

  defaultRect(view, center, w, h) {
    const x0 = clamp(center.x - w / 2, 0, Math.max(0, view.w - w));
    const y0 = clamp(center.y - h / 2, 0, Math.max(0, view.h - h));
    return [x0, y0, Math.min(view.w, x0 + w), Math.min(view.h, y0 + h)];
  }

  svgOverlay(view) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'draft-svg');
    view.layers.tool.append(svg);
    return svg;
  }

  drawPath() {
    const { path, points } = this.press;
    const s = this.viewer.scale;
    path.setAttribute('points', points.map(([x, y]) => `${(x * s).toFixed(1)},${(y * s).toFixed(1)}`).join(' '));
  }

  updateDraft() {
    const press = this.press;
    const s = this.viewer.scale;
    if (press.preview?._svg) {
      press.preview.setAttribute('x1', String(press.start.x * s));
      press.preview.setAttribute('y1', String(press.start.y * s));
      press.preview.setAttribute('x2', String(press.end.x * s));
      press.preview.setAttribute('y2', String(press.end.y * s));
      return;
    }
    this.viewer.placeInTool(press.preview, press.view, normRect(press.start, press.end));
  }

  async finishHighlight(press, event) {
    const view = press.view;
    const selection = window.getSelection();
    const kind = this.opts.hlType;
    const byPage = new Map();
    if (selection && !selection.isCollapsed && selection.rangeCount) {
      for (let i = 0; i < selection.rangeCount; i += 1) {
        const range = selection.getRangeAt(i);
        for (const r of range.getClientRects()) {
          if (r.width < 1 || r.height < 1) continue;
          const hit = this.viewer.pageAtClient(r.left + r.width / 2, r.top + r.height / 2);
          if (!hit) continue;
          const p0 = this.viewer.pointInView(hit.view, r.left, r.top);
          const p1 = this.viewer.pointInView(hit.view, r.right, r.bottom);
          if (!byPage.has(hit.index)) byPage.set(hit.index, []);
          byPage.get(hit.index).push([p0.x, p0.y, p1.x, p1.y]);
        }
      }
      selection.removeAllRanges();
    } else if (Math.hypot(event.clientX - press.startX, event.clientY - press.startY) > 6) {
      const end = this.viewer.pointInView(view, event.clientX, event.clientY);
      byPage.set(view.index, [normRect(press.start, end)]);
    }
    if (!byPage.size) return;
    let last = null;
    for (const [page, rects] of byPage) {
      const merged = mergeLineRects(rects);
      if (!merged.length) continue;
      last = await Api.post('api/annot/add', { page, annot: { type: kind, rects: merged.map((r) => r.map(round)), color: this.opts.hlColor } });
    }
    if (last) await this.app.applyDoc(last.doc, { waitPage: view.index });
  }

  // --- Texte libre ---

  openFree(view, point) {
    const s = this.viewer.scale;
    const size = this.opts.textSize;
    const area = el('textarea', { class: 'free-editor', rows: '1', spellcheck: 'true', 'aria-label': 'Texte à ajouter', placeholder: 'Votre texte' });
    area.style.left = `${point.x * s}px`;
    area.style.top = `${(point.y - size * 0.62) * s}px`;
    area.style.fontSize = `${size * s}px`;
    area.style.color = this.opts.textColor;
    view.layers.tool.append(area);
    view.el.classList.add('raised');
    const grow = () => {
      area.style.height = 'auto';
      area.style.height = `${area.scrollHeight + 2}px`;
      area.style.width = 'auto';
      area.style.width = `${Math.max(160, area.scrollWidth + 8)}px`;
    };
    area.addEventListener('input', grow);
    area.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); this.closeFree(false); }
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); this.closeFree(true); }
    });
    this.free = { view, area, size, color: this.opts.textColor, onOutside: null };
    this.free.onOutside = (event) => {
      if (!this.free || area.contains(event.target)) return;
      if (event.target.closest?.('.tool-layer') && this.tool === 'text') return; // traité par onPointerDown
      this.closeFree(true);
    };
    document.addEventListener('pointerdown', this.free.onOutside, true);
    grow();
    area.focus();
  }

  async closeFree(commit) {
    const free = this.free;
    if (!free) return;
    this.free = null;
    document.removeEventListener('pointerdown', free.onOutside, true);
    const { view, area, size, color } = free;
    const text = area.value.replace(/\s+$/, '');
    const s = this.viewer.scale;
    const rect = [
      area.offsetLeft / s,
      area.offsetTop / s,
      (area.offsetLeft + area.offsetWidth) / s + 4,
      (area.offsetTop + area.offsetHeight) / s + 2,
    ];
    if (!commit || !text.trim()) {
      area.remove();
      view.el.classList.remove('raised');
      return;
    }
    area.disabled = true;
    try {
      const data = await Api.post('api/annot/add', { page: view.index, annot: { type: 'freetext', rect: rect.map(round), content: text, fontsize: size, color } });
      await this.app.applyDoc(data.doc, { waitPage: view.index });
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      area.remove();
      view.el.classList.remove('raised');
    }
  }

  // --- Notes ---

  openNote(view, point) {
    const s = this.viewer.scale;
    this.openPopover(view, { x: point.x * s + 10, y: point.y * s + 10 }, {
      title: 'Nouvelle note',
      meta: this.app.settings?.author || '',
      value: '',
      confirm: 'Ajouter',
      onConfirm: async (value) => {
        if (!value.trim()) return;
        const data = await Api.post('api/annot/add', {
          page: view.index,
          annot: { type: 'note', point: [round(point.x - 8), round(point.y - 8)], content: value, color: this.opts.noteColor },
        });
        await this.app.applyDoc(data.doc, { waitPage: view.index });
      },
    });
  }

  openPopover(view, pos, { title, meta = '', value = '', confirm = 'Enregistrer', onConfirm }) {
    this.closePopover();
    const area = el('textarea', { 'aria-label': title, spellcheck: 'true' });
    area.value = value;
    const cancelBtn = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Annuler' });
    const okBtn = el('button', { class: 'btn btn-primary btn-sm', type: 'button', text: confirm });
    const pop = el('div', { class: 'popover', role: 'dialog', 'aria-label': title },
      el('div', { class: 'popover-head' }, el('span', { class: 'popover-title', text: title }), el('span', { class: 'popover-meta', text: meta })),
      area,
      el('div', { class: 'popover-actions' }, cancelBtn, okBtn));
    view.layers.tool.append(pop);
    view.el.classList.add('raised');
    const maxLeft = view.el.clientWidth - 280;
    pop.style.left = `${clamp(pos.x, 0, Math.max(0, maxLeft))}px`;
    pop.style.top = `${clamp(pos.y, 0, Math.max(0, view.el.clientHeight - 170))}px`;
    const submit = async () => {
      okBtn.disabled = true;
      try {
        await onConfirm(area.value);
        this.closePopover();
      } catch (err) {
        okBtn.disabled = false;
        toast(err.message, 'error');
      }
    };
    okBtn.addEventListener('click', submit);
    cancelBtn.addEventListener('click', () => this.closePopover());
    area.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); this.closePopover(); }
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); submit(); }
    });
    const onOutside = (event) => { if (!pop.contains(event.target)) this.closePopover(); };
    setTimeout(() => document.addEventListener('pointerdown', onOutside, true), 0);
    this.popover = { pop, view, onOutside };
    area.focus();
  }

  closePopover() {
    if (!this.popover) return;
    const { pop, view, onOutside } = this.popover;
    document.removeEventListener('pointerdown', onOutside, true);
    pop.remove();
    view.el.classList.remove('raised');
    this.popover = null;
  }

  // --- Cadre de signature ---

  setSignFrame(page, rect) {
    this.signFrame = { page, rect };
    this.placeSignFrame();
    this.dispatchEvent(new CustomEvent('signframe', { detail: this.signFrame }));
  }

  clearSignFrame() {
    this.signFrame = null;
    document.querySelectorAll('.sig-frame').forEach((n) => n.remove());
    this.dispatchEvent(new CustomEvent('signframe', { detail: null }));
  }

  placeSignFrame() {
    document.querySelectorAll('.sig-frame').forEach((n) => n.remove());
    if (!this.signFrame) return;
    const view = this.viewer.views[this.signFrame.page];
    if (!view) return;
    const node = el('div', { class: 'sig-frame', text: 'Signature' });
    this.viewer.placeInTool(node, view, this.signFrame.rect);
    view.layers.tool.append(node);
  }
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function normRect(a, b) {
  return [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)];
}

// Fusionne les rectangles d'une même ligne (sélection de texte) en un seul par ligne.
function mergeLineRects(rects) {
  const sorted = rects.filter((r) => r[2] - r[0] > 0.5 && r[3] - r[1] > 0.5).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const out = [];
  for (const r of sorted) {
    const prev = out[out.length - 1];
    const sameLine = prev && Math.abs(prev[1] - r[1]) < 2.5 && Math.abs(prev[3] - r[3]) < 2.5 && r[0] <= prev[2] + 4;
    if (sameLine) {
      prev[0] = Math.min(prev[0], r[0]);
      prev[2] = Math.max(prev[2], r[2]);
      prev[1] = Math.min(prev[1], r[1]);
      prev[3] = Math.max(prev[3], r[3]);
    } else {
      out.push([...r]);
    }
  }
  return out;
}
