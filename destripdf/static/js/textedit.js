// Éditeur d'une ligne de texte existante, posé exactement sur la ligne d'origine.
// Entrée valide, Échap annule, Tab valide puis passe à la ligne suivante.

import { Api } from './api.js';
import { el, iconEl, toast } from './ui.js';

const COMMON_FONTS = ['Arial', 'Calibri', 'Cambria', 'Century Gothic', 'Courier New', 'Garamond', 'Georgia', 'Segoe UI', 'Tahoma', 'Times New Roman', 'Trebuchet MS', 'Verdana'];
let installedFonts = null;

async function loadFonts() {
  if (installedFonts) return installedFonts;
  try {
    const data = await Api.get('api/fonts');
    installedFonts = data.families || [];
  } catch {
    installedFonts = [];
  }
  return installedFonts;
}

function cssFamily(family) {
  const safe = String(family || '').replace(/["\\]/g, '');
  return safe ? `"${safe}", Arial, sans-serif` : 'Arial, sans-serif';
}

export class LineEditor {
  constructor(app) {
    this.app = app;
    this.active = null;
    this.onOutside = (event) => {
      if (!this.active) return;
      const { box, bar } = this.active;
      if (box.contains(event.target) || bar.contains(event.target)) return;
      // Un clic sur une autre ligne est traité par l'outil : validation puis ouverture.
      if (event.target.closest?.('.tl-seg') && document.body.classList.contains('mode-edit')) return;
      this.commit();
    };
  }

  get isOpen() {
    return Boolean(this.active);
  }

  open(view, line, clickEvent = null) {
    if (this.active) this.close();
    if (!line.editable) {
      toast('Ce texte est incliné : utilisez « Effacer une zone » puis « Ajouter du texte ».', 'error');
      return;
    }
    const viewer = this.app.viewer;
    const s = viewer.scale;
    const [x0, y0, x1, y1] = line.bbox;
    const first = line.spans[0];
    const state = {
      family: first.family,
      size: first.size,
      bold: first.bold,
      italic: first.italic,
      color: first.color || '#000000',
      align: line.align || 'left',
      styleChanged: false,
    };

    const content = el('div', { class: 'te-content', contenteditable: 'true', spellcheck: 'true', role: 'textbox', 'aria-label': 'Texte de la ligne' });
    for (const span of line.spans) {
      const node = el('span', { text: span.text });
      Object.assign(node.dataset, {
        family: span.family, size: String(span.size), bold: span.bold ? '1' : '', italic: span.italic ? '1' : '', color: span.color || '#000000',
      });
      this.styleSpan(node, s);
      content.append(node);
    }
    // Le conteneur porte le style de la ligne : Chrome n'a pas à envelopper la saisie
    // dans un style en ligne (que la politique de sécurité refuse).
    content.style.fontFamily = cssFamily(first.family);
    content.style.fontSize = `${first.size * s}px`;
    content.style.fontWeight = first.bold ? '700' : '400';
    content.style.fontStyle = first.italic ? 'italic' : 'normal';
    content.style.color = first.color || '#000000';
    const box = el('div', { class: 'te-box' }, content);
    box.style.left = `${x0 * s - 2}px`;
    box.style.top = `${y0 * s}px`;
    box.style.minWidth = `${(x1 - x0) * s + 4}px`;
    box.style.height = `${(y1 - y0) * s}px`;
    content.style.lineHeight = `${(y1 - y0) * s}px`;
    content.style.paddingLeft = '2px';
    content.style.paddingRight = '2px';
    if (state.align === 'right') {
      box.style.left = 'auto';
      box.style.right = `${(view.w - x1) * s - 2}px`;
      content.style.textAlign = 'right';
    }

    const bar = this.buildBar(state, line);
    view.layers.tool.append(box, bar);
    view.el.classList.add('raised');
    this.active = { view, line, box, bar, content, state, busy: false };
    this.positionBar();

    content.addEventListener('keydown', (event) => this.onKey(event));
    content.addEventListener('paste', (event) => {
      event.preventDefault();
      const text = (event.clipboardData?.getData('text/plain') || '').replace(/[\r\n\t]+/g, ' ');
      document.execCommand('insertText', false, text);
    });
    content.addEventListener('input', () => this.positionBar());
    content.addEventListener('drop', (event) => event.preventDefault());
    document.addEventListener('pointerdown', this.onOutside, true);

    content.focus();
    this.placeCaret(clickEvent);
  }

  styleSpan(node, s) {
    node.style.fontFamily = cssFamily(node.dataset.family);
    node.style.fontSize = `${Number(node.dataset.size) * s}px`;
    node.style.fontWeight = node.dataset.bold ? '700' : '400';
    node.style.fontStyle = node.dataset.italic ? 'italic' : 'normal';
    node.style.color = node.dataset.color || '#000000';
  }

  placeCaret(clickEvent) {
    const { content } = this.active;
    const selection = window.getSelection();
    let range = null;
    if (clickEvent && document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(clickEvent.clientX, clickEvent.clientY);
      if (r && content.contains(r.startContainer)) range = r;
    }
    if (!range) {
      range = document.createRange();
      range.selectNodeContents(content);
      range.collapse(false);
    }
    selection.removeAllRanges();
    selection.addRange(range);
  }

  buildBar(state, line) {
    const bar = el('div', { class: 'te-bar', role: 'toolbar', 'aria-label': 'Mise en forme de la ligne' });
    const family = el('select', { 'aria-label': 'Police', 'data-tip': 'Police' });
    const fill = (fonts) => {
      family.textContent = '';
      const original = el('optgroup', { label: "Police de la ligne" }, el('option', { value: state.family, text: state.family }));
      const common = el('optgroup', { label: 'Courantes' });
      for (const name of COMMON_FONTS) if (name !== state.family) common.append(el('option', { value: name, text: name }));
      family.append(original, common);
      const rest = fonts.filter((f) => f !== state.family && !COMMON_FONTS.includes(f));
      if (rest.length) {
        const all = el('optgroup', { label: 'Toutes les polices' });
        for (const name of rest) all.append(el('option', { value: name, text: name }));
        family.append(all);
      }
      family.value = state.family;
    };
    fill([]);
    loadFonts().then((fonts) => { if (this.active) { const current = family.value; fill(fonts); family.value = current; } });
    family.addEventListener('change', () => this.applyStyle({ family: family.value }));

    const size = el('input', { class: 'num-input', type: 'number', min: '2', max: '200', step: '0.5', value: String(Math.round(state.size * 10) / 10), 'aria-label': 'Taille', 'data-tip': 'Taille (points)' });
    size.addEventListener('change', () => {
      const value = Number(size.value);
      if (value >= 2 && value <= 200) this.applyStyle({ size: value });
    });
    const bold = el('button', { class: 'icon-btn bold-btn', type: 'button', 'aria-pressed': String(state.bold), 'data-tip': 'Gras', text: 'G' });
    bold.addEventListener('click', () => {
      const value = bold.getAttribute('aria-pressed') !== 'true';
      bold.setAttribute('aria-pressed', String(value));
      this.applyStyle({ bold: value });
    });
    const italic = el('button', { class: 'icon-btn italic-btn', type: 'button', 'aria-pressed': String(state.italic), 'data-tip': 'Italique', text: 'I' });
    italic.addEventListener('click', () => {
      const value = italic.getAttribute('aria-pressed') !== 'true';
      italic.setAttribute('aria-pressed', String(value));
      this.applyStyle({ italic: value });
    });
    const color = el('input', { type: 'color', value: state.color, 'aria-label': 'Couleur', 'data-tip': 'Couleur' });
    color.addEventListener('input', () => this.applyStyle({ color: color.value }));

    const aligns = [['left', 'alignLeft', 'Aligner à gauche'], ['center', 'alignCenter', 'Centrer'], ['right', 'alignRight', 'Aligner à droite']];
    const alignButtons = aligns.map(([value, iconName, label]) => {
      const button = el('button', { class: 'icon-btn', type: 'button', 'aria-pressed': String(state.align === value), 'data-tip': label }, iconEl(iconName), el('span', { class: 'sr-only', text: label }));
      button.addEventListener('click', () => {
        state.align = value;
        state.styleChanged = true;
        alignButtons.forEach((b, i) => b.setAttribute('aria-pressed', String(aligns[i][0] === value)));
        this.active?.content.focus();
      });
      return button;
    });

    const remove = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Supprimer la ligne' }, iconEl('trash'), el('span', { class: 'sr-only', text: 'Supprimer la ligne' }));
    remove.addEventListener('click', () => this.commit({ remove: true }));
    const ok = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Valider (Entrée)' }, iconEl('check'), el('span', { class: 'sr-only', text: 'Valider' }));
    ok.addEventListener('click', () => this.commit());
    const cancel = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Annuler (Échap)' }, iconEl('close'), el('span', { class: 'sr-only', text: 'Annuler' }));
    cancel.addEventListener('click', () => this.close());

    bar.append(family, size, bold, italic, color, el('span', { class: 'te-sep' }), ...alignButtons, el('span', { class: 'te-sep' }));
    const missing = line.spans.find((sp) => !sp.exact);
    if (missing) {
      bar.append(el('span', { class: 'te-warn', 'data-tip': `Police « ${missing.font.replace(/^[A-Z]{6}\+/, '')} » absente de ce poste : remplacée par ${missing.family}.` }, iconEl('warn')));
    }
    bar.append(remove, ok, cancel);
    return bar;
  }

  applyStyle(changes) {
    if (!this.active) return;
    const { content, state } = this.active;
    Object.assign(state, changes);
    state.styleChanged = true;
    const s = this.app.viewer.scale;
    for (const span of content.querySelectorAll('span')) {
      if ('family' in changes) span.dataset.family = changes.family;
      if ('size' in changes) span.dataset.size = String(changes.size);
      if ('bold' in changes) span.dataset.bold = changes.bold ? '1' : '';
      if ('italic' in changes) span.dataset.italic = changes.italic ? '1' : '';
      if ('color' in changes) span.dataset.color = changes.color;
      this.styleSpan(span, s);
    }
    content.style.fontFamily = cssFamily(state.family);
    content.style.fontSize = `${state.size * s}px`;
    content.style.fontWeight = state.bold ? '700' : '400';
    content.style.fontStyle = state.italic ? 'italic' : 'normal';
    content.style.color = state.color;
    this.positionBar();
  }

  positionBar() {
    if (!this.active) return;
    const { box, bar, view } = this.active;
    const top = box.offsetTop;
    const height = bar.offsetHeight || 40;
    const above = top - height - 8;
    bar.style.top = `${above > -60 ? above : box.offsetTop + box.offsetHeight + 8}px`;
    const maxLeft = view.el.clientWidth - bar.offsetWidth;
    bar.style.left = `${Math.max(Math.min(box.offsetLeft, maxLeft), -40)}px`;
  }

  onKey(event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      this.commit();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.close();
    } else if (event.key === 'Tab') {
      event.preventDefault();
      this.commit({ next: event.shiftKey ? -1 : 1 });
    }
  }

  collectRuns() {
    const { content, state } = this.active;
    const runs = [];
    let last = null;
    // Texte saisi hors de tout fragment (ligne entièrement remplacée) : style de la ligne.
    const base = { family: state.family, size: Number(state.size), bold: Boolean(state.bold), italic: Boolean(state.italic), color: state.color || '#000000' };
    const pushText = (text, source) => {
      if (!text) return;
      const style = source ? {
        family: source.dataset.family,
        size: Number(source.dataset.size),
        bold: Boolean(source.dataset.bold),
        italic: Boolean(source.dataset.italic),
        color: source.dataset.color || '#000000',
      } : last ? { ...last } : { ...base };
      const prev = runs[runs.length - 1];
      if (prev && prev.family === style.family && prev.size === style.size && prev.bold === style.bold && prev.italic === style.italic && prev.color === style.color) {
        prev.text += text;
      } else {
        runs.push({ text, ...style });
      }
      last = style;
    };
    for (const node of content.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        pushText(node.textContent, null);
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const source = node.matches('span[data-family]') ? node : node.querySelector('span[data-family]');
        pushText(node.textContent, source);
      }
    }
    for (const run of runs) run.text = run.text.replace(/[\r\n\u200b]+/g, ' ');
    return runs.filter((r) => r.text.length);
  }

  async commit({ next = 0, remove = false } = {}) {
    if (!this.active || this.active.busy) return;
    const active = this.active;
    const { view, line, state } = active;
    const runs = remove ? [] : this.collectRuns();
    const text = runs.map((r) => r.text).join('');
    const unchanged = !remove && !state.styleChanged && text === line.text;
    if (unchanged) {
      this.close();
      if (next) this.openNeighbour(view, line, next);
      return;
    }
    if (!remove && !text.trim()) {
      // Ligne vidée : c'est une suppression.
      return this.commit({ next, remove: true });
    }
    active.busy = true;
    active.box.classList.add('busy');
    try {
      const data = await Api.post('api/edit-line', {
        page: view.index,
        line: { bbox: line.bbox, text: line.text },
        runs,
        align: state.align,
      });
      const editedBox = line.bbox;
      const index = view.index;
      await this.app.applyDoc(data.doc, { waitPage: index });
      if (this.active === active) this.close();
      if (next) this.openNeighbourAfterRefresh(index, editedBox, next);
    } catch (err) {
      active.busy = false;
      active.box.classList.remove('busy');
      toast(err.message, 'error');
      active.content.focus();
    }
  }

  close() {
    if (!this.active) return;
    const { box, bar, view } = this.active;
    box.remove();
    bar.remove();
    view.el.classList.remove('raised');
    document.removeEventListener('pointerdown', this.onOutside, true);
    this.active = null;
  }

  // Ligne suivante (ou précédente) dans l'ordre de lecture, d'après la géométrie.
  pickNeighbour(lines, bbox, direction) {
    const editable = lines.filter((l) => l.editable).sort((a, b) => (Math.abs(a.bbox[1] - b.bbox[1]) < 2 ? a.bbox[0] - b.bbox[0] : a.bbox[1] - b.bbox[1]));
    const key = (l) => [l.bbox[1], l.bbox[0]];
    const [y, x] = [bbox[1], bbox[0]];
    const after = (l) => (Math.abs(key(l)[0] - y) < 2 ? key(l)[1] > x + 0.5 : key(l)[0] > y);
    const before = (l) => (Math.abs(key(l)[0] - y) < 2 ? key(l)[1] < x - 0.5 : key(l)[0] < y);
    if (direction > 0) return editable.find(after) || null;
    return [...editable].reverse().find(before) || null;
  }

  openNeighbour(view, line, direction) {
    const lines = view.textData?.lines || [];
    const target = this.pickNeighbour(lines, line.bbox, direction);
    if (target) this.open(view, target);
  }

  openNeighbourAfterRefresh(index, bbox, direction) {
    const view = this.app.viewer.views[index];
    if (!view) return;
    const tryOpen = () => {
      const target = this.pickNeighbour(view.textData?.lines || [], bbox, direction);
      if (target) this.open(view, target);
    };
    if (view.textV === view.v && view.textData && view.textData.v === view.v) {
      tryOpen();
      return;
    }
    const onReady = (event) => {
      if (event.detail.index !== index) return;
      this.app.viewer.removeEventListener('textready', onReady);
      tryOpen();
    };
    this.app.viewer.addEventListener('textready', onReady);
    view.ensure();
  }
}
