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

### Installation et dépôt — 12 octobre

- [x] Installé sur le poste de Florent par
  `installer_output\DestriPDF-1.0.0-installation.exe` (par utilisateur,
  `%LOCALAPPDATA%\Programs\DestriPDF`) : menu Démarrer (dossier DestriPDF),
  Bureau, « Ouvrir avec », déclaration aux applications par défaut ; version
  1.0.0 lancée en 1,2 s. Bundle postérieur à la dernière modification des
  sources, fichiers d'interface identiques au dépôt. Remplacée l'après-midi par
  l'installation dans Program Files (voir version 1.1).
- [x] Dépôt privé https://github.com/florentdestribois/DestriPDF, branche
  `main` : 55 fichiers, sans environnement, sortie de build, certificat ni clé
  (certificats de test générés par `tests/pki.py`). Git du poste hors PATH :
  push par `gh auth git-credential` en option de commande, sans configuration
  globale.

## Version 1.1 — 12 octobre 2026, après-midi

Demandes de Florent : « il faut l'installer dans le dossier C:\Programmes » ;
« la signature numérique ne ressemble pas à la signature faite sur Acrobat.
Cette signature doit avoir une vraie preuve de signature ».

### Constat sur la première signature réelle (13 h 14, clé CertEurope)

- [x] Fichier signé relu en lecture seule avec la vérification de DestriPDF :
  signature PAdES valide, intacte, couvrant tout le fichier, certificat qualifié
  eIDAS « CertEurope eID User », chaîne approuvée par Windows. Écarts avec
  Acrobat : présentation du cadre, et état de révocation absent, alors
  qu'Acrobat l'intègre par défaut (« compatible LTV ») et que CertEurope le
  publie (OCSP et listes de révocation).

### Réalisé

- [x] Installateur administrateur : `C:\Program Files\DestriPDF` (`{autopf}`),
  associations sous HKLM (`HKA`), `/CURRENTUSER` gardé pour les essais. Copie par
  utilisateur désinstallée, réglages conservés.
- [x] Cadre visible présenté comme dans Acrobat : nom en grand à gauche (ou image
  manuscrite), « Signature numérique de … », motif, lieu et « Date : 2026.10.12
  13:14:05 +02'00' » à droite ; un petit cadre réduit le texte sans le tronquer.
- [x] Validation à long terme : état de révocation demandé à l'autorité avant le
  PIN (certificat révoqué refusé sans PIN), intégré au DSS par une seconde mise à
  jour ; autorité injoignable : signature sans LTV après un seul PIN, message
  explicite ; horloge du poste en retard sur l'autorité tolérée
  (`retroactive_revinfo`). Réglage « Validation à long terme » (actif par
  défaut), panneau Signatures : lignes « Révocation » et « Heure ».
- [x] Version 1.1.0 ; README, plan et consignes (accès réseau) à jour.

### Validations

- [x] Tests : 64 (dont apparence Acrobat, cadre minuscule, LTV intégrée puis
  vérifiée hors ligne, horloge de l'autorité en avance, autorité injoignable,
  certificat révoqué, LTV désactivée).
- [x] Test de fumée 16/16 sur les sources et sur l'exécutable figé, avec une
  autorité de révocation simulée (aiohttp bien embarqué).
- [x] Recette Edge sur l'exécutable 1.1.0 : 27 parcours sur 27 ; captures
  relues (panneau Signatures, Réglages, 1024×680).
- [x] Installé dans `C:\Program Files\DestriPDF` (mise à jour 1.0.0 → 1.1.0,
  autorisation Windows acceptée par Florent) : 717 fichiers identiques au
  paquet, « Ouvrir avec » et raccourcis en place ; lancé sans droits
  d'administrateur : fenêtre en 0,5 s, première page en 0,9 s, aucun fichier
  écrit dans Program Files.
- [x] Relecture indépendante du changement (agent) : terminée après le commit de
  la 1.1.0 ; constats traités en 1.2.0 (ci-dessous).

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

## Papier A4/A3 et recto verso des pages normales, 27 octobre 2026 (non publié)

Demande de Florent : « Pour l'impression des documents, ajoute le choix du
format A4 ou A3 ainsi que le recto verso ».

### Réalisé

- [x] `printing.py` : `page_settings` (papier ordinaire, jamais un « A4R », et
  recto verso `psk:OneSided`/`TwoSidedLongEdge`/`TwoSidedShortEdge` sur la
  fonction déclarée par le pilote), `duplex_modes`, `current_choice` ; réglage
  commun `_tuned` (changés s'ils diffèrent, copies, relus ; refus → message)
  partagé avec le livret. Sans choix, comportement d'avant (préférences seules).
- [x] Capacités : `duplex_modes` et `current` (papier et recto verso en cours,
  préférences comprises) ; `api/print` accepte `sheet` et `duplex` (refus
  `bad_sheet`, `bad_duplex`, y compris valeurs non textuelles).
- [x] Boîte Imprimer : ligne Papier (A4, A3) et Recto verso (recto seul, bord
  long « comme un livre », bord court « comme un bloc-notes »), ouverte sur
  les réglages du pilote et relue après « Préférences de l'imprimante » ; en
  livret, la colonne Recto verso cède la place à la Reliure et le papier
  s'affiche « A4 → livret A5 ». Imprimante sans recto verso : choix grisé et
  signalé ; capacités illisibles : impression « selon l'imprimante ».
  Message de fin : « 1 page envoyée … en A3 recto seul ».

### Validations

- [x] Tests : 124 (pytest), dont chaque format × chaque recto verso proposé
  accepté et relu sur chaque pilote du poste (Adobe PDF, iR-ADV C3520,
  Microsoft Print to PDF, OneNote, PDFCreator), sans rien imprimer, et une page
  A4 imprimée en A3 par « Microsoft Print to PDF » (feuille 842 × 1191 pt,
  annotation en haut à gauche).
- [x] Recette Edge : 33 parcours sur 33 ; boîte ouverte sur la Canon en A4 bord
  long (ses réglages par défaut), sans débordement en 1024×680 ; impression A3
  dans un fichier relue. Captures `recette_output\20261027-091647\r3-07f-*`,
  `r3-07g-imprime-a3.png`.
- [x] Version 1.4.0 (code, informations de l'exécutable, installateur).
- [x] Premier `build.ps1` 1.4.0 en échec au test de fumée (16/20 : signature,
  LTV, vérification). Cause : le runtime Python du poste (Codex, mis à jour le
  25 octobre) a un `ssl.py` qui charge `codex-rejected-cas.pem`, voisin de
  `ssl.py`, à chaque contexte SSL ; absent de l'exécutable figé, l'import
  d'aiohttp échouait (`FileNotFoundError`). Reproduit sur un exécutable minimal.
  Correction : `DestriPDF.spec` joint ce fichier (dossier `_internal`) quand le
  runtime en a un. Toute construction depuis le 25 octobre aurait eu ce défaut.
- [x] `build.ps1` 1.4.0 : 124 tests, fumée de l'exécutable figé 20/20,
  installateur `DestriPDF-1.4.0-installation.exe` (36 192 565 octets) ; SHA-256
  `A742BD269FE86E6DE577DA4B95F3BB53277E043E82B47F591232A3106A8BE626`.
- [x] Installée sur le poste à la demande de Florent, pour essai sur la Canon
  (1.3.3 → 1.4.0, installation silencieuse, autorisation Windows acceptée) :
  718 fichiers identiques au paquet, entrée « DestriPDF » version 1.4.0 ;
  lancement sans droits : fenêtre en 0,50 s, interface en 1,12 s, fermeture
  propre.
- [ ] Essai papier sur la Canon (A3, recto verso bord long et bord court) :
  à faire par Florent. Ni commit ni release.

## Assemblage de PDF et compression, 4 novembre 2026 (non publié)

Demande de Florent : « Permettre d'assemblé des PDF ensemble par un simple
glisser/déposer ou bouton "ajouter des PDFs", l'utilisateur devra pouvoir
modifier l'odre des pages par un simple glisser (en pouvant selectionner
plusieur pages via clique+ctrl ou clic + maj+ctrl) » et « Fonction de
compression des pdfs ».

### Choix vérifiés par essais

- [x] `Document.select()` (`pdf_rearrange_pages2`) retire /AcroForm : un
  formulaire réordonné n'est plus un formulaire. Déplacement par `move_page`
  successifs (formulaire gardé), ordre final contrôlé par les xref.
- [x] `rewrite_images` : la méthode « moyenne » de MuPDF divise par puissances
  de 2 (300 ppp restent 300 ppp pour une cible de 150) ; bicubique : résolution
  exacte. Toutes les images sont recompressées, pas seulement celles au-delà du
  seuil : « seulement si plus petite » (défaut de MuPDF) garde un logo sans
  perte ; en « qualité élevée », les images sans perte le restent.
- [x] Dialogue Windows à sélection multiple : ordre rendu variable, fichiers
  rangés par nom comme dans l'Explorateur.

### Réalisé

- [x] `document.py` : `move_pages` (pages choisies avant une page, une étape
  d'annulation, aucune si elles sont déjà en place), `insert_pdfs` (plusieurs PDF
  à une position en une étape ; tout est refusé si une source est illisible,
  protégée ou vide ; sources signées signalées), `assemble_pdfs` (nouveau PDF,
  un signet par fichier, ses signets dessous), `compressed_bytes` et
  `COMPRESSION_LEVELS` (300, 150, 100 ppp ; JPEG 85, 75, 55), document neuf « à
  enregistrer » (`new_document`, dossier des sources proposé).
- [x] Serveur : `api/pages/move-many`, `api/pages/insert-upload` (PDF envoyés
  bout à bout : `sizes`, `names`), `api/pages/insert-files`,
  `api/assemble-upload`, `api/assemble-files`, `api/dialog/open-pdfs`,
  `api/dialog/save-pdf`, `api/compress/estimate`, `api/compress/save` (copie
  gardée jusqu'à la modification suivante ; refus : sans gain, document signé,
  niveau inconnu, sans chemin). Dialogue Windows dans une requête à part :
  l'indicateur d'avancement n'apparaît qu'une fois les fichiers choisis.
  `api/pages/insert-dialog` remplacé.
- [x] Interface : vue « Organiser » (bouton de la barre d'outils, menu ⋯, clic
  droit d'une vignette) : grille de toutes les pages en trois tailles ; clic,
  Ctrl+clic, Maj+clic, Ctrl+Maj+clic ; flèches, Maj+flèches, Ctrl+A, Suppr,
  Entrée, double-clic, Échap ; glisser des pages choisies (trait d'insertion,
  défilement au bord) ; PDF de l'Explorateur déposés à l'endroit du trait ;
  barre « Ajouter des PDF », pivoter, supprimer, nombre de pages choisies,
  « Terminé ». Vignettes à gauche : mêmes gestes (`pagesorter.js` partagé, une
  page choisie seule suit la page affichée). Accueil : « Assembler des PDF » et
  plusieurs PDF déposés assemblés. Voile du glisser annonçant l'effet du dépôt.
  Boîte « Compresser le PDF » : trois niveaux, taille estimée (les autres niveaux
  estimés aussitôt si le calcul est rapide), copie « nom - compressé.pdf »,
  notification avec « Ouvrir ».
- [x] Constatés en recette et corrigés : notifications posées sur les boutons
  d'une boîte ouverte (passées en haut tant qu'une boîte est ouverte) ;
  « Enregistrer » d'un document sans fichier envoyait une requête refusée avant
  « Enregistrer sous » ; menu ⋯ plus haut que la fenêtre (défilant).
- [x] Version 1.5.0 (code, informations de l'exécutable, installateur) ;
  exécutable et installateur non construits.

### Validations

- [x] Tests : 142 (18 nouveaux) : déplacement de plusieurs pages (4 cas, déjà
  en place, refus), formulaire, annotations, liens et signets qui suivent leurs
  pages, insertion groupée et refus complet, assemblage (ordre, signets,
  document à enregistrer, source signée), compression (niveaux, résolution,
  texte, document ouvert intact, mot de passe, document signé, modifications en
  cours), routes et refus (garde-fous, envoi incohérent, trop de fichiers,
  fichier disparu, dialogues, sans gain).
- [x] Recette Edge : 44 parcours sur 44 (18 + 15 + 11 nouveaux,
  `parcours_assemblage.py`) : vrai glisser-déposer HTML5 (geste de la souris
  intercepté par le protocole DevTools), PDF « de l'Explorateur » déposés entre
  deux pages et sur l'accueil, Ctrl/Maj/Ctrl+Maj+clic, clavier, assemblage puis
  Enregistrer sous, compression (photo 3,7 Mo → 119 Ko en équilibrée, 26 Ko en
  minimale), 1024×680, 1920×1080 et sombre sans débordement, console propre.
- [x] Test de fumée sur les sources : 26/26 (4 nouveaux : assemblage,
  déplacement, estimation et enregistrement de la compression).

### Relecture indépendante (agent, 4 novembre) — 9 constats, tous traités

- [x] Grave : la compression rendait brunes les images CMJN à profil ICC (MuPDF
  les recompresse en JPEG RVB en leur laissant l'espace CMJN ; exports
  d'InDesign, catalogues). Après recompression, l'espace de couleur suit le
  JPEG ; couleurs vérifiées aux trois niveaux, JPEG et sans perte (test).
- [x] `insert_pdf` ne reprend ni les calques (/OCProperties) ni les pièces
  jointes : un calque masqué d'un plan apparaissait. Calques reportés avec leur
  état par défaut (table des objets copiés de MuPDF), pièces jointes copiées
  (nom rendu unique) (test).
- [x] Une source signée rendait le document assemblé « signé » à signatures
  invalides (bandeau rouge, compression refusée, enregistrement incrémental) :
  ses champs sont figés (`bake`), la signature reste visible comme image (test).
- [x] Dialogue Windows : « Électricité » rangé après « plan 10 » → ordre de
  l'Explorateur (`StrCmpLogicalW`), comme pour les fichiers déposés (test).
- [x] Glisser de pages resté en mémoire (liste reconstruite pendant le geste) :
  le type du glisser décide, un PDF déposé ne peut plus être pris pour un
  déplacement de pages.
- [x] Demandes croisées : une modification des pages à la fois dans
  l'interface, réponse plus ancienne que l'état affiché ignorée ; verrou tenu
  pendant tout l'enregistrement de la copie compressée.
- [x] Page cliquée en fin de document remplacée dans la sélection par la page
  désignée par le défilement : une page choisie seule ne suit la page affichée
  qu'une fois sortie de l'écran.
- [x] Envoi de plus de 1 Go : message clair au lieu de « DestriPDF ne répond
  plus » ; même limite pour les fichiers choisis dans le dialogue.
- [x] Sélection gardée par position après Ctrl+Z ou Ctrl+Y : remise à zéro
  (recette).
- [x] Tests : 146 ; recette Edge : 44 parcours sur 44 après corrections.

### Publication et installation — 4 novembre, à la demande de Florent

Demande : « commit push et release puis instal le ».

- [x] Commit `adae98e` (avec le papier A4/A3 et le recto verso de la 1.4.0,
  jamais commités) poussé sur `main`. GitHub en incident (« Pull Requests, Git
  Operations and Issues ») : premier push refusé (« Internal Server Error »),
  accepté au second.
- [x] `scripts\release.ps1 -Publish` : `build.ps1` complet — 146 tests,
  exécutable, fumée de l'exécutable figé 26/26 (assemblage et compression
  compris), installateur `DestriPDF-1.5.0-installation.exe` (36 703 168
  octets), SHA-256 `6A0D92ED34F7385CF25C42A7C0474968B8A5AC23C2AB3E6065EB254B
  53539FAA`. Étiquette `v1.5.0` refusée au push (500), poussée au second essai.
- [x] Release `v1.5.0` publiée :
  https://github.com/florentdestribois/DestriPDF/releases/tag/v1.5.0, étiquette
  sur `adae98e`, installateur joint, SHA-256 identique sur GitHub. Création
  d'abord refusée par GitHub pendant l'incident (500, 404 à l'envoi de
  l'installateur, 502 ; aucun brouillon laissé), puis faite par un essai
  automatique avec les notes de `release.ps1` (dont l'arrêt au push de
  l'étiquette a laissé la fin de la publication à faire à la main).
- [x] Installée sur le poste (1.4.0 → 1.5.0, installation silencieuse,
  autorisation Windows acceptée) : 760 fichiers identiques au paquet, entrée
  « DestriPDF » 1.5.0. Les deux fenêtres ouvertes (sans modification) ont été
  fermées puis rouvertes sur leurs documents ; lancement sans droits : fenêtre
  en 0,48 s, interface en 1,0 s, première page en 1,2 s.

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
- [ ] Glisser-déposer depuis l'Explorateur : recetté dans Edge sans fenêtre
  (même moteur que WebView2), à confirmer dans la vraie fenêtre DestriPDF.
- [x] Assemblage : images acceptées (voir « Conversion et assemblage d'images »,
  9 novembre). Un PDF protégé par
  mot de passe est refusé (l'ouvrir seul) ; numérotation des pages
  personnalisée (/PageLabels) des sources non reprise.
- [ ] Compression : un très gros document numérisé occupe le moteur PDF pendant
  le calcul (affichage en pause) ; pas d'annulation en cours de calcul.

## Conversion et assemblage d'images, 9 novembre 2026 (version 1.6.0)

Demande de Florent : « Permet la conversion et assemblage de fichier image ».

### Choix vérifiés par essais

- `convert_to_pdf` de MuPDF garde le JPEG tel quel (DCT), applique l'orientation
  EXIF (photo prise en portrait) et le masque de transparence ; `insert_image` ne
  fait pas mieux. Une image sans résolution inscrite compte 96 ppp, une photo de
  téléphone 72 ppp (4032 px = 1,4 m) : d'où la règle de taille ci-dessous.
- Pillow non nécessaire : MuPDF lit JPG, PNG, TIFF (multipage), BMP, GIF,
  JPEG 2000, WebP. HEIC (iPhone) non lu.

### Réalisé

- [x] Moteur (`document.py`) : `image_kind` (signature du fichier, pas son nom),
  `image_to_pdf` (une page par image ; taille réelle si la page tient dans un A3,
  sinon réduite dans un A4 de même orientation, proportions gardées, jamais
  agrandie). `_open_sources` convertit les images : ajout et assemblage mêlent
  PDF et images, un signet par fichier, une étape d'annulation, une image
  illisible refuse tout l'ajout.
- [x] Ouverture (`server.py`) : une image ouverte (dialogue, glisser, récents,
  ligne de commande) devient « nom.pdf », sans fichier, à enregistrer ; dossier
  de l'image proposé ; l'image reste dans les récents (reconvertie à la
  réouverture). Dialogues Windows : filtre « PDF et images » ; fichier déposé
  dans la fenêtre accepté s'il est une image.
- [x] Interface : « Choisir un fichier », « Ajouter des fichiers », « Assembler des
  fichiers », « Insérer des fichiers avant/après » ; infobulles « PDF ou images » ;
  champs de fichier et voile du glisser étendus aux images ; messages en
  « fichiers ».
- [x] `IMAGE_EXTENSIONS` dans `destripdf/__init__.py` : la fenêtre ne charge pas
  MuPDF au démarrage pour connaître les extensions.

### Validations

- [x] Tests : 156 (10 nouveaux, `tests/test_images.py`) : signature des formats,
  taille (scan A4 à 300 ppp, photo 4032×3024 à 72 ppp, petite image), JPEG non
  recompressé et orientation EXIF, TIFF de deux pages, transparence rendue,
  images illisibles refusées, ajout mêlé en une étape, refus complet, assemblage
  avec signets, routes (ouvrir par chemin, déposer, ajouter, assembler, image
  jamais remplacée, refus d'une image illisible, garde-fous `X-DestriPDF` et
  jeton).
- [x] Recette Edge : 47 parcours sur 47 (3 nouveaux : photo déposée sur l'accueil
  ouverte redressée, photo et TIFF déposés entre deux pages dans « Organiser »,
  « Assembler des fichiers » avec PNG transparent, PDF et TIFF). Captures lues :
  accueil, `r5-01` à `r5-03`.
- [x] Test de fumée sur les sources : 28/28 (2 nouveaux : assemblage d'images,
  image ouverte en PDF). Exécutable figé et installateur non construits.

### Publication — 9 novembre, à la demande de Florent

Demande : « Oui, release 1.6.0 ».

- [x] Commit `0d9e452` ; `scriptselease.ps1 -Publish` : `build.ps1` complet —
  156 tests, exécutable, fumée de l'exécutable figé 28/28 (images comprises),
  installateur `DestriPDF-1.6.0-installation.exe` (36 700 038 octets), SHA-256
  `CC751B9C5CCA5FB707A8C0FF55888F34E4F85D248F899F1EB2CDE19B8CCFDF41`.
- [x] `main` et l'étiquette `v1.6.0` poussées ; release publiée :
  https://github.com/florentdestribois/DestriPDF/releases/tag/v1.6.0,
  installateur joint, taille et SHA-256 identiques sur GitHub.
- [ ] Non installée sur le poste (pas demandé).

### Reste à faire / limites

- [ ] HEIC (photos d'iPhone) non lu : exporter en JPG.
- [ ] Pas de PDF vers images autres que l'export JPG existant (PNG, TIFF).
- [ ] DestriPDF non proposé dans « Ouvrir avec » des images (installateur
  inchangé) ; les ouvrir par DestriPDF ou les glisser.
- [ ] Glisser-déposer d'images depuis l'Explorateur dans la vraie fenêtre : même
  chemin que les PDF, à confirmer hors Edge sans fenêtre.
- [x] Version 1.6.0 (code, informations de l'exécutable, installateur).
