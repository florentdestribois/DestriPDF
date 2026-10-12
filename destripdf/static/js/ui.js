// Composants transverses : icônes, notifications, fenêtres modales, menus, infobulles.

const P = (d) => `<path d="${d}"/>`;
const ICONS = {
  open: P('M3 7.5V18a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9.5a2 2 0 0 0-2-2h-7l-2-2.5H5a2 2 0 0 0-2 2z'),
  save: P('M5 3h11l3 3v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z') + P('M8 3v5h7V3') + P('M8 21v-7h8v7'),
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  sign: P('M4 20c3-1 5.5-3.2 7.7-6.6l2.9 1.7c-2.1 3.3-4.6 5.1-8.2 5.9z') + P('M11.7 13.4 16.8 4.6a1.6 1.6 0 0 1 2.8 1.6l-5 8.6') + P('M14 20h6'),
  select: P('M5 3.5 18.5 12l-6 1.6 3.5 6-2.4 1.4-3.5-6L6 19.5z'),
  edit: P('M4 20h4L19 9l-4-4L4 16z') + P('M13.5 6.5l4 4') + P('M14 20h6'),
  text: P('M5 6V4.5h14V6') + P('M12 4.5V20') + P('M9 20h6'),
  note: P('M5 4h14a1 1 0 0 1 1 1v10.5L15.5 20H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z') + P('M15 20v-4.5h5') + P('M8 9h8M8 12.5h5'),
  highlight: P('M9 15 5 19h5l1.8-1.8') + P('M9 15l7.5-10.5 3 2.2L12 17z') + P('M14 21h6'),
  draw: P('M4 19c2.5-.3 3.8-1.7 4.5-4.2S11 9 14 9s3 3 1 5-4 3-1 4 4.5-.5 6-2'),
  shape: '<rect x="3.5" y="4" width="10" height="8" rx="1"/><circle cx="15.5" cy="15.5" r="5"/>',
  rect: '<rect x="4" y="5.5" width="16" height="13" rx="1"/>',
  ellipse: '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>',
  arrow: P('M5 19 19 5') + P('M10 5h9v9'),
  erase: P('M8.5 20h11') + P('M5.6 13.6l7.8-7.8a2 2 0 0 1 2.8 0l2.5 2.5a2 2 0 0 1 0 2.8L12 18H8.2l-2.6-2.6a1.3 1.3 0 0 1 0-1.8z') + P('M9.5 9.7l5.3 5.3'),
  stamp: P('M9 4h6l-1 6h5v4H5v-4h5z') + P('M5 18h14v2H5z'),
  undo: P('M9 14 4 9l5-5') + P('M4 9h10.5a5.5 5.5 0 0 1 0 11H11'),
  redo: P('M15 14l5-5-5-5') + P('M20 9H9.5a5.5 5.5 0 0 0 0 11H13'),
  minus: P('M5 12h14'),
  plus: P('M12 5v14M5 12h14'),
  search: '<circle cx="11" cy="11" r="6.5"/>' + P('M20 20l-4.4-4.4'),
  up: P('M6 15l6-6 6 6'),
  down: P('M6 9l6 6 6-6'),
  close: P('M6 6l12 12M18 6 6 18'),
  sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/>' + P('M9 4.5v15'),
  insert: P('M7 3h7l5 5v13H7z') + P('M14 3v5h5') + P('M12 11v7M8.5 14.5h7'),
  rotate: P('M20 11a8 8 0 1 0-2.3 5.7') + P('M20 4v7h-7'),
  rotateLeft: P('M4 11a8 8 0 1 1 2.3 5.7') + P('M4 4v7h7'),
  trash: P('M4 7h16') + P('M10 11v6M14 11v6') + P('M6 7l1 13h10l1-13') + P('M9 7V4h6v3'),
  print: P('M7 9V3h10v6') + '<rect x="3.5" y="9" width="17" height="8" rx="1.5"/>' + P('M7 14h10v7H7z'),
  saveAs: P('M5 3h11l3 3v6') + P('M5 3v16a2 2 0 0 0 2 2h4') + P('M8 3v5h7V3') + P('M15 21l5-5-2-2-5 5v2z'),
  download: P('M12 4v11') + P('M7 10l5 5 5-5') + P('M5 20h14'),
  close2: P('M7 7l10 10M17 7 7 17'),
  check: P('M5 12.5l4.5 4.5L19 7.5'),
  shield: P('M12 3l7 3v5.5c0 4.3-3 7.8-7 9.5-4-1.7-7-5.2-7-9.5V6z') + P('M8.8 12.2l2.2 2.2 4.4-4.6'),
  shieldWarn: P('M12 3l7 3v5.5c0 4.3-3 7.8-7 9.5-4-1.7-7-5.2-7-9.5V6z') + P('M12 8v5M12 16.3v.2'),
  shieldBad: P('M12 3l7 3v5.5c0 4.3-3 7.8-7 9.5-4-1.7-7-5.2-7-9.5V6z') + P('M9.5 9.5l5 5M14.5 9.5l-5 5'),
  key: '<circle cx="8" cy="15" r="4"/>' + P('M11 12l8-8M16 7l2.5 2.5M14 9l2 2'),
  comment: P('M4 5h16v11H9l-5 4z'),
  warn: P('M12 4 2.8 19.5h18.4z') + P('M12 10v4.5M12 17.3v.2'),
  info: '<circle cx="12" cy="12" r="8.5"/>' + P('M12 11v5.5M12 7.8v.2'),
  pen: P('M4 20l1-4L16 5l3 3L8 19z'),
  image: '<rect x="3.5" y="5" width="17" height="14" rx="1.5"/><circle cx="9" cy="10" r="1.6"/>' + P('M20.5 16l-5-5L6 19'),
  fitWidth: P('M4 12h16') + P('M7 9l-3 3 3 3M17 9l3 3-3 3'),
  fitPage: '<rect x="6" y="3.5" width="12" height="17" rx="1"/>',
  settings: '<circle cx="12" cy="12" r="3"/>' + P('M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1'),
  alignLeft: P('M4 6h16M4 10h10M4 14h16M4 18h10'),
  alignCenter: P('M4 6h16M7 10h10M4 14h16M7 18h10'),
  alignRight: P('M4 6h16M10 10h10M4 14h16M10 18h10'),
  file: P('M7 3h7l5 5v13H7z') + P('M14 3v5h5'),
  pages: '<rect x="6.5" y="3.5" width="11" height="14" rx="1"/>' + P('M4 7v13h11'),
};

export function icon(name) {
  const body = ICONS[name] || '';
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll('.ico[data-icon]').forEach((node) => {
    if (!node.firstChild) node.innerHTML = icon(node.dataset.icon);
  });
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function iconEl(name, cls = 'ico') {
  const span = document.createElement('span');
  span.className = cls;
  span.innerHTML = icon(name);
  return span;
}

// --- Notifications ---

export function toast(message, kind = 'info', { action, onAction, duration } = {}) {
  const root = document.getElementById('toasts');
  const iconName = kind === 'error' ? 'warn' : kind === 'ok' ? 'check' : 'info';
  const node = el('div', { class: `toast ${kind}` }, iconEl(iconName), el('span', { text: message }));
  if (action && onAction) {
    node.append(el('button', { class: 'toast-action', type: 'button', text: action, onclick: () => { onAction(); node.remove(); } }));
  }
  root.append(node);
  while (root.children.length > 3) root.firstElementChild.remove();
  const ms = duration ?? (kind === 'error' ? 6500 : 3200);
  setTimeout(() => node.remove(), ms);
  return node;
}

// --- Fenêtres modales maison (jamais window.alert/confirm) ---

let modalDepth = 0;
export function isModalOpen() {
  return modalDepth > 0;
}

export function modal({ title, text = '', body = null, buttons = [], wide = false, onOpen = null, dismissValue = null }) {
  return new Promise((resolve) => {
    const root = document.getElementById('modal-root');
    const previous = document.activeElement;
    const dialog = el('div', { class: `modal${wide ? ' modal-wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'modal-title' });
    const backdrop = el('div', { class: 'modal-backdrop' }, dialog);
    dialog.append(el('h2', { class: 'modal-title', id: 'modal-title', text: title }));
    if (text) dialog.append(el('p', { class: 'modal-text', text }));
    if (body) dialog.append(body);
    const actions = el('div', { class: 'modal-actions' });
    let done = false;
    const close = (value) => {
      if (done) return;
      done = true;
      modalDepth -= 1;
      backdrop.remove();
      document.removeEventListener('keydown', onKey, true);
      if (previous && previous.focus) previous.focus();
      resolve(value);
    };
    for (const button of buttons) {
      if (button.spacer) {
        actions.append(el('span', { class: 'spacer' }));
        continue;
      }
      const node = el('button', { class: `btn ${button.kind || 'btn-ghost'}`, type: 'button', text: button.label });
      node.addEventListener('click', async () => {
        if (button.validate) {
          const ok = await button.validate();
          if (!ok) return;
        }
        close(button.value);
      });
      if (button.default) node.dataset.default = '1';
      actions.append(node);
    }
    dialog.append(actions);
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close(dismissValue);
      } else if (event.key === 'Enter' && !event.shiftKey && event.target.tagName !== 'TEXTAREA' && event.target.tagName !== 'BUTTON') {
        const def = actions.querySelector('[data-default]');
        if (def) {
          event.preventDefault();
          def.click();
        }
      } else if (event.key === 'Tab') {
        const focusables = [...dialog.querySelectorAll('button, input, select, textarea, canvas[tabindex], [tabindex="0"]')].filter((n) => !n.disabled);
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey, true);
    backdrop.addEventListener('mousedown', (event) => {
      if (event.target === backdrop) close(dismissValue);
    });
    modalDepth += 1;
    root.append(backdrop);
    const autofocus = dialog.querySelector('[autofocus]') || dialog.querySelector('input, textarea, select') || actions.querySelector('[data-default]') || actions.querySelector('button');
    if (autofocus) autofocus.focus();
    if (onOpen) onOpen(dialog, close);
  });
}

export async function confirmModal(title, text, { confirm = 'Confirmer', cancel = 'Annuler', danger = false } = {}) {
  const value = await modal({
    title,
    text,
    buttons: [
      { label: cancel, value: false },
      { label: confirm, value: true, kind: danger ? 'btn-danger' : 'btn-primary', default: true },
    ],
    dismissValue: false,
  });
  return value === true;
}

export async function promptModal(title, { label = '', value = '', type = 'text', help = '', confirm = 'Valider' } = {}) {
  const input = el('input', { class: 'text-input', type, value, autofocus: true, autocomplete: 'off' });
  const body = el('div', {}, label ? el('label', { class: 'field-label', text: label }) : null, input, help ? el('p', { class: 'help', text: help }) : null);
  const result = await modal({
    title,
    body,
    buttons: [
      { label: 'Annuler', value: null },
      { label: confirm, value: 'ok', kind: 'btn-primary', default: true },
    ],
    dismissValue: null,
  });
  return result === 'ok' ? input.value : null;
}

export function busy(message) {
  const node = el('div', { class: 'busy-overlay', role: 'alert', 'aria-live': 'assertive' },
    el('div', { class: 'busy-card' }, el('span', { class: 'spinner' }), el('span', { text: message })));
  document.body.append(node);
  return {
    update(text) { node.querySelector('.busy-card span:last-child').textContent = text; },
    close() { node.remove(); },
  };
}

// --- Menus contextuels ---

let openMenu = null;
export function closeMenu() {
  if (openMenu) {
    openMenu.close();
    openMenu = null;
  }
}

export function showMenu(anchor, items) {
  closeMenu();
  const menu = el('div', { class: 'menu', role: 'menu' });
  for (const item of items) {
    if (item === '-') {
      menu.append(el('div', { class: 'menu-sep', role: 'separator' }));
      continue;
    }
    const node = el('button', { class: 'menu-item', type: 'button', role: 'menuitem', disabled: item.disabled || undefined },
      item.icon ? iconEl(item.icon) : null, el('span', { text: item.label }), item.shortcut ? el('span', { class: 'kbd', text: item.shortcut }) : null);
    node.addEventListener('click', () => { closeMenu(); item.action(); });
    menu.append(node);
  }
  document.body.append(menu);
  const rect = anchor.getBoundingClientRect();
  const width = menu.offsetWidth;
  const left = Math.min(Math.max(8, rect.right - width), window.innerWidth - width - 8);
  menu.style.left = `${left}px`;
  menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 8)}px`;
  anchor.setAttribute('aria-expanded', 'true');
  const onDown = (event) => { if (!menu.contains(event.target) && event.target !== anchor) closeMenu(); };
  const onKey = (event) => {
    const buttons = [...menu.querySelectorAll('.menu-item:not([disabled])')];
    const index = buttons.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); closeMenu(); anchor.focus(); }
    else if (event.key === 'ArrowDown') { event.preventDefault(); buttons[(index + 1) % buttons.length]?.focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); buttons[(index - 1 + buttons.length) % buttons.length]?.focus(); }
  };
  setTimeout(() => document.addEventListener('mousedown', onDown, true), 0);
  document.addEventListener('keydown', onKey, true);
  menu.querySelector('.menu-item:not([disabled])')?.focus();
  openMenu = {
    close() {
      menu.remove();
      anchor.setAttribute('aria-expanded', 'false');
      document.removeEventListener('mousedown', onDown, true);
      document.removeEventListener('keydown', onKey, true);
    },
  };
}

// --- Infobulles (attribut data-tip) ---

export function installTooltips() {
  const tip = document.getElementById('tooltip');
  let timer = null;
  let current = null;
  const hide = () => {
    clearTimeout(timer);
    tip.hidden = true;
    current = null;
  };
  document.addEventListener('pointerover', (event) => {
    const target = event.target.closest('[data-tip]');
    if (!target || target === current) return;
    hide();
    current = target;
    timer = setTimeout(() => {
      if (!document.body.contains(target)) return;
      tip.textContent = target.dataset.tip;
      tip.hidden = false;
      const rect = target.getBoundingClientRect();
      const left = Math.min(Math.max(6, rect.left + rect.width / 2 - tip.offsetWidth / 2), window.innerWidth - tip.offsetWidth - 6);
      let top = rect.bottom + 8;
      if (top + tip.offsetHeight > window.innerHeight - 6) top = rect.top - tip.offsetHeight - 8;
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    }, 450);
  });
  document.addEventListener('pointerout', (event) => {
    if (current && !current.contains(event.relatedTarget)) hide();
  });
  document.addEventListener('pointerdown', hide, true);
  document.addEventListener('keydown', hide, true);
}

export function formatDate(iso, withTime = true) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  const day = `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()}`;
  return withTime ? `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}` : day;
}

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
