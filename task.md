# Suivi — DestriPDF

## Version 1.0 — 12 octobre 2026

### Choix vérifiés par essais

- [x] Caviardage d'une bande de ligne : MuPDF retire un glyphe dès ~10 % de
  recouvrement de sa boîte métrique ; bande au cœur de la ligne, voisines
  contrôlées après coup, repli sur une bande plus fine.
- [x] Réécriture TextWriter avec police Windows réduite par fontTools (€, Œ, ’
  corrects ; table Unicode sans ambiguïté espace/tiret).
- [x] Journal MuPDF écarté (`get_text` d'une page pivotée modifie le document ;
  `insert_pdf`/`show_pdf_page` refusés dans une opération) : instantanés
  `tobytes` (~30 ms) sous budget de 400 Mo.
- [x] Texte modifiable extrait du seul contenu de page (`fz_run_page_contents`) :
  textes ajoutés, valeurs de champs et apparences de signature exclus.
- [x] Texte libre : cadre mesuré avec `Font("helv").text_length` (même mesure que
  la mise en page MuPDF ; `get_text_length` sous-estime « — » et « € »).

### Réalisé

- [x] Socle : `document.py` (rendu PNG maison hors verrou / JPEG pour les pages
  image, texte en segments coupés aux grands écarts, alignement détecté,
  modification de ligne, annotations, formulaires, pages, effacement réel,
  recherche, enregistrement complet ou incrémental unique pour un PDF signé,
  mot de passe), `fonts.py`, `settings.py`.
- [x] Signature : `wincert.py` (magasin Windows, CNG/CryptoAPI par ctypes,
  chaîne Windows, erreurs PIN en clair, certificats qualifiés eIDAS repérés),
  `pades.py` (PAdES B-B, horodatage facultatif B-T, apparence Roboto avec image
  manuscrite, pages pivotées, contresignature, vérification + confiance Windows).
- [x] Serveur local : jeton, Host/Origin/en-tête, CSP stricte, corps non lu vidé
  (connexions persistantes saines), cache des rendus.
- [x] Interface DestriMix : accueil et récents, vignettes et signets, pastille
  de navigation, outils à libellés courts, barre d'options par outil, éditeur
  de ligne, texte libre, notes, surlignage, dessin, formes, effacement,
  sélection/déplacement/suppression d'annotation, champs de formulaire,
  panneaux Commentaires/Signatures/Signer, bandeau de vérification, réglages,
  signature manuscrite dessinée ou importée, impression, glisser-déposer
  (chemin réel en mode fenêtre), thème sombre, raccourcis clavier.
- [x] Paquet : PyInstaller en mode dossier (92 Mo), icône, informations de
  version, installateur Inno Setup par utilisateur (34 Mo) avec « Ouvrir avec »
  et déclaration aux applications par défaut.

### Relecture indépendante (agent, 12 octobre) — 9 constats, tous traités

- [x] Critique : images de pages d'un autre document servies par le cache (mêmes
  URL d'un document à l'autre) → identifiant du document dans l'URL, refus 409
  d'une image d'un document remplacé, cache durable seulement si l'identifiant
  correspond ; contrôle ajouté à la recette.
- [x] « Enregistrer, annuler, autre modification » déclaré enregistré → un
  identifiant unique par état dans `History`.
- [x] Apparence de signature à l'envers sur page /Rotate 90 et 270 → sens de
  rotation corrigé ; test d'orientation (échoue sur l'ancien code).
- [x] Signature impossible d'un PDF protégé → mot de passe transmis à pyHanko
  (`encrypt`, contrôle du résultat), /Encrypt direct écrit par MuPDF converti en
  objet indirect ; PDF à mot de passe et PDF « restreint » testés.
- [x] PDF signé réparé à l'ouverture : refus explicite, réécriture complète
  seulement après confirmation (signatures invalidées, dit à l'utilisateur).
- [x] Lecture qui modifiait la page (/Rotate hérité recopié) → extraction de
  texte, recherche et repérage des images par matrice de dé-rotation, sans
  mutation ; test « la lecture ne modifie rien ».
- [x] Échap sur la barre de l'éditeur validait → annule ; Suppr sur une vignette
  ne touche plus l'annotation sélectionnée ; derniers accès MuPDF sous verrou.
- [x] Constaté en vraie fenêtre : la fermeture se fiait à l'état connu de
  l'interface → l'état du serveur est relu avant de fermer.

### Validations

- [x] 57 tests (`pytest tests`) : signature CNG RSA/ECDSA, chaîne, PAdES
  visible/invisible, page pivotée, contresignature, PIN annulé, horodatage par
  autorité locale simulée, édition de ligne et de montant, voisins intacts,
  annotations, formulaires, pages, annulation, mot de passe, enregistrement
  incrémental d'un PDF signé, sécurité HTTP, connexion persistante.
- [x] Robustesse sur PDF réels (copies en mémoire) : 70 modifications de ligne
  sur 70 (factures DestriCenter et guide ReportLab), voisins, tracés et images
  intacts ; 150 pages numérisées : ouverture < 1 ms, rendu 90 ms, annotation
  31 ms, annuler 3 ms.
- [x] Recette Edge sans fenêtre (`scripts\recette.ps1`) : 27 parcours sur 27,
  sur les sources puis sur l'exécutable figé ; 1024×680, 1280×720, 1920×1080,
  aucun débordement horizontal, console propre.
  Défauts trouvés et corrigés : icônes de l'éditeur superposées, style en ligne
  refusé par la CSP, ligne supprimée au lieu d'être remplacée après Ctrl+A,
  texte d'annotation pris pour du texte de page, grille élargie par le panneau
  de droite, notification masquant la pastille, écran d'accueil écrasé,
  contraste du mode sombre, retour à la ligne du texte libre.
- [x] Mode fenêtre réel : fenêtre en 0,6 s, première page en 0,8 s (1,1 s à
  froid, 2,2 s au tout premier lancement après installation) avec l'exécutable
  figé ; deux fenêtres simultanées ; fermeture d'un document modifié retenue
  jusqu'à la réponse de l'utilisateur.
- [x] Test de fumée de l'exécutable figé (`scripts\smoke.py`) : 14/14, signature
  et vérification comprises.
- [x] Installateur : installation silencieuse, lancement, désinstallation sans
  résidu (programme, raccourcis, clés « Ouvrir avec »).

### Reste à faire / limites

- [ ] Première signature avec la vraie clé de Florent (PIN saisi par lui) et
  contrôle dans Adobe Reader : seul essai impossible sans la clé.
- [ ] Clés accessibles uniquement par PKCS#11 (hors magasin Windows) : non gérées.
- [ ] Recomposition d'un paragraphe entier : modification ligne par ligne.
- [ ] OCR des documents numérisés : hors périmètre.
