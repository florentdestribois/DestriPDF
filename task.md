# Suivi — DestriPDF

Versions 1.0 et 1.1 : `docs/archives/TASK-1.0-1.1.md` (chercher, ne pas lire en entier).

## Version 1.2.0 — 12 octobre 2026, fin d'après-midi

Retour de Florent avec la même facture (INV_2026_00119) signée par Acrobat et
par DestriPDF 1.1.0 : « Ce n'est toujours pas la même signature ». Puis :
« Permet ensuite un export en .jpg puis génère toujours un installateur à
chaque release ». La 1.1.1 (cadre Acrobat) a été construite mais pas installée
(autorisation Windows annulée) : son contenu est repris dans la 1.2.0.

### Constat (fichiers relus en lecture seule)

- [x] Signatures électroniques équivalentes : même clé CertEurope, certificat
  qualifié. DestriPDF : PAdES (ETSI.CAdES.detached) avec état de révocation
  intégré (4 réponses OCSP de CertEurope : LTV confirmé avec la vraie clé).
  Acrobat du poste : ancien format PKCS#7 détaché, état de révocation dans la
  signature.
- [x] Écarts du cadre : Acrobat remplit chaque moitié au plus grand (nom coupé
  dans le mot : « DESTRIB / OIS »), Myriad Pro noir, logo d'Acrobat pâle au
  centre ; DestriPDF 1.1.0 : nom deux fois plus petit, Roboto gris foncé.
- [x] Écart de verdict : DestriPDF disait « à vérifier » la première de deux
  signatures ; Acrobat les dit valides.

### Réalisé

- [x] Mise en page d'Acrobat : chaque moitié remplie au plus grand, coupure dans
  un mot trop large, marge de 1 pt, noir, Segoe UI ; emblème DestriPDF pâle au
  centre (logo d'Acrobat : marque d'Adobe ; Myriad Pro : police d'Adobe).
  Comparé au cadre d'Acrobat de la facture : mêmes retours à la ligne.
- [x] Verdict : une contresignature laisse la signature précédente valide, sauf
  interdiction DocMDP ; annotation, valeur de champ ou métadonnée modifiée
  ensuite : « à vérifier », champ nommé. Vérifié sur la facture réelle : les
  deux signatures DestriPDF et celle d'Acrobat sont « valides » et « LTV ».
- [x] Export JPG (menu ⋯) : page affichée ou toutes, 150 ou 300 ppp, une image
  par page numérotée, résolution inscrite, très grande page réduite et signalée.
- [x] Release : `scripts\release.ps1` (versions alignées, arbre propre sur main,
  `build.ps1` complet, installateur joint à la release GitHub avec son SHA-256) ;
  règle inscrite dans AGENTS.md, plan et README.
- [x] Version 1.2.0.

### Relecture indépendante de la 1.1.0 (agent) — constats traités

- [x] Valeur de champ (montant) modifiée après la signature déclarée valide
  (introduit par la 1.1.1 non livrée) : comparaison des valeurs `/V` entre la
  révision signée et la dernière.
- [x] Métadonnées modifiées présentées comme « aucune modification » :
  comparaison de /Info et du XMP (titre, auteur…), sans les dates et le
  producteur que pyHanko réécrit à chaque mise à jour.
- [x] Révocation non décelée si la liste de la racine manque : contrôle souple
  du seul signataire avant le PIN.
- [x] Horodatage « attesté » pour tout jeton : exigé intact, valide et autorité
  approuvée par Windows ; sinon « jeton présent, autorité non vérifiée ».
- [x] Horodatage + LTV : racine de la TSA prise dans la chaîne construite par
  Windows à partir de son jeton ; messages selon la cause (signataire,
  autorité émettrice, horodatage).
- [x] État de révocation obtenu mais DSS non écrit après le PIN : la signature
  est gardée (signature étape par étape), message explicite.
- [x] Heure du cadre et `/M` identiques à la seconde (`system_time` imposé).
- [x] LTV non reconnue sans racine intégrée ou `/M` sans fuseau : racines de la
  chaîne Windows, heure locale par défaut ; état archivé dans une signature
  PKCS#7 d'Acrobat lu, autorité émettrice pour ancre comme Acrobat.
- [ ] Mise à jour d'une installation « par utilisateur » 1.0.0 : seconde
  installation possible ; aucune ne subsiste (désinstallée sur ce poste, aucune
  autre diffusion). Proxy obligatoire : aiohttp ne l'utilise pas (LTV en repli).

### Validations

- [x] Tests : 79 (contresignature valide, montant modifié, métadonnées, XMP,
  horodatage non vérifié, LTV avec horodatage, révocation sans liste racine,
  DSS illisible, heure du cadre, messages de révocation, archive PKCS#7
  d'Acrobat avec répondeur OCSP simulé, export JPG).
- [x] Recette Edge sur les sources : 28 parcours sur 28 (export JPG compris).
- [x] `build.ps1` 1.2.0 : 79 tests, test de fumée de l'exécutable figé 16/16
  (LTV avec autorité simulée), installateur `DestriPDF-1.2.0-installation.exe`
  (34,5 Mo) ; recette Edge sur l'exécutable figé : 28 parcours sur 28.
- [x] Release `v1.2.0` publiée à la demande de Florent :
  https://github.com/florentdestribois/DestriPDF/releases/tag/v1.2.0 (étiquette
  sur `eaf2bf8`), installateur reconstruit et testé par `release.ps1` (79 tests,
  fumée 16/16) puis joint ; SHA-256 `571556155E632694C07B00A113AF1C0F75DB7004
  2269852558940E4C943586DE`, identique sur GitHub. Premier passage : `gh` n'a pas
  trouvé git (hors PATH), release créée à la main avec le même installateur ;
  script corrigé (git dans le PATH de `gh`, `--repo` tiré d'`origin`).
- [x] Installé dans `C:\Program Files\DestriPDF` (1.1.0 → 1.2.0, autorisation
  Windows acceptée) : 717 fichiers identiques au paquet de la release, entrée
  « DestriPDF 1.2.0 », « Ouvrir avec » en place, lancement sans droits correct.

## Version 1.2.1 — 12 octobre 2026, soir

Demande de Florent : « prépare la 1.2.1 et publie la release », après le
DestriPDF resté sans fenêtre quand DestriCenter l'a lancé (fiche technique
ouverte par `os.startfile`, 14 h 20) : WebView2 chargé mais en attente
(LpcReply), aucun processus WebView2 créé, aucun journal. Écartés : variables
`_PYI_*` héritées (essai), `PATH` avec le `_MEI` de DestriCenter (même
WebView2Loader), élévation, mise à jour de WebView2, fichier (le même PDF
s'ouvre depuis l'Explorateur).

### Réalisé

- [x] `destripdf/startup.py` : PATH hérité nettoyé des dossiers `_MEI…` d'une
  autre application avant WebView2 ; démarrage journalisé (programme lanceur,
  document, version de WebView2, dossiers retirés), durées « fenêtre affichée »
  et « interface chargée ».
- [x] Surveillance : fenêtre absente après 20 s → piles de tous les fils
  d'exécution dans `logs\blocage-….txt`, relance unique détachée (hors de
  l'objet tâche du lanceur si permis, variables PyInstaller et Python retirées,
  dossier WebView2 de secours), sinon message natif et fin du processus.
- [x] Recette `scripts\recette\surveillance_demarrage.py` (fenêtre bloquée
  simulée, journal et réglages isolés).

### Validations

- [x] Tests : 85 (PATH, environnement de relance, surveillance, relevé des
  piles, programme lanceur, version de WebView2).
- [x] `build.ps1` 1.2.1 : 85 tests, fumée de l'exécutable figé 16/16,
  installateur.
- [x] Recette `surveillance_demarrage.py` sur l'exécutable figé : 9 contrôles
  sur 9 (dossier étranger retiré du PATH, relevé puis relance unique, relance au
  PATH propre, message, fin avec le code 1, deux relevés de piles). Le relevé
  montre aussi le fil d'ouverture en attente de la fenêtre (`window.title`).
- [x] Démarrage normal de l'exécutable figé : fenêtre en 0,43 s, interface en
  0,84 s, première page en 1,0 s ; surveillance non déclenchée après 25 s ;
  fermeture propre.
- [x] Release `v1.2.1` publiée par `scripts\release.ps1 -Publish` sans
  intervention (correctif du script validé) :
  https://github.com/florentdestribois/DestriPDF/releases/tag/v1.2.1, étiquette
  sur `cd06e28`, SHA-256 `53001FEFCFF1557DE90DC7B516484FCDD010187EAAB616C9C440279
  51E972705` identique sur GitHub.
- [x] Recette de surveillance sur l'exécutable de la release : 9/9, trois fois
  de suite. Le script de recette cliquait sur IDOK alors que le bouton du
  message porte l'identifiant 2 (instance d'essai restée à l'écran, arrêtée) :
  clic sur le vrai bouton, arrêt de l'instance d'essai en dernier recours.
- [x] Installé sur le poste à la demande de Florent (1.2.0 → 1.2.1, autorisation
  Windows acceptée) : installateur identique à celui de la release, 717 fichiers
  identiques au paquet, entrée « DestriPDF 1.2.1 » ; lancement sans droits :
  fenêtre en 0,45 s, interface en 0,9 s, surveillance non déclenchée après
  25 s, fermeture propre.

## Version 1.3.0 — impression en livret, 19 octobre 2026

Demande de Florent : « Adobe Acrobat permet une impression en livret simple des
pages, permets cela avec DestriPDF ».

### Réalisé

- [x] Boîte « Imprimer » (menu ⋯ et Ctrl+P) : pages normales ou livret ; feuille
  A4 paysage (pages réduites en A5) ou A3 paysage (A4 en taille réelle),
  reliure à gauche ou à droite, recto verso, rectos seuls ou versos seuls ;
  nombre de feuilles et de pages blanches affiché ; consigne « retourner sur le
  bord court ».
- [x] `static/js/booklet.js` : ordre de piqûre à cheval, blancs en fin de
  document. Feuilles en pages CSS nommées (`@page booklet-a4/a3`), chaque page
  réduite sans déformation et centrée dans sa moitié.
- [x] Zone d'impression vidée à `afterprint` (et non plus après 1 s).

### Validations

- [x] Tests : 85 passés.
- [x] Recette Edge : 30 parcours sur 30 (18 + 12) ; nouveaux : ordre
  d'imposition pour 1, 2, 4, 5 et 8 pages, reliure à droite, rectos et versos
  seuls ; boîte Imprimer par Ctrl+P ; sortie réelle `Page.printToPDF` : 2 faces
  A4 paysage (842 × 595 pt) pour 2 pages, page 1 à droite du recto, page 2 à
  gauche du verso (captures relues).
- [ ] Essai sur l'imprimante du poste (recto verso bord court, pliage) : à faire
  par Florent.
- [x] Version 1.3.0 (code, installateur, informations de l'exécutable,
  README) ; publication demandée par Florent : `scripts\release.ps1 -Publish`.
- [x] Release `v1.3.0` publiée sans intervention :
  https://github.com/florentdestribois/DestriPDF/releases/tag/v1.3.0, étiquette
  sur `85f0e8e` ; `build.ps1` : tests, fumée de l'exécutable figé 16/16,
  installateur `DestriPDF-1.3.0-installation.exe` (34,5 Mo) ; SHA-256
  `E7A3D28D31301BFC4B8C78AF075E1E78C84E6461D7EBA721EBCAF461743952CC`
  identique sur GitHub.
- [x] Installée sur le poste à la demande de Florent (1.2.1 → 1.3.0,
  autorisation Windows acceptée) : installateur identique à celui de la
  release, 718 fichiers identiques au paquet (`booklet.js` compris), entrée
  « DestriPDF 1.3.0 » ; lancement sans droits : fenêtre en 0,9 s, fermeture
  propre.

## Version 1.3.1 — livret par l'imprimante, 19 octobre 2026 (non publiée)

Retour de Florent sur la 1.3.0 : « ce n'est pas bon, il ne s'imprime pas comme
un vrai livret, c'est une option des paramètres d'imprimante qu'il faut
lancer ».

### Constats

- [x] La 1.3.0 imprimait par l'aperçu d'Edge, sans accès aux réglages du pilote.
- [x] `ShowPrintUI(System)` de WebView2 et même `PrintDlgEx` ouvrent sur ce poste
  la boîte moderne de Windows 11 (« … – Imprimer »), sans accès sûr au pilote.
- [x] Imprimante de l'atelier : Canon iR-ADV C3520, « Canon Office XPS Class
  Driver ». Ses capacités déclarent `psk:JobBindAllDocuments` = `psk:Booklet`,
  mais sa fenêtre de réglages (onglets Disposition, Papier/qualité) ne montre
  que « Pages par feuille » : le livret ne s'y choisit pas.

### Réalisé

- [x] `destripdf/printing.py` : imprimantes du poste et imprimante par défaut,
  préférences du pilote (`DocumentProperties`, au-dessus de la fenêtre, gardées
  pour la session), option Livret par le schéma d'impression converti en
  DEVMODE, copies assemblées dans le DEVMODE, pages rendues par MuPDF à la
  résolution de l'imprimante (300 ppp au plus), ajustées, centrées, page paysage
  tournée vers la gauche, envoi GDI.
- [x] Routes `GET api/printers`, `GET api/printers/capabilities`,
  `POST api/print/preferences`, `POST api/print` (imprimante du poste exigée,
  pages « 1-3, 5 », copies 1 à 99) ; dernière imprimante retenue
  (`last_printer`).
- [x] Boîte Imprimer de l'interface (Ctrl+P, menu ⋯) : imprimante, bouton
  « Préférences de l'imprimante… », case « Imprimer en livret » grisée si le
  pilote ne la propose pas, pages, copies. Mise en page livret maison de la 1.3.0
  retirée (`booklet.js`). Impression web gardée en secours (`webPrint`).
- [x] Défauts trouvés et corrigés en recette : page pivotée imprimée à l'envers
  (sens du quart de tour ; test qui échouait sur l'ancien code) ; erreur 500 sur
  les capacités quand deux requêtes chargeaient .NET en même temps (verrou).

### Validations

- [x] Tests : 97 (routes et refus, plages de pages, copies, placement, rendu
  BGRA, page pivotée droite, requêtes simultanées ; envoi réel au pilote
  « Microsoft Print to PDF » : 2 exemplaires assemblés 1-2-1-2, page paysage
  tournée ; livret sur le vrai pilote Canon : option inscrite, gardée avec
  2 copies, retirée — sans rien imprimer).
- [x] Fenêtre WebView2 réelle : préférences du pilote Canon ouvertes au-dessus de
  la fenêtre (bloquée pendant ce temps), Annuler sans effet.
- [x] Recette Edge : 30 parcours sur 30 ; boîte Imprimer (livret proposé pour la
  Canon seule), page 2 imprimée dans un fichier par « Microsoft Print to PDF »,
  droite (capture relue).
- [x] `build.ps1` 1.3.1 : 97 tests, fumée de l'exécutable figé 19/19
  (imprimantes, options des pilotes, impression par le pilote), installateur.
- [x] Installée sur le poste à la demande de Florent, pour essai avant
  publication (1.3.0 → 1.3.1, autorisation Windows acceptée) : 717 fichiers
  identiques au paquet, entrée « DestriPDF 1.3.1 », fenêtre en 0,8 s sans
  droits. `booklet.js` de la 1.3.0 resté dans le dossier (inutilisé) : retiré par
  `[InstallDelete]` à la prochaine construction.
- [x] Essai de Florent sur la Canon : échec, « cela demande un papier A4r à
  l'imprimante qu'elle ne connaît pas » (fonction Livret de l'imprimante).
  Remplacée en 1.3.2.

## Version 1.3.2 — livret mis en page par DestriPDF, 19 octobre 2026 (non publiée)

Demande de Florent : « ça ne fonctionne pas. Revoit complètement cette fonction
afin de garantir que ça marche ».

### Constats

- [x] File d'impression locale de la Canon vide (aucun travail bloqué côté
  poste). Le pilote ne connaît aucun format « A4R » : c'est la fonction Livret
  de l'imprimante qui le réclame (A4 chargé dans l'autre sens, pour son pliage).
- [x] Le pilote propose A4 et A3 ordinaires (`psk:ISOA4`, `psk:ISOA3`), le
  recto verso bord court, l'orientation paysage, la désactivation du livret et
  de l'agrafage, une page par feuille. Ticket utilisateur par défaut : recto
  verso bord long (cause probable des versos tête en bas de la 1.3.0).

### Réalisé

- [x] `destripdf/booklet.py` : ordre de piqûre à cheval, faces composées en
  PDF (pages telles qu'affichées, annotations et champs intégrés à une copie,
  rotation compensée, page paysage tournée vers la gauche), marge au pli et aux
  bords. La fonction Livret des imprimantes n'est plus jamais demandée.
- [x] `printing.py` : réglages imposés pour cette impression (format ordinaire
  décrit en portrait, jamais tourné ; paysage ; recto verso bord court ; livret
  et agrafage de l'imprimante désactivés ; une page par feuille), relus dans le
  pilote avant l'envoi, refus explicite sinon ; faces posées sur tout le papier,
  taille réelle, pli au milieu exact ; versos retournés sur demande.
- [x] Routes : `GET api/print/booklet-plan`, `POST api/print` avec
  `layout`/`sheet`/`binding`/`flip_backs` ; « Retourner les versos » retenu par
  imprimante (`booklet_flipped`).
- [x] Boîte Imprimer : mise en page (pages normales, livret), feuille A4 → livret
  A5 ou A3 → livret A4, reliure, retournement des versos, aperçu de la feuille 1
  (recto, verso, page paysage tournée comme à l'impression) et ordre de toutes
  les feuilles. Modales défilantes quand l'écran est bas (1024×680).

### Validations

- [x] Tests : 116 (ordre des faces, chaque page une fois, composition :
  moitiés, marges, pli, pages pivotées et paysage, annotations et champs,
  document ouvert intact ; réglages du livret ; papier tourné refusé ; placement
  sur le papier ; routes et refus). Sur les vrais pilotes du poste, Canon
  comprise, sans impression papier : réglages acceptés et relus (A4 ordinaire,
  paysage, bord court, livret et agrafage désactivés, 1 page par feuille,
  2 copies) ; papier annoncé 297 × 210 mm. Livret réel imprimé par
  « Microsoft Print to PDF » : 6 pages → 4 faces A4 paysage, chaque page
  reconnue à sa couleur, à sa place et droite ; versos retournés sur demande.
- [x] Recette Edge : 31 parcours sur 31 (aperçu et plan, 1024×680, livret et
  page imprimés dans des fichiers ; captures relues).
- [x] `build.ps1` 1.3.2 : 116 tests, fumée de l'exécutable figé 20/20 (livret
  compris), installateur `DestriPDF-1.3.2-installation.exe`.
- [x] Installée sur le poste à la demande de Florent, pour essai sur la Canon
  (1.3.1 → 1.3.2, autorisation Windows acceptée) : 717 fichiers identiques au
  paquet (celui du test de fumée 20/20), `booklet.js` de la 1.3.0 retiré par
  `[InstallDelete]`, entrée « DestriPDF 1.3.2 » ; lancement sans droits :
  fenêtre en 0,45 s (0,83 s mesurée de l'extérieur), interface en 0,89 s,
  fermeture propre.
- [x] Essai de Florent sur la Canon : « elle imprime pas en recto verso » —
  deux pages par face, en paysage, mais une seule face par feuille. Word et
  Acrobat impriment pourtant en recto verso sur cette Canon depuis ce poste.
  Corrigé en 1.3.3.

## Version 1.3.3 — livret envoyé comme un document Word, 19 octobre 2026 (non publiée)

### Constats (sans impression papier : travail du pilote Canon capturé dans un fichier)

- [x] Pilote « Canon Office XPS Class Driver » (v4, port WSD, impression XPS
  directe) : Windows convertit le travail en XPS, le filtre Canon le transmet
  tel quel (aucun traitement du recto verso), la Canon applique le ticket.
- [x] Le XPS du livret 1.3.2 demandait bien le recto verso
  (`JobDuplexAllDocumentsContiguously = TwoSidedShortEdge`, privé Canon
  `Duplex HORIZONTAL`, paysage) : la Canon ne l'a pas appliqué. Les documents
  Word partent en A4 portrait, bord long (réglages par défaut de la Canon).

### Réalisé

- [x] Livret envoyé comme un document Word recto verso : A4 (ou A3) portrait,
  bord long ; seuls les réglages qui diffèrent sont changés. Sur la Canon,
  aucun : DEVMODE par défaut (copies mises à part) et ticket XPS identique à
  celui d'une impression normale (vérifié dans les fichiers produits).
- [x] Faces tournées d'un quart de tour vers la gauche sur la feuille portrait,
  versos d'un demi-tour de plus en bord long (`backs_half_turn`) ; bord court
  gardé seulement pour un pilote qui n'aurait que lui (versos sans demi-tour).
  « Retourner les versos » inverse le choix.
- [x] Aperçu et textes de la boîte Imprimer, README, plan.

### Validations

- [x] Tests : 120, dont une feuille simulée sur les vrais pixels : recto et
  verso imprimés selon la définition du retournement (bord long : autour des
  grands côtés du papier ; bord court : des petits), lus comme un lecteur
  (recto tourné pour lire la page de droite, feuille retournée autour du pli).
  Livret juste pour 4 et 8 pages en A4 portrait bord long, juste en paysage bord
  court, et faux (versos tête en bas, pages inversées) si le demi-tour manque :
  la simulation distingue bien le juste du faux.
- [x] Réglages relus sur chaque pilote du poste, Canon comprise : A4 portrait,
  bord long, livret et agrafage désactivés, papier annoncé 210 × 297 mm.
- [x] Recette Edge : 31 parcours sur 31 (livret imprimé dans un fichier : faces
  tournées sur A4 portrait, capture relue).
- [x] `build.ps1` 1.3.3 : 120 tests, fumée de l'exécutable figé 20/20,
  installateur `DestriPDF-1.3.3-installation.exe`.
- [x] Installée sur le poste à la demande de Florent, pour essai sur la Canon
  (1.3.2 → 1.3.3, autorisation Windows acceptée) : 717 fichiers identiques au
  paquet, exécutable identique à celui du test de fumée 20/20, entrée
  « DestriPDF 1.3.3 » ; lancement sans droits : fenêtre en 0,56 s, interface
  en 0,81 s. Florent a rouvert son document dans la 1.3.3 depuis l'Explorateur.
- [x] Retour de Florent après l'installation de la 1.3.3 : « ok commit push ».
  Commit `1016d15` poussé sur `main` (20 octobre).
- [x] Release `v1.3.3` publiée à la demande de Florent par
  `scripts\release.ps1 -Publish` :
  https://github.com/florentdestribois/DestriPDF/releases/tag/v1.3.3, étiquette
  sur `1016d15` ; `build.ps1` : 120 tests, fumée de l'exécutable figé 20/20,
  installateur `DestriPDF-1.3.3-installation.exe` (36 174 358 octets) ; SHA-256
  `3912658C4DF9936BBA8542107D7D037873734E5F3E6796B82E3C7ADC41CF2F22` identique
  sur GitHub. Le poste garde l'installation 1.3.3 du 19 octobre (même code,
  construite avant ce suivi).

### Reste à faire / limites

- [ ] Imprimante sans recto verso automatique : faces imprimées à la suite, pas
  d'assistant de recto verso manuel.
- [ ] Imprimante réseau : le pilote interroge l'imprimante (capacités) à
  l'ouverture de la boîte Imprimer, par le spouleur de Windows.
- [ ] Cause du blocage au lancement par DestriCenter toujours inconnue : au
  prochain cas, lire `logs\blocage-….txt` (piles) et le journal de démarrage.
- [ ] Signature réelle avec la clé CertEurope puis contrôle dans Acrobat :
  « Signature valide » et « compatible LTV » attendus (seul essai impossible sans
  la clé et son PIN).
- [ ] Format PKCS#7 détaché d'Acrobat non proposé : DestriPDF signe en PAdES
  (format européen, « équivalent CAdES » dans Acrobat).
- [ ] Si Florent le souhaite, DestriPDF comme lecteur PDF par défaut : Windows
  réserve ce choix à l'utilisateur (clic droit › Ouvrir avec › Choisir une
  autre application › DestriPDF › Toujours).
- [ ] Clés accessibles uniquement par PKCS#11 (hors magasin Windows) : non gérées.
- [ ] Recomposition d'un paragraphe entier : modification ligne par ligne.
- [ ] OCR des documents numérisés : hors périmètre.
