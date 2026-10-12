// Panneaux : vignettes et signets (gauche) ; commentaires, signatures et signature (droite).

import { Api } from './api.js';
import { el, iconEl, toast, modal, busy, formatDate, showMenu, promptModal } from './ui.js';

const THUMB_W = 132;

export class Sidebar {
  constructor(app) {
    this.app = app;
    this.root = document.getElementById('sidebar');
    this.thumbs = document.getElementById('thumbs');
    this.toc = document.getElementById('toc');
    this.items = [];
    this.dragFrom = null;
    this.io = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) this.loadThumb(Number(entry.target.dataset.index));
    }, { root: this.thumbs, rootMargin: '300px 0px' });
    const tabPages = document.getElementById('tab-pages');
    const tabToc = document.getElementById('tab-toc');
    const select = (pages) => {
      tabPages.setAttribute('aria-selected', String(pages));
      tabToc.setAttribute('aria-selected', String(!pages));
      this.thumbs.hidden = !pages;
      this.toc.hidden = pages;
    };
    tabPages.addEventListener('click', () => select(true));
    tabToc.addEventListener('click', () => select(false));
    document.getElementById('btn-insert').addEventListener('click', () => this.app.insertPdf(this.app.doc ? this.app.doc.page_count : 0));
  }

  setVisible(visible) {
    this.root.classList.toggle('collapsed', !visible);
    document.getElementById('btn-sidebar').setAttribute('aria-pressed', String(visible));
    try { localStorage.setItem('destripdf.sidebar', visible ? '1' : '0'); } catch { /* sans stockage */ }
  }

  render(doc) {
    this.io.disconnect();
    this.thumbs.textContent = '';
    this.items = doc.pages.map((info, index) => {
      const ratio = info.h / info.w;
      const width = info.w >= info.h ? THUMB_W : Math.round(THUMB_W * 0.82);
      const height = Math.round(width * ratio);
      const img = el('img', { class: 'thumb-img', alt: '', width: String(width), height: String(height), draggable: 'false' });
      const item = el('div', { class: 'thumb', tabindex: '0', role: 'button', draggable: 'true', dataset: { index: String(index) }, 'aria-label': `Page ${index + 1}` },
        img, el('span', { class: 'thumb-num', text: String(index + 1) }));
      const actions = el('div', { class: 'thumb-actions' });
      const rotate = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Pivoter à droite' }, iconEl('rotate'), el('span', { class: 'sr-only', text: 'Pivoter' }));
      rotate.addEventListener('click', (e) => { e.stopPropagation(); this.app.rotatePages([index], 90); });
      const remove = el('button', { class: 'icon-btn', type: 'button', 'data-tip': 'Supprimer la page' }, iconEl('trash'), el('span', { class: 'sr-only', text: 'Supprimer la page' }));
      remove.addEventListener('click', (e) => { e.stopPropagation(); this.app.deletePages([index]); });
      actions.append(rotate, remove);
      item.append(actions);
      item.addEventListener('click', () => this.app.viewer.scrollToPage(index));
      item.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.app.viewer.scrollToPage(index); }
        if (e.key === 'Delete') {
          // La touche ne concerne que la page : jamais l'annotation sélectionnée.
          e.preventDefault();
          e.stopPropagation();
          this.app.deletePages([index]);
        }
      });
      item.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showMenu(item, [
          { label: 'Pivoter à droite', icon: 'rotate', action: () => this.app.rotatePages([index], 90) },
          { label: 'Pivoter à gauche', icon: 'rotateLeft', action: () => this.app.rotatePages([index], -90) },
          '-',
          { label: 'Insérer un PDF avant', icon: 'insert', action: () => this.app.insertPdf(index) },
          { label: 'Insérer un PDF après', icon: 'insert', action: () => this.app.insertPdf(index + 1) },
          '-',
          { label: 'Supprimer la page', icon: 'trash', action: () => this.app.deletePages([index]) },
        ]);
      });
      item.addEventListener('dragstart', (e) => { this.dragFrom = index; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(index)); });
      item.addEventListener('dragover', (e) => {
        if (this.dragFrom === null) return;
        e.preventDefault();
        const rect = item.getBoundingClientRect();
        const after = e.clientY > rect.top + rect.height / 2;
        this.clearDrop();
        item.classList.add(after ? 'drop-after' : 'drop-before');
      });
      item.addEventListener('dragleave', () => item.classList.remove('drop-before', 'drop-after'));
      item.addEventListener('drop', (e) => {
        if (this.dragFrom === null) return;
        e.preventDefault();
        const after = item.classList.contains('drop-after');
        this.clearDrop();
        const from = this.dragFrom;
        this.dragFrom = null;
        let to = after ? index + 1 : index;
        if (to > from) to -= 1;
        if (to !== from) this.app.movePage(from, to);
      });
      item.addEventListener('dragend', () => { this.dragFrom = null; this.clearDrop(); });
      this.thumbs.append(item);
      this.io.observe(item);
      return { item, img, v: -1, info, width };
    });
    this.renderToc(doc);
    this.setCurrent(this.app.viewer.current);
  }

  clearDrop() {
    this.thumbs.querySelectorAll('.drop-before, .drop-after').forEach((n) => n.classList.remove('drop-before', 'drop-after'));
  }

  loadThumb(index) {
    const entry = this.items[index];
    const info = this.app.doc?.pages[index];
    if (!entry || !info || entry.v === info.v) return;
    entry.v = info.v;
    const scale = Math.round((entry.width / info.w) * (window.devicePixelRatio || 1) * 1000) / 1000;
    entry.img.src = `api/page/${index}/image?d=${this.app.doc.id}&s=${scale}&v=${info.v}`;
  }

  update(doc, structural) {
    if (structural || this.items.length !== doc.page_count) {
      this.render(doc);
      return;
    }
    doc.pages.forEach((info, i) => {
      const entry = this.items[i];
      if (entry && entry.v !== info.v && entry.v !== -1) this.loadThumb(i);
    });
  }

  setCurrent(index) {
    this.items.forEach((entry, i) => entry.item.classList.toggle('current', i === index));
    const entry = this.items[index];
    if (!entry || this.root.classList.contains('collapsed')) return;
    const box = this.thumbs.getBoundingClientRect();
    const r = entry.item.getBoundingClientRect();
    if (r.top < box.top || r.bottom > box.bottom) entry.item.scrollIntoView({ block: 'nearest' });
  }

  renderToc(doc) {
    this.toc.textContent = '';
    if (!doc.toc.length) {
      this.toc.append(el('p', { class: 'empty-note', text: 'Ce document ne contient pas de signets.' }));
      return;
    }
    for (const [level, title, page] of doc.toc) {
      const item = el('button', { class: 'toc-item', type: 'button', text: title || `Page ${page + 1}` });
      item.style.paddingLeft = `${6 + (level - 1) * 14}px`;
      item.addEventListener('click', () => this.app.viewer.scrollToPage(Math.max(0, page)));
      this.toc.append(item);
    }
  }
}

// --- Panneau de droite ---

const REASONS = ["Je suis l'auteur de ce document", "J'approuve ce document", 'Bon pour accord', 'Lu et approuvé'];

export class Panel {
  constructor(app) {
    this.app = app;
    this.root = document.getElementById('panel');
    this.tabsEl = document.getElementById('panel-tabs');
    this.body = document.getElementById('panel-body');
    this.tab = null;
    this.certs = null;
    this.certId = null;
    this.reports = null;
    this.pollTimer = null;
    document.getElementById('panel-close').addEventListener('click', () => this.close());
    app.tools.addEventListener('signframe', () => { if (this.tab === 'sign') this.renderSign(); });
  }

  get isOpen() {
    return !this.root.hidden;
  }

  open(tab) {
    this.tab = tab;
    this.root.hidden = false;
    this.renderTabs();
    this.render();
  }

  close() {
    this.root.hidden = true;
    if (this.tab === 'sign' && this.app.tools.tool === 'sign') this.app.tools.set('select');
    this.tab = null;
  }

  renderTabs() {
    this.tabsEl.textContent = '';
    const doc = this.app.doc;
    const tabs = [['comments', 'Commentaires'], ['sign', 'Signer']];
    if (doc?.signed) tabs.splice(1, 0, ['signatures', 'Signatures']);
    for (const [id, label] of tabs) {
      const tab = el('button', { class: 'tab', role: 'tab', type: 'button', 'aria-selected': String(this.tab === id), text: label });
      tab.addEventListener('click', () => this.open(id));
      this.tabsEl.append(tab);
    }
  }

  onDoc() {
    if (!this.isOpen) return;
    this.renderTabs();
    if (this.tab === 'comments') this.renderComments();
    if (this.tab === 'signatures') this.renderSignatures();
  }

  render() {
    if (this.tab === 'comments') this.renderComments();
    else if (this.tab === 'signatures') this.renderSignatures();
    else if (this.tab === 'sign') this.renderSign();
  }

  // --- Commentaires ---

  async renderComments() {
    const token = Symbol('comments');
    this.renderToken = token;
    let annots = [];
    try {
      annots = (await Api.get('api/annotations')).annots || [];
    } catch (err) {
      this.body.textContent = '';
      this.body.append(el('p', { class: 'empty-note', text: err.message }));
      return;
    }
    if (this.renderToken !== token || this.tab !== 'comments') return;
    this.body.textContent = '';
    if (!annots.length) {
      this.body.append(el('p', { class: 'empty-note', text: 'Aucune annotation. Les notes, surlignages, textes ajoutés et dessins apparaissent ici.' }));
      return;
    }
    let page = -1;
    for (const a of annots) {
      if (a.page !== page) {
        page = a.page;
        this.body.append(el('div', { class: 'comment-group', text: `Page ${page + 1}` }));
      }
      const dot = el('span', { class: 'comment-dot' });
      dot.style.background = a.color || 'var(--line-strong)';
      const meta = [a.author, formatDate(a.modified)].filter(Boolean).join(' · ');
      const item = el('button', { class: 'comment', type: 'button' }, dot,
        el('span', { class: 'comment-main' },
          el('span', { class: 'comment-kind', text: a.label }),
          el('span', { class: 'comment-meta', text: meta ? ` · ${meta}` : '' }),
          a.content ? el('div', { class: 'comment-text', text: a.content }) : null));
      item.addEventListener('click', () => this.app.focusAnnotation(a.page, a.id, a.rect));
      this.body.append(item);
    }
  }

  // --- Signatures du document ---

  async loadReports() {
    clearTimeout(this.pollTimer);
    try {
      const data = await Api.get('api/signatures');
      if (data.pending) {
        this.pollTimer = setTimeout(() => this.loadReports(), 700);
        return { pending: true };
      }
      this.reports = data.reports || [];
      this.app.updateSignatureBanner(this.reports, data.error);
      if (this.tab === 'signatures') this.renderSignatures(true);
      return { pending: false, reports: this.reports };
    } catch (err) {
      this.app.updateSignatureBanner([], err.message);
      return { pending: false, reports: [] };
    }
  }

  renderSignatures(fromLoad = false) {
    this.body.textContent = '';
    if (!fromLoad || this.reports === null) {
      this.body.append(el('div', { class: 'notice' }, el('span', { text: 'Vérification des signatures…' })));
      if (!fromLoad) this.loadReports();
      return;
    }
    if (!this.reports.length) {
      this.body.append(el('p', { class: 'empty-note', text: 'Ce document ne contient aucune signature électronique.' }));
      return;
    }
    for (const r of this.reports) {
      const iconName = r.status === 'valid' ? 'shield' : r.status === 'warning' ? 'shieldWarn' : 'shieldBad';
      const word = r.status === 'valid' ? 'Valide' : r.status === 'warning' ? 'À vérifier' : 'Invalide';
      const card = el('div', { class: `sig-report ${r.status}`, role: 'button', tabindex: '0' },
        el('div', { class: 'sig-report-head' }, iconEl(iconName), el('span', { class: 'sig-report-name', text: r.signer || 'Signataire inconnu' }),
          el('span', { class: `badge ${r.status === 'valid' ? 'ok' : r.status === 'warning' ? 'warn' : 'bad'}`, text: word })),
        el('div', { class: 'sig-report-summary', text: r.summary }),
        el('dl', {},
          el('dt', { text: 'Date' }), el('dd', { text: formatDate(r.signed_at) || '—' }),
          el('dt', { text: 'Émetteur' }), el('dd', { text: r.issuer || '—' }),
          r.reason ? el('dt', { text: 'Motif' }) : null, r.reason ? el('dd', { text: r.reason }) : null,
          r.location ? el('dt', { text: 'Lieu' }) : null, r.location ? el('dd', { text: r.location }) : null,
          el('dt', { text: 'Certificat' }), el('dd', { text: r.qualified ? 'Qualifié eIDAS' : 'Non qualifié' }),
          el('dt', { text: 'Confiance' }), el('dd', { text: r.trust_detail || '—' }),
          el('dt', { text: 'Révocation' }), el('dd', { text: r.ltv ? 'État intégré : vérifiable à long terme (LTV)' : 'Non intégré : vérification en ligne seulement' }),
          el('dt', { text: 'Heure' }), el('dd', { text: r.timestamp ? 'Attestée par une autorité d\'horodatage' : 'Horloge de l\'ordinateur du signataire' })));
      if (r.errors?.length) card.append(el('div', { class: 'sig-report-summary', text: r.errors.join(' ') }));
      const go = () => { if (r.page_index !== null && r.page_index !== undefined && r.rect) { this.app.viewer.scrollToPage(r.page_index); this.app.viewer.scrollToRect(r.page_index, r.rect); } };
      card.addEventListener('click', go);
      card.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
      this.body.append(card);
    }
  }

  // --- Signature électronique ---

  async loadCertificates(force = false) {
    if (this.certs && !force) return this.certs;
    try {
      this.certs = (await Api.get('api/certificates')).certificates || [];
      this.certError = null;
    } catch (err) {
      this.certs = [];
      this.certError = err.message;
    }
    const usable = this.certs.filter((c) => c.can_sign);
    if (!usable.some((c) => c.id === this.certId)) this.certId = usable[0]?.id || null;
    return this.certs;
  }

  async renderSign() {
    const settings = this.app.settings || {};
    if (!this.signDraft) {
      this.signDraft = {
        visible: settings.sign_visible !== false,
        withImage: settings.sign_with_image !== false,
        reason: settings.sign_reason || '',
        location: settings.sign_location || '',
      };
    }
    const draft = this.signDraft;
    const body = this.body;
    const keepScroll = body.scrollTop;
    body.textContent = '';

    // Certificat
    const certSection = el('div', { class: 'panel-section' }, el('span', { class: 'field-label', text: 'Certificat de signature' }));
    const list = el('div', { class: 'cert-list', role: 'radiogroup', 'aria-label': 'Certificat' });
    certSection.append(list);
    const refresh = el('button', { class: 'btn btn-ghost btn-sm', type: 'button' }, iconEl('rotate'), el('span', { text: 'Actualiser' }));
    refresh.addEventListener('click', async () => {
      refresh.disabled = true;
      await this.loadCertificates(true);
      this.renderSign();
    });
    body.append(certSection);
    if (this.certs === null) {
      list.append(el('div', { class: 'notice' }, el('span', { text: 'Recherche des certificats…' })));
      this.loadCertificates().then(() => { if (this.tab === 'sign') this.renderSign(); });
    } else if (!this.certs.length) {
      list.append(el('div', { class: 'notice warn' },
        el('div', { text: this.certError || 'Aucun certificat de signature trouvé.' }),
        el('div', { class: 'help', text: 'Branchez votre clé USB de signature, attendez quelques secondes puis cliquez sur « Actualiser ». Le logiciel de la clé (fourni par votre autorité de certification) doit être installé.' })));
    } else {
      for (const c of this.certs) {
        const badges = el('span', { class: 'badges' });
        if (c.qualified) badges.append(el('span', { class: 'badge ok', text: 'Qualifié eIDAS' }));
        if (c.hardware) badges.append(el('span', { class: 'badge', text: 'Clé matérielle' }));
        if (c.expired) badges.append(el('span', { class: 'badge bad', text: 'Expiré' }));
        else if (!c.can_sign) badges.append(el('span', { class: 'badge warn', text: 'Inutilisable' }));
        const item = el('button', {
          class: `cert${c.can_sign ? '' : ' disabled'}`, type: 'button', role: 'radio', 'aria-checked': String(this.certId === c.id), disabled: !c.can_sign || undefined,
        }, el('span', { class: 'cert-radio' }), el('span', { class: 'cert-main' },
          el('span', { class: 'cert-name', text: c.subject }),
          el('span', { class: 'cert-meta', text: [c.organization, c.issuer].filter(Boolean).join(' — ') }),
          el('span', { class: 'cert-meta', text: `Valable jusqu'au ${formatDate(c.not_after, false)}` }),
          badges));
        item.addEventListener('click', () => { this.certId = c.id; this.renderSign(); });
        list.append(item);
      }
    }
    certSection.append(el('div', { class: 'panel-actions' }, refresh));

    // Apparence
    const appearance = el('div', { class: 'panel-section' }, el('span', { class: 'field-label', text: 'Apparence' }));
    const visible = el('input', { type: 'checkbox' });
    visible.checked = draft.visible;
    visible.addEventListener('change', () => {
      draft.visible = visible.checked;
      if (!draft.visible) {
        this.app.tools.clearSignFrame();
        if (this.app.tools.tool === 'sign') this.app.tools.set('select');
      } else {
        this.app.tools.set('sign');
      }
      this.renderSign();
    });
    appearance.append(el('label', { class: 'check' }, visible, el('span', { text: 'Signature visible sur la page' })));
    if (draft.visible) {
      const frame = this.app.tools.signFrame;
      const place = el('button', { class: 'btn btn-secondary btn-sm', type: 'button' }, iconEl('rect'), el('span', { text: frame ? 'Déplacer le cadre' : 'Placer le cadre' }));
      place.addEventListener('click', () => this.app.tools.set('sign'));
      appearance.append(el('div', { class: 'sign-place' }, place,
        el('span', { class: 'sign-place-state', text: frame ? `Cadre placé page ${frame.page + 1}.` : 'Tracez le cadre sur la page, ou cliquez à son emplacement.' })));
      const withImage = el('input', { type: 'checkbox' });
      withImage.checked = draft.withImage;
      withImage.addEventListener('change', () => { draft.withImage = withImage.checked; this.renderSign(); });
      appearance.append(el('label', { class: 'check' }, withImage, el('span', { text: 'Ajouter mon image de signature manuscrite' })));
      if (draft.withImage) appearance.append(this.signatureImageControls());
    }
    body.append(appearance);

    // Motif et lieu
    const details = el('div', { class: 'panel-section' });
    const reason = el('input', { class: 'text-input', list: 'reasons', value: draft.reason, placeholder: 'Facultatif', autocomplete: 'off' });
    reason.addEventListener('input', () => { draft.reason = reason.value; });
    const datalist = el('datalist', { id: 'reasons' }, ...REASONS.map((r) => el('option', { value: r })));
    const location = el('input', { class: 'text-input', value: draft.location, placeholder: 'Facultatif', autocomplete: 'off' });
    location.addEventListener('input', () => { draft.location = location.value; });
    details.append(el('label', { class: 'field-label', text: 'Motif' }), reason, datalist,
      el('label', { class: 'field-label spaced', text: 'Lieu' }), location);
    body.append(details);

    // Action
    const sign = el('button', { class: 'btn btn-primary', type: 'button', disabled: !this.certId || undefined }, iconEl('sign'), el('span', { text: 'Signer et enregistrer' }));
    sign.addEventListener('click', () => this.app.signDocument(this.signPayload()));
    body.append(el('div', { class: 'panel-actions panel-actions-sticky' }, sign));
    const notes = el('div', { class: 'panel-section' });
    notes.append(el('p', { class: 'help', text: 'Le code PIN de votre clé est demandé par la fenêtre de son logiciel. Le document signé est enregistré dans un nouveau fichier : l\'original reste intact.' }));
    if (settings.sign_ltv !== false) notes.append(el('p', { class: 'help', text: 'Comme Acrobat, l\'état de révocation de votre certificat est demandé à votre autorité de certification et intégré au document (validation à long terme) : connexion Internet utilisée au moment de signer.' }));
    if (settings.timestamp_url) notes.append(el('p', { class: 'help', text: `Horodatage : ${settings.timestamp_url}` }));
    if (this.app.doc?.dirty) notes.append(el('p', { class: 'help', text: 'Les modifications en cours sont incluses dans le document signé.' }));
    body.append(notes);

    // Signature manuscrite seule
    const simple = el('div', { class: 'panel-section' }, el('span', { class: 'field-label', text: 'Signature manuscrite seule' }),
      el('p', { class: 'help', text: 'Image de votre signature posée sur la page, sans valeur de signature électronique.' }));
    const stamp = el('button', { class: 'btn btn-ghost btn-sm', type: 'button' }, iconEl('image'), el('span', { text: 'Apposer mon image de signature' }));
    stamp.addEventListener('click', () => this.app.placeHandwritten());
    simple.append(el('div', { class: 'panel-actions' }, stamp));
    body.append(simple);
    body.scrollTop = keepScroll;
  }

  signatureImageControls() {
    const wrap = el('div', { class: 'sig-preview' });
    const has = this.app.settings?.has_signature_image;
    if (has) {
      const img = el('img', { alt: 'Image de signature enregistrée' });
      img.src = `api/signature-image?t=${Date.now()}`;
      wrap.append(img);
    } else {
      wrap.append(el('span', { class: 'help', text: 'Aucune image enregistrée.' }));
    }
    const draw = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: has ? 'Refaire' : 'Dessiner' });
    draw.addEventListener('click', async () => { if (await this.app.drawSignature()) this.renderSign(); });
    const load = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Importer' });
    load.addEventListener('click', async () => { if (await this.app.importSignature()) this.renderSign(); });
    wrap.append(draw, load);
    return wrap;
  }

  signPayload() {
    const draft = this.signDraft;
    const frame = this.app.tools.signFrame;
    return {
      certificate: this.certId,
      visible: draft.visible ? (frame ? { page: frame.page, rect: frame.rect } : 'missing') : null,
      with_image: draft.visible && draft.withImage && Boolean(this.app.settings?.has_signature_image),
      reason: draft.reason.trim(),
      location: draft.location.trim(),
    };
  }

  resetAfterSign() {
    this.app.tools.clearSignFrame();
    if (this.app.tools.tool === 'sign') this.app.tools.set('select');
    this.reports = null;
  }
}
