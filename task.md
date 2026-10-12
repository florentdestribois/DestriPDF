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
- [ ] Installation de la 1.2.0 dans Program Files : autorisation Windows à
  donner par Florent (la tentative 1.1.1 a été annulée ; poste encore en 1.1.0).
- [ ] Commit et première release `v1.2.0` par `scripts\release.ps1 -Publish` :
  sur demande explicite de Florent.

### Reste à faire / limites

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
