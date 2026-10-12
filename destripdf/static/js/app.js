// Orchestration : démarrage, ouverture, enregistrement, raccourcis, recherche,
// impression, signature, glisser-déposer et fermeture.

import { Api, ApiError } from './api.js';
import {
  busy, closeMenu, confirmModal, el, formatDate, hydrateIcons, iconEl, installTooltips,
  isModalOpen, modal, promptModal, showMenu, toast,
} from './ui.js';
import { Viewer } from './viewer.js';
import { LineEditor } from './textedit.js';
import { ToolManager, TOOLS } from './tools.js';
import { Panel, Sidebar } from './panels.js';

const $ = (id) => document.getElementById(id);

class App {
  constructor() {
    this.doc = null;
    this.state = null;
    this.settings = null;
    this.viewer = new Viewer($('viewer'), $('pages'));
    this.editor = new LineEditor(this);
    this.tools = new ToolManager(this);
    this.sidebar = new Sidebar(this);
    this.panel = new Panel(this);
    this.search = { query: '', hits: [], index: -1, timer: null, seq: 0 };
    this.busyOps = 0;
  }

  // --- Démarrage ---

  async boot() {
    hydrateIcons();
    installTooltips();
    this.buildToolbar();
    this.bindChrome();
    this.bindKeys();
    this.bindDrop();
    this.viewer.addEventListener('pagechange', (e) => this.onPageChange(e.detail.index));
    this.viewer.addEventListener('zoomchange', (e) => this.onZoomChange(e.detail));
    this.viewer.addEventListener('textready', (e) => this.tools.pageHint(this.viewer.views[e.detail.index]));
    let sidebarVisible = true;
    try { sidebarVisible = localStorage.getItem('destripdf.sidebar') !== '0'; } catch { /* sans stockage */ }
    this.sidebar.setVisible(sidebarVisible);
    this.tools.set('select');
    try {
      const state = await Api.get('api/state?wait=1');
      await this.applyState(state);
    } catch (err) {
      this.showStart([]);
      toast(err.message, 'error');
    }
  }

  async applyState(state) {
    this.state = state;
    this.settings = state.settings;
    // Mode recette (navigateur) : l'état de l'application est lisible par le pilote de test.
    if (state.app?.mode === 'browser') window.__app = this;
    this.applyTheme();
    if (state.doc) {
      await this.onOpened(state.doc);
    } else {
      this.showStart(state.recent || []);
    }
    if (state.error) toast(state.error.error, 'error');
    if (state.password_needed) await this.askPassword(state.pending_name);
  }

  applyTheme() {
    const theme = this.settings?.theme || 'auto';
    if (theme === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }

  buildToolbar() {
    const host = $('tools');
    for (const tool of TOOLS) {
      const button = el('button', {
        class: 'tool', type: 'button', 'aria-pressed': 'false', dataset: { tool: tool.id },
        'data-tip': `${tool.label} (${tool.key.toUpperCase()})`, 'aria-label': tool.label,
      }, iconEl(tool.icon), el('span', { class: 'tool-label', text: tool.short }));
      button.addEventListener('click', () => this.tools.set(this.tools.tool === tool.id && tool.id !== 'select' ? 'select' : tool.id));
      host.append(button);
    }
  }

  bindChrome() {
    $('btn-open').addEventListener('click', () => this.openDialog());
    $('start-open').addEventListener('click', () => this.openDialog());
    $('btn-save').addEventListener('click', () => this.save());
    $('btn-sign').addEventListener('click', () => this.startSigning());
    $('btn-more').addEventListener('click', (e) => this.moreMenu(e.currentTarget));
    $('btn-undo').addEventListener('click', () => this.undo());
    $('btn-redo').addEventListener('click', () => this.redo());
    $('btn-zoom-in').addEventListener('click', () => this.viewer.zoomStep(1));
    $('btn-prev-page').addEventListener('click', () => this.viewer.scrollToPage(this.viewer.current - 1));
    $('btn-next-page').addEventListener('click', () => this.viewer.scrollToPage(this.viewer.current + 1));
    $('btn-zoom-out').addEventListener('click', () => this.viewer.zoomStep(-1));
    $('zoom-value').addEventListener('click', (e) => this.zoomMenu(e.currentTarget));
    $('btn-sidebar').addEventListener('click', () => {
      const visible = $('sidebar').classList.contains('collapsed');
      this.sidebar.setVisible(visible);
      if (this.viewer.fit) this.viewer.applyFit(true);
    });
    const pageInput = $('page-input');
    pageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const n = parseInt(pageInput.value, 10);
        if (this.doc && n >= 1 && n <= this.doc.page_count) this.viewer.scrollToPage(n - 1);
        else pageInput.value = String(this.viewer.current + 1);
        $('viewer').focus();
      } else if (e.key === 'Escape') {
        pageInput.value = String(this.viewer.current + 1);
        $('viewer').focus();
      }
    });
    pageInput.addEventListener('focus', () => pageInput.select());
    const search = $('search-input');
    search.addEventListener('input', () => {
      clearTimeout(this.search.timer);
      this.search.timer = setTimeout(() => this.runSearch(search.value), 250);
    });
    search.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (search.value !== this.search.query) this.runSearch(search.value);
        else this.stepSearch(e.shiftKey ? -1 : 1);
      } else if (e.key === 'Escape') {
        search.value = '';
        this.runSearch('');
        $('viewer').focus();
      }
    });
    $('search-next').addEventListener('click', () => this.stepSearch(1));
    $('search-prev').addEventListener('click', () => this.stepSearch(-1));
    $('file-input').addEventListener('change', (e) => {
      const file = e.target.files[0];
      e.target.value = '';
      if (file) this.uploadFile(file);
    });
    $('insert-input').addEventListener('change', async (e) => {
      const file = e.target.files[0];
      e.target.value = '';
      if (!file) return;
      await this.mutate(() => Api.upload(`api/pages/insert-upload?at=${this.insertAt ?? this.doc.page_count}`, file), 'Pages insérées.');
    });
  }

  // --- Affichage du document ---

  async onOpened(doc) {
    this.editor.close();
    this.tools.cancelTransient();
    this.tools.deselect();
    this.tools.clearSignFrame();
    this.panel.reports = null;
    this.doc = null;
    $('start').hidden = true;
    document.body.classList.remove('no-doc');
    await this.applyDoc(doc);
    this.tools.set('select');
    this.resetSearch();
    $('viewer').focus();
    if (doc.signed) this.panel.loadReports();
    else this.updateSignatureBanner(null);
    if (this.panel.isOpen) this.panel.open(this.panel.tab === 'signatures' && !doc.signed ? 'comments' : this.panel.tab);
  }

  async applyDoc(doc, { waitPage = null } = {}) {
    const previous = this.doc;
    const sameDoc = previous && previous.id === doc.id;
    const structural = !sameDoc || previous.page_count !== doc.page_count
      || doc.pages.some((p, i) => !previous.pages[i] || previous.pages[i].w !== p.w || previous.pages[i].h !== p.h || previous.pages[i].rot !== p.rot);
    this.doc = doc;
    if (!sameDoc) {
      this.viewer.load(doc);
      this.sidebar.render(doc);
    } else {
      this.viewer.update(doc);
      this.sidebar.update(doc, structural);
    }
    this.updateChrome();
    this.panel.onDoc(doc);
    if (structural && sameDoc) this.tools.placeSignFrame();
    if (waitPage !== null && sameDoc) await this.waitRendered(waitPage);
  }

  waitRendered(index, timeout = 1600) {
    const view = this.viewer.views[index];
    if (!view || !view.visible || view.loadedKey === view.imageKey()) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        this.viewer.removeEventListener('pagerendered', onRender);
        resolve();
      };
      const onRender = (e) => { if (e.detail.index === index) done(); };
      const timer = setTimeout(done, timeout);
      this.viewer.addEventListener('pagerendered', onRender);
    });
  }

  updateChrome() {
    const doc = this.doc;
    const title = $('doc-title');
    title.textContent = doc ? doc.name : 'Aucun document';
    if (doc?.dirty) title.append(el('span', { class: 'dirty-mark', 'aria-label': 'modifié', text: '●' }));
    document.title = doc ? `${doc.dirty ? '• ' : ''}${doc.name} — DestriPDF` : 'DestriPDF';
    const undo = $('btn-undo');
    const redo = $('btn-redo');
    undo.disabled = !doc?.can_undo;
    redo.disabled = !doc?.can_redo;
    undo.dataset.tip = doc?.undo_label ? `Annuler : ${doc.undo_label} (Ctrl+Z)` : 'Annuler (Ctrl+Z)';
    redo.dataset.tip = doc?.redo_label ? `Rétablir : ${doc.redo_label} (Ctrl+Y)` : 'Rétablir (Ctrl+Y)';
    $('page-count').textContent = `/ ${doc ? doc.page_count : 0}`;
    $('btn-save').dataset.tip = doc?.path ? `Enregistrer dans ${doc.path} (Ctrl+S)` : 'Enregistrer (Ctrl+S)';
  }

  onPageChange(index) {
    if (document.activeElement !== $('page-input')) $('page-input').value = String(index + 1);
    this.sidebar.setCurrent(index);
  }

  onZoomChange({ zoom }) {
    $('zoom-value').textContent = `${Math.round(zoom * 100)} %`;
  }

  showStart(recent) {
    this.doc = null;
    document.body.classList.add('no-doc');
    $('start').hidden = false;
    $('doc-title').textContent = 'Aucun document';
    document.title = 'DestriPDF';
    $('pages').textContent = '';
    $('thumbs').textContent = '';
    this.viewer.doc = null;
    this.viewer.views = [];
    this.panel.close();
    this.updateSignatureBanner(null);
    const host = $('recent');
    host.textContent = '';
    if (!recent.length) return;
    host.append(el('h2', { class: 'recent-title', text: 'Documents récents' }));
    const list = el('ul', { class: 'recent-list' });
    for (const item of recent) {
      const dir = item.path.replace(/[\\/][^\\/]*$/, '');
      const open = el('button', { class: 'recent-open', type: 'button', disabled: !item.exists || undefined, title: item.exists ? item.path : 'Fichier introuvable' },
        iconEl('file'),
        el('span', { class: 'recent-texts' }, el('span', { class: 'recent-name', text: item.name }), el('span', { class: 'recent-dir', text: dir })),
        el('span', { class: 'recent-date', text: formatDate(new Date(item.opened_at * 1000).toISOString(), false) }));
      open.addEventListener('click', () => this.openPath(item.path));
      const forget = el('button', { class: 'icon-btn icon-btn-sm', type: 'button', 'data-tip': 'Retirer de la liste' }, iconEl('close'), el('span', { class: 'sr-only', text: 'Retirer de la liste' }));
      forget.addEventListener('click', async () => {
        const data = await Api.post('api/recent/remove', { path: item.path });
        this.showStart(data.recent || []);
      });
      list.append(el('li', { class: `recent-item${item.exists ? '' : ' missing'}` }, open, forget));
    }
    host.append(list);
  }

  // --- Ouverture ---

  async confirmDiscard() {
    if (this.editor.isOpen) await this.editor.commit();
    if (!this.doc?.dirty) return true;
    const choice = await modal({
      title: 'Enregistrer les modifications ?',
      text: `« ${this.doc.name} » a été modifié depuis son dernier enregistrement.`,
      buttons: [
        { label: 'Annuler', value: 'cancel' },
        { spacer: true },
        { label: 'Ne pas enregistrer', value: 'discard', kind: 'btn-ghost' },
        { label: 'Enregistrer', value: 'save', kind: 'btn-primary', default: true },
      ],
      dismissValue: 'cancel',
    });
    if (choice === 'save') return this.save();
    return choice === 'discard';
  }

  async openDialog() {
    if (!(await this.confirmDiscard())) return;
    if (this.state?.app?.dialogs) {
      try {
        const data = await Api.post('api/open-dialog');
        if (data.doc) await this.onOpened(data.doc);
      } catch (err) {
        await this.handleOpenError(err);
      }
    } else {
      $('file-input').click();
    }
  }

  async openPath(path) {
    if (!(await this.confirmDiscard())) return;
    const progress = setTimeout(() => toast('Ouverture…'), 400);
    try {
      const data = await Api.post('api/open', { path });
      await this.onOpened(data.doc);
    } catch (err) {
      await this.handleOpenError(err);
    } finally {
      clearTimeout(progress);
    }
  }

  async uploadFile(file) {
    if (!(await this.confirmDiscard())) return;
    try {
      const data = await Api.upload(`api/upload?name=${encodeURIComponent(file.name)}`, file);
      await this.onOpened(data.doc);
    } catch (err) {
      await this.handleOpenError(err);
    }
  }

  async handleOpenError(err) {
    if (err instanceof ApiError && err.code === 'password') {
      await this.askPassword(null);
      return;
    }
    toast(err.message, 'error');
  }

  async askPassword(name) {
    let message = name ? `« ${name} » est protégé par un mot de passe.` : 'Ce PDF est protégé par un mot de passe.';
    for (;;) {
      const password = await promptModal('Mot de passe', { label: 'Mot de passe du document', type: 'password', help: message, confirm: 'Ouvrir' });
      if (password === null) {
        await Api.post('api/cancel-pending').catch(() => {});
        return;
      }
      try {
        const data = await Api.post('api/password', { password });
        await this.onOpened(data.doc);
        return;
      } catch (err) {
        if (err.code !== 'password') {
          toast(err.message, 'error');
          return;
        }
        message = 'Mot de passe incorrect. Réessayez.';
      }
    }
  }

  // --- Modifications ---

  async mutate(request, okMessage = null) {
    if (!this.doc) return null;
    try {
      const data = await request();
      if (data?.cancelled) return null;
      if (data?.doc) await this.applyDoc(data.doc);
      if (okMessage) toast(okMessage, 'ok');
      return data;
    } catch (err) {
      toast(err.message, 'error');
      return null;
    }
  }

  async undo() {
    if (!this.doc?.can_undo) return;
    this.editor.close();
    this.tools.deselect();
    await this.mutate(() => Api.post('api/undo'));
  }

  async redo() {
    if (!this.doc?.can_redo) return;
    this.editor.close();
    this.tools.deselect();
    await this.mutate(() => Api.post('api/redo'));
  }

  async rotatePages(pages, angle) {
    await this.mutate(() => Api.post('api/pages/rotate', { pages, angle }));
  }

  async deletePages(pages) {
    if (!this.doc) return;
    if (this.doc.page_count <= pages.length) {
      toast('Un PDF garde au moins une page.', 'error');
      return;
    }
    const data = await this.mutate(() => Api.post('api/pages/delete', { pages }));
    if (data) toast(pages.length > 1 ? 'Pages supprimées.' : `Page ${pages[0] + 1} supprimée.`, 'ok', { action: 'Annuler', onAction: () => this.undo() });
  }

  async movePage(from, to) {
    await this.mutate(() => Api.post('api/pages/move', { from, to }));
    this.viewer.scrollToPage(to);
  }

  async insertPdf(at) {
    if (!this.doc) return;
    this.insertAt = at;
    if (this.state?.app?.dialogs) {
      await this.mutate(() => Api.post('api/pages/insert-dialog', { at }), 'Pages insérées.');
    } else {
      $('insert-input').click();
    }
  }

  focusAnnotation(page, id, rect) {
    this.tools.set('select');
    this.viewer.scrollToPage(page);
    this.viewer.scrollToRect(page, rect);
    const select = () => this.tools.selectAnnot(page, id);
    const view = this.viewer.views[page];
    if (view?.annotData) select();
    else {
      const onReady = (e) => {
        if (e.detail.index !== page) return;
        this.viewer.removeEventListener('annotsready', onReady);
        select();
      };
      this.viewer.addEventListener('annotsready', onReady);
    }
  }

  // --- Enregistrement ---

  async save() {
    if (!this.doc) return false;
    if (this.editor.isOpen) await this.editor.commit();
    try {
      const data = await Api.post('api/save');
      await this.applyDoc(data.doc);
      toast('Enregistré.', 'ok');
      return true;
    } catch (err) {
      if (err.code === 'need_path') return this.saveAs();
      if (err.code === 'repaired_signed') return this.saveRewritingSigned(err);
      toast(err.message, 'error');
      return false;
    }
  }

  // PDF signé endommagé : seule une réécriture complète est possible, après accord explicite.
  async saveRewritingSigned(err) {
    const ok = await confirmModal(
      'Signatures existantes',
      `${err.message}\n\nEnregistrer quand même ? Le fichier sera réécrit et ses signatures ne seront plus valides.`,
      { confirm: 'Enregistrer quand même', danger: true },
    );
    if (!ok) return false;
    try {
      const data = await Api.post('api/save-as', { path: err.data.path, force_full: true });
      await this.onOpened(data.doc);
      toast(`Enregistré : ${data.doc.name}`, 'ok');
      return true;
    } catch (again) {
      toast(again.message, 'error');
      return false;
    }
  }

  async saveAs() {
    if (!this.doc) return false;
    if (this.editor.isOpen) await this.editor.commit();
    let body = {};
    if (!this.state?.app?.dialogs) {
      const path = await promptModal('Enregistrer sous', { label: 'Chemin complet du fichier', value: this.doc.path || '', confirm: 'Enregistrer' });
      if (!path) return false;
      body = { path };
    }
    try {
      const data = await Api.post('api/save-as', body);
      if (data.cancelled) return false;
      await this.applyDoc(data.doc);
      toast(`Enregistré : ${data.doc.name}`, 'ok');
      return true;
    } catch (err) {
      if (err.code === 'repaired_signed') return this.saveRewritingSigned(err);
      toast(err.message, 'error');
      return false;
    }
  }

  download() {
    const link = el('a', { href: 'api/download', download: this.doc?.name || 'document.pdf' });
    document.body.append(link);
    link.click();
    link.remove();
  }

  async closeDocument() {
    if (!(await this.confirmDiscard())) return;
    await Api.post('api/close').catch(() => {});
    const state = await Api.get('api/state');
    this.state = state;
    this.showStart(state.recent || []);
  }

  async requestClose() {
    if (isModalOpen()) return;
    // L'état du serveur fait foi : aucune modification ne se perd à la fermeture.
    try {
      const state = await Api.get('api/state');
      if (state.doc && this.doc && state.doc.id === this.doc.id) await this.applyDoc(state.doc);
    } catch {
      /* serveur injoignable : on garde l'état connu */
    }
    if (await this.confirmDiscard()) await Api.post('api/quit').catch(() => {});
  }

  // --- Recherche ---

  resetSearch() {
    $('search-input').value = '';
    this.search = { ...this.search, query: '', hits: [], index: -1 };
    $('search-count').textContent = '';
    this.viewer.setSearch([], -1);
  }

  async runSearch(query) {
    query = query.trim();
    const seq = ++this.search.seq;
    this.search.query = query;
    if (!query || !this.doc) {
      this.search.hits = [];
      this.search.index = -1;
      $('search-count').textContent = '';
      this.viewer.setSearch([], -1);
      return;
    }
    try {
      const data = await Api.get(`api/search?q=${encodeURIComponent(query)}`);
      if (seq !== this.search.seq) return;
      const hits = data.hits || [];
      const current = this.viewer.current;
      let index = hits.findIndex((h) => h.page >= current);
      if (index < 0) index = hits.length ? 0 : -1;
      this.search.hits = hits;
      this.search.index = index;
      $('search-count').textContent = hits.length ? `${index + 1} / ${hits.length}` : 'Aucun';
      this.viewer.setSearch(hits, index);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  stepSearch(direction) {
    const { hits } = this.search;
    if (!hits.length) return;
    this.search.index = (this.search.index + direction + hits.length) % hits.length;
    $('search-count').textContent = `${this.search.index + 1} / ${hits.length}`;
    this.viewer.setSearch(hits, this.search.index);
  }

  // --- Impression ---

  async print() {
    if (!this.doc) return;
    const root = $('print-root');
    root.textContent = '';
    const indicator = busy("Préparation de l'impression…");
    // Résolution adaptée au volume : chaque page est une image en mémoire.
    const count = this.doc.page_count;
    const dpi = count <= 30 ? 150 : count <= 120 ? 110 : 80;
    const scale = dpi / 72;
    try {
      const images = this.doc.pages.map((info, index) => {
        const img = el('img', { class: 'print-page', alt: '' });
        img.style.width = `${info.w}pt`;
        img.style.height = `${info.h}pt`;
        root.append(img);
        return { img, url: `api/page/${index}/image?d=${this.doc.id}&s=${scale}&v=${info.v}` };
      });
      let done = 0;
      const queue = [...images];
      const worker = async () => {
        while (queue.length) {
          const { img, url } = queue.shift();
          img.src = url;
          await img.decode().catch(() => {});
          done += 1;
          indicator.update(`Préparation de l'impression… ${done} / ${images.length}`);
        }
      };
      await Promise.all([worker(), worker(), worker()]);
    } finally {
      indicator.close();
    }
    window.print();
    setTimeout(() => { root.textContent = ''; }, 1000);
  }

  // --- Signature ---

  startSigning() {
    if (!this.doc) return;
    this.panel.open('sign');
    const draft = this.panel.signDraft;
    const visible = draft ? draft.visible : this.settings?.sign_visible !== false;
    if (visible && !this.tools.signFrame) this.tools.set('sign');
  }

  async signDocument(payload) {
    if (!payload.certificate) {
      toast('Choisissez un certificat.', 'error');
      return;
    }
    if (payload.visible === 'missing') {
      this.tools.set('sign');
      toast('Tracez le cadre de la signature sur la page, ou décochez « Signature visible ».', 'error');
      return;
    }
    if (this.editor.isOpen) await this.editor.commit();
    const body = { ...payload };
    if (!this.state?.app?.dialogs) {
      const suggestion = (this.doc.path || '').replace(/\.pdf$/i, '') + ' - signé.pdf';
      const path = await promptModal('Enregistrer le document signé', { label: 'Chemin complet du fichier signé', value: this.doc.path ? suggestion : '', confirm: 'Signer' });
      if (!path) return;
      body.path = path;
    }
    const indicator = busy('Signature en cours. Si la fenêtre de votre clé le demande, saisissez votre code PIN.');
    try {
      const data = await Api.post('api/sign', body);
      if (data.cancelled) return;
      this.panel.resetAfterSign();
      await this.onOpened(data.doc);
      this.panel.open('signatures');
      toast(`Document signé et enregistré : ${data.doc.name}`, 'ok', { duration: 6000 });
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      indicator.close();
    }
  }

  updateSignatureBanner(reports, error = null) {
    const banner = $('sig-banner');
    banner.textContent = '';
    banner.className = 'sig-banner';
    if (reports === null || !this.doc?.signed) {
      banner.hidden = !this.doc?.signed;
      if (this.doc?.signed) banner.append(iconEl('shield'), el('span', { text: 'Vérification des signatures…' }));
      return;
    }
    banner.hidden = false;
    if (error || !reports.length) {
      banner.classList.add('warning');
      banner.append(iconEl('shieldWarn'), el('span', { text: error || 'Signatures illisibles.' }));
      return;
    }
    const worst = reports.some((r) => r.status === 'invalid') ? 'invalid' : reports.some((r) => r.status === 'warning') ? 'warning' : 'valid';
    banner.classList.add(worst);
    const names = [...new Set(reports.map((r) => r.signer).filter(Boolean))].join(', ');
    const text = worst === 'valid'
      ? `Signé par ${names} — signature${reports.length > 1 ? 's' : ''} valide${reports.length > 1 ? 's' : ''}.`
      : worst === 'warning'
        ? `Signé par ${names} — à vérifier : ${reports.find((r) => r.status === 'warning').summary.replace(/^Signature intègre, à vérifier : /, '')}`
        : `Signature invalide : ${reports.find((r) => r.status === 'invalid').summary}`;
    banner.append(iconEl(worst === 'valid' ? 'shield' : worst === 'warning' ? 'shieldWarn' : 'shieldBad'), el('span', { text }));
    const details = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Détails' });
    details.addEventListener('click', () => this.panel.open('signatures'));
    banner.append(details);
  }

  async placeHandwritten() {
    if (!this.settings?.has_signature_image) {
      const ok = await this.drawSignature();
      if (!ok) return;
    }
    this.tools.set('stamp');
  }

  async drawSignature() {
    const canvas = el('canvas', { class: 'sig-pad', width: '1040', height: '380', tabindex: '0', 'aria-label': 'Zone de dessin de la signature' });
    const ctx = canvas.getContext('2d');
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#1b2a4a';
    ctx.lineWidth = 5;
    let drawing = false;
    let empty = true;
    const pos = (e) => {
      const r = canvas.getBoundingClientRect();
      return [(e.clientX - r.left) * (canvas.width / r.width), (e.clientY - r.top) * (canvas.height / r.height)];
    };
    canvas.addEventListener('pointerdown', (e) => {
      drawing = true;
      empty = false;
      canvas.setPointerCapture(e.pointerId);
      const [x, y] = pos(e);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + 0.1, y + 0.1);
      ctx.stroke();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!drawing) return;
      const [x, y] = pos(e);
      ctx.lineTo(x, y);
      ctx.stroke();
    });
    canvas.addEventListener('pointerup', () => { drawing = false; });
    const clear = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Effacer' });
    clear.addEventListener('click', () => { ctx.clearRect(0, 0, canvas.width, canvas.height); empty = true; });
    const body = el('div', {}, canvas, el('div', { class: 'modal-actions' }, clear),
      el('p', { class: 'help', text: 'Signez avec la souris, un stylet ou le doigt. L\'image est conservée sur ce poste pour vos prochaines signatures.' }));
    const result = await modal({
      title: 'Dessiner ma signature',
      body,
      wide: true,
      buttons: [
        { label: 'Annuler', value: null },
        { label: 'Enregistrer', value: 'ok', kind: 'btn-primary', validate: () => { if (empty) toast('Dessinez votre signature.', 'error'); return !empty; } },
      ],
    });
    if (result !== 'ok') return false;
    const blob = await trimmedPng(canvas);
    return this.uploadSignature(blob);
  }

  async importSignature() {
    const input = el('input', { type: 'file', accept: 'image/png,image/jpeg' });
    const file = await new Promise((resolve) => {
      input.addEventListener('change', () => resolve(input.files[0] || null));
      input.click();
    });
    if (!file) return false;
    const bitmap = await createImageBitmap(file).catch(() => null);
    if (!bitmap) {
      toast('Image illisible.', 'error');
      return false;
    }
    const scale = Math.min(1, 1200 / bitmap.width, 600 / bitmap.height);
    const canvas = el('canvas', { width: String(Math.round(bitmap.width * scale)), height: String(Math.round(bitmap.height * scale)) });
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    return this.uploadSignature(blob);
  }

  async uploadSignature(blob) {
    try {
      const data = await Api.upload('api/signature-image', blob, 'image/png');
      this.settings = data.settings;
      toast('Image de signature enregistrée.', 'ok');
      return true;
    } catch (err) {
      toast(err.message, 'error');
      return false;
    }
  }

  // --- Menus ---

  moreMenu(anchor) {
    const doc = this.doc;
    const current = this.viewer.current;
    showMenu(anchor, [
      { label: 'Enregistrer sous…', icon: 'saveAs', shortcut: 'Ctrl+Maj+S', disabled: !doc, action: () => this.saveAs() },
      ...(this.state?.app?.dialogs ? [] : [{ label: 'Télécharger', icon: 'download', disabled: !doc, action: () => this.download() }]),
      { label: 'Imprimer…', icon: 'print', shortcut: 'Ctrl+P', disabled: !doc, action: () => this.print() },
      { label: 'Fermer le document', icon: 'close', disabled: !doc, action: () => this.closeDocument() },
      '-',
      { label: 'Pivoter la page à droite', icon: 'rotate', disabled: !doc, action: () => this.rotatePages([current], 90) },
      { label: 'Pivoter la page à gauche', icon: 'rotateLeft', disabled: !doc, action: () => this.rotatePages([current], -90) },
      { label: 'Supprimer la page', icon: 'trash', disabled: !doc, action: () => this.deletePages([current]) },
      { label: 'Insérer un PDF après cette page…', icon: 'insert', disabled: !doc, action: () => this.insertPdf(current + 1) },
      '-',
      { label: 'Commentaires', icon: 'comment', disabled: !doc, action: () => this.panel.open('comments') },
      ...(doc?.signed ? [{ label: 'Signatures du document', icon: 'shield', action: () => this.panel.open('signatures') }] : []),
      { label: 'Apposer ma signature manuscrite', icon: 'image', disabled: !doc, action: () => this.placeHandwritten() },
      '-',
      { label: 'Réglages…', icon: 'settings', action: () => this.openSettings() },
      { label: 'À propos de DestriPDF', icon: 'info', action: () => this.about() },
    ]);
  }

  zoomMenu(anchor) {
    const set = (z) => () => this.viewer.setZoom(z);
    showMenu(anchor, [
      { label: 'Ajuster à la largeur', icon: 'fitWidth', shortcut: 'Ctrl+2', action: () => this.viewer.setFit('width') },
      { label: 'Page entière', icon: 'fitPage', shortcut: 'Ctrl+0', action: () => this.viewer.setFit('page') },
      '-',
      { label: '50 %', action: set(0.5) },
      { label: '75 %', action: set(0.75) },
      { label: '100 %', shortcut: 'Ctrl+1', action: set(1) },
      { label: '125 %', action: set(1.25) },
      { label: '150 %', action: set(1.5) },
      { label: '200 %', action: set(2) },
    ]);
  }

  async openSettings() {
    const s = this.settings || {};
    const author = el('input', { class: 'text-input', value: s.author || '', autocomplete: 'off' });
    const theme = el('select', { class: 'text-input' },
      el('option', { value: 'auto', text: 'Comme Windows' }), el('option', { value: 'light', text: 'Clair' }), el('option', { value: 'dark', text: 'Sombre' }));
    theme.value = s.theme || 'auto';
    const tsa = el('input', { class: 'text-input', value: s.timestamp_url || '', placeholder: 'Facultatif — ex. adresse d\'horodatage de votre autorité', autocomplete: 'off' });
    const imageControls = el('div', { class: 'sig-preview' });
    const renderImage = () => {
      imageControls.textContent = '';
      if (this.settings?.has_signature_image) {
        const img = el('img', { alt: 'Image de signature' });
        img.src = `api/signature-image?t=${Date.now()}`;
        const remove = el('button', { class: 'btn btn-danger btn-sm', type: 'button', text: 'Supprimer' });
        remove.addEventListener('click', async () => {
          const data = await Api.del('api/signature-image');
          this.settings = data.settings;
          renderImage();
        });
        imageControls.append(img, remove);
      } else {
        const draw = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Dessiner' });
        draw.addEventListener('click', async () => { if (await this.drawSignature()) renderImage(); });
        imageControls.append(el('span', { class: 'help', text: 'Aucune image.' }), draw);
      }
    };
    renderImage();
    const body = el('div', {},
      el('label', { class: 'field-label', text: 'Auteur des annotations' }), author,
      el('label', { class: 'field-label spaced', text: 'Apparence' }), theme,
      el('label', { class: 'field-label spaced', text: 'Horodatage des signatures (TSA)' }), tsa,
      el('p', { class: 'help', text: "Laissez vide pour signer sans horodatage. Avec une adresse, chaque signature est horodatée par ce service (connexion Internet nécessaire)." }),
      el('label', { class: 'field-label spaced', text: 'Image de signature manuscrite' }), imageControls);
    const result = await modal({
      title: 'Réglages',
      body,
      wide: true,
      buttons: [{ label: 'Annuler', value: null }, { label: 'Enregistrer', value: 'ok', kind: 'btn-primary', default: true }],
    });
    if (result !== 'ok') return;
    try {
      const data = await Api.post('api/settings', { author: author.value, theme: theme.value, timestamp_url: tsa.value });
      this.settings = data.settings;
      this.applyTheme();
      toast('Réglages enregistrés.', 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  about() {
    const app = this.state?.app || {};
    modal({
      title: 'DestriPDF',
      text: `Version ${app.version || ''}\nLecture, modification, annotation et signature électronique de documents PDF.\nSignature PAdES avec le certificat de votre clé, via le magasin de certificats Windows.\nMoteur PDF : MuPDF (PyMuPDF). Signature : pyHanko.`,
      buttons: [{ label: 'Fermer', value: null, kind: 'btn-primary', default: true }],
    });
  }

  // --- Clavier ---

  bindKeys() {
    document.addEventListener('keydown', (e) => {
      if (isModalOpen()) return;
      // Échap annule la ligne en cours, même si le focus est sur sa barre d'outils.
      if (e.key === 'Escape' && this.editor.isOpen) {
        e.preventDefault();
        this.editor.close();
        return;
      }
      const target = e.target;
      const typing = target.closest?.('input, textarea, select, [contenteditable="true"]');
      const ctrl = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (ctrl && key === 'o') { e.preventDefault(); this.openDialog(); return; }
      if (ctrl && key === 's') { e.preventDefault(); if (e.shiftKey) this.saveAs(); else this.save(); return; }
      if (!this.doc) return;
      if (ctrl && key === 'p') { e.preventDefault(); this.print(); return; }
      if (ctrl && key === 'f') { e.preventDefault(); $('search-input').focus(); $('search-input').select(); return; }
      if (ctrl && (key === '+' || key === '=')) { e.preventDefault(); this.viewer.zoomStep(1); return; }
      if (ctrl && (key === '-' || key === '_')) { e.preventDefault(); this.viewer.zoomStep(-1); return; }
      if (ctrl && key === '0') { e.preventDefault(); this.viewer.setFit('page'); return; }
      if (ctrl && key === '1') { e.preventDefault(); this.viewer.setZoom(1); return; }
      if (ctrl && key === '2') { e.preventDefault(); this.viewer.setFit('width'); return; }
      if (typing) return;
      if (ctrl && key === 'z' && !e.shiftKey) { e.preventDefault(); this.undo(); return; }
      if (ctrl && (key === 'y' || (key === 'z' && e.shiftKey))) { e.preventDefault(); this.redo(); return; }
      if (ctrl || e.altKey) return;
      if (e.key === 'Escape') {
        closeMenu();
        if (this.tools.selected) this.tools.deselect();
        else if (this.tools.tool !== 'select') this.tools.set('select');
        else if (this.panel.isOpen) this.panel.close();
        return;
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && this.tools.selected && !target.closest?.('#sidebar, #panel')) {
        e.preventDefault();
        this.tools.deleteSelected();
        return;
      }
      if (e.key === 'PageDown' || e.key === 'PageUp') {
        if (document.activeElement === $('viewer')) return; // défilement natif
        e.preventDefault();
        this.viewer.scrollToPage(this.viewer.current + (e.key === 'PageDown' ? 1 : -1));
        return;
      }
      if (e.key === 'Home' && document.activeElement !== $('viewer')) { this.viewer.scrollToPage(0); return; }
      if (e.key === 'End' && document.activeElement !== $('viewer')) { this.viewer.scrollToPage(this.doc.page_count - 1); return; }
      const tool = TOOLS.find((t) => t.key === key);
      if (tool && !e.shiftKey) { e.preventDefault(); this.tools.set(tool.id); }
    });
  }

  // --- Glisser-déposer ---

  bindDrop() {
    const overlay = $('drop-overlay');
    let depth = 0;
    const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
    document.addEventListener('dragenter', (e) => {
      if (!hasFiles(e)) return;
      depth += 1;
      overlay.hidden = false;
    });
    document.addEventListener('dragleave', (e) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) overlay.hidden = true;
    });
    document.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
    document.addEventListener('drop', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      overlay.hidden = true;
      const file = [...e.dataTransfer.files].find((f) => /\.pdf$/i.test(f.name) || f.type === 'application/pdf');
      if (!file) {
        toast('Déposez un fichier PDF.', 'error');
        return;
      }
      if (this.state?.app?.mode === 'window') {
        // La fenêtre transmet le chemin réel (enregistrement sur place) ; sinon, envoi du fichier.
        clearTimeout(this.pendingDrop?.timer);
        this.pendingDrop = { file, timer: setTimeout(() => this.uploadDropped(), 900) };
        return;
      }
      this.uploadFile(file);
    });
  }

  uploadDropped() {
    const pending = this.pendingDrop;
    this.pendingDrop = null;
    if (pending) this.uploadFile(pending.file);
  }

  openDropped(path) {
    if (this.pendingDrop) {
      clearTimeout(this.pendingDrop.timer);
      this.pendingDrop = null;
    }
    this.openPath(path);
  }
}

// Recadre le dessin de signature sur ses traits, avec une petite marge.
async function trimmedPng(canvas) {
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  const data = ctx.getImageData(0, 0, width, height).data;
  let x0 = width;
  let y0 = height;
  let x1 = 0;
  let y1 = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (data[(y * width + x) * 4 + 3] > 8) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  if (x1 <= x0 || y1 <= y0) return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  const pad = 12;
  x0 = Math.max(0, x0 - pad);
  y0 = Math.max(0, y0 - pad);
  x1 = Math.min(width, x1 + pad);
  y1 = Math.min(height, y1 + pad);
  const out = document.createElement('canvas');
  out.width = x1 - x0;
  out.height = y1 - y0;
  out.getContext('2d').drawImage(canvas, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
  return new Promise((resolve) => out.toBlob(resolve, 'image/png'));
}

const app = new App();
window.DestriPDF = { requestClose: () => app.requestClose(), openDropped: (path) => app.openDropped(path) };
app.boot();
