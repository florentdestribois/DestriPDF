# Plan — DestriPDF

## Objectif

Demande de Florent du 12 octobre 2026 : « un équivalent d'Adobe Acrobat » pour
modifier facilement du texte, poser des notes et surtout signer avec sa clé
numérique (certificat eIDAS sur clé USB, exigé pour les marchés publics). Le
logiciel doit être rapide, se charger vite, rester simple et logique.

## Périmètre

Inclus :

- ouvrir un PDF (dialogue, glisser-déposer, ligne de commande, « Ouvrir avec »,
  fichiers récents), PDF protégé par mot de passe ;
- afficher vite : rendu à la demande des pages visibles, vignettes, zoom,
  ajustement largeur/page, recherche, sélection et copie du texte ;
- modifier le texte existant ligne par ligne (même position, police
  approchante, taille, couleur, gras, italique) ;
- ajouter du texte, des notes, surligner/souligner/barrer, dessiner à main
  levée, rectangle, ellipse, flèche, effacer une zone (caviardage réel) ;
- signature électronique PAdES avec le certificat de la clé (magasin Windows,
  code PIN saisi dans la fenêtre du fournisseur de la clé), visible ou
  invisible, image manuscrite facultative ; vérification des signatures à
  l'ouverture ;
- signature présentée comme dans Acrobat (nom à gauche, « Signature numérique
  de … » et date au format d'Acrobat à droite) et, comme Acrobat, état de
  révocation du certificat intégré au document (validation à long terme,
  « compatible LTV ») ; demande de Florent du 12 octobre après-midi ;
- signature manuscrite simple (image), signalée comme sans valeur électronique ;
- pages : pivoter, supprimer, déplacer, insérer depuis un autre PDF ;
- annuler/rétablir, enregistrer, enregistrer sous, imprimer ;
- exporter en JPG la page affichée ou toutes les pages (150 ou 300 ppp), telles
  qu'affichées (annotations, champs, signatures visibles) ;
- installateur Windows pour tous les utilisateurs du poste (Program Files,
  droits d'administrateur ; `/CURRENTUSER` pour les essais), entrée « Ouvrir
  avec ».

Exclus de cette version : OCR, formulaires XFA, édition de paragraphes avec
recomposition, horodatage par défaut (réglage facultatif), PAdES-LTA
(horodatage de document), lecteurs PKCS#11 hors magasin Windows.

## Architecture

- Python 3.12, serveur HTTP de la bibliothèque standard sur `127.0.0.1`,
  port aléatoire, jeton secret dans le chemin, contrôle `Host`/`Origin`.
- Fenêtre pywebview (Edge WebView2) ; mode navigateur `--serve` pour la
  recette. Démarrage surveillé (`startup.py`) : PATH hérité d'une autre
  application PyInstaller nettoyé ; sans fenêtre après 20 s, piles des fils
  d'exécution, relance unique dans un environnement nettoyé avec un dossier
  WebView2 de secours, sinon message et fin du processus.
- Moteur PDF : PyMuPDF (MuPDF). Document ouvert depuis la mémoire (le fichier
  d'origine n'est jamais verrouillé). Un verrou global sérialise MuPDF.
- Annuler/rétablir : instantanés complets du document après chaque opération,
  sous un budget mémoire (le journal MuPDF s'est montré incompatible avec
  plusieurs fonctions de PyMuPDF).
- Modification d'une ligne : l'unité modifiable est le segment (ligne MuPDF
  coupée aux écarts de plus de 0,9 corps : une cellule de tableau se modifie
  seule, l'alignement à droite d'une colonne de montants est détecté). Texte
  extrait du seul contenu de page (`fz_run_page_contents`), jamais des
  annotations ni des champs. Caviardage d'une bande centrée sur la ligne
  (texte seul, ni images ni tracés), contrôle que les segments voisins sont
  intacts (repli sur une bande plus fine), puis réécriture avec une police
  réduite aux glyphes utiles (fontTools) : police Windows du même nom, puis
  police de remplacement selon les attributs. Pages pivotées : écriture à plat
  puis rotation autour de l'origine.
- Enregistrement : réécriture complète et propre d'un document non signé ;
  document déjà signé : une seule mise à jour incrémentale contenant les seuls
  objets modifiés, pour préserver les signatures existantes.
- Signature : pyHanko (PAdES B-B, `ETSI.CAdES.detached`, SHA-256) avec un
  signataire qui délègue la signature brute à Windows (CryptoAPI/CNG par
  ctypes), chaîne de certification construite par Windows. Apparence visible
  dessinée par PyMuPDF (présentation d'Acrobat) puis importée par pyHanko.
- Validation à long terme : si le certificat publie un état de révocation,
  pyHanko le demande à l'autorité (OCSP/CRL, aiohttp) avant le PIN — un
  certificat révoqué est refusé — puis l'écrit dans le DSS par une seconde mise
  à jour. Autorité injoignable : signature sans LTV, un seul PIN. La
  vérification juge « LTV » une signature dont la chaîne se vérifie hors ligne
  avec le seul DSS, à la date de signature.
- Annotations sur page pivotée : coordonnées échangées dans l'espace affiché ;
  quadrilatères de surlignage transformés coin par coin ; image de signature
  pré-tournée ; texte libre composé avec `rotate`.
- Interface : SPA vanilla (modules ES), charte DestriMix (thème `atelier`,
  `graphite` en sombre), polices locales, aucune ressource externe. Barre
  d'outils à libellés courts, pastille de navigation et de zoom en bas du
  document, barre d'options propre à l'outil actif.
- Recette : Edge sans fenêtre piloté par le protocole DevTools
  (`scripts\cdp.py`, `scripts\recette.ps1`), certificat de test en mémoire.
- Paquet : PyInstaller en mode dossier (démarrage rapide) et Inno Setup.
- Release : `scripts\release.ps1` ; chaque release GitHub `vX.Y.Z` porte son
  installateur, construit et vérifié par `build.ps1` (demande de Florent).

## Phases

1. Socle : document, rendu, texte, historique, serveur, sécurité HTTP.
2. Signature : magasin Windows, signataire pyHanko, apparence, vérification.
3. Interface : visionneuse, outils, panneaux, raccourcis, dialogues.
4. Recette : tests unitaires et HTTP, parcours réels dans un navigateur,
   mesures de démarrage.
5. Paquet : exécutable, installateur, « Ouvrir avec ».

## Critères d'acceptation

- Un PDF de 60 pages s'affiche en moins de 2 s après le lancement ; la page
  visible apparaît avant le rendu des autres.
- Une ligne modifiée remplace exactement l'ancienne ; les lignes voisines, les
  images et les tracés restent intacts (test automatisé).
- Notes, surlignage, dessin et texte ajouté s'enregistrent comme annotations
  standard lisibles par Acrobat et Edge.
- Une signature produite avec un certificat dont la clé est gérée par Windows
  (CNG) est valide pour pyHanko (intégrité, couverture complète) ; une
  annulation de saisie du PIN produit un message clair sans fichier partiel.
- Signer un document déjà signé conserve la première signature valide.
- Le cadre visible reproduit la mise en page d'Acrobat : nom à gauche rempli au
  plus grand (coupé dans le mot si besoin), « Signature numérique de … » et
  « Date : AAAA.MM.JJ HH:MM:SS +HH'MM' » à droite remplis au plus grand, noir,
  Segoe UI ; comparé au cadre d'un PDF signé par Acrobat (mêmes retours à la
  ligne). Ni logo ni police d'Adobe (marque et licence d'Adobe).
- Comme Acrobat, une contresignature laisse la signature précédente « valide » ;
  une annotation, une valeur de champ ou une métadonnée modifiée ensuite la rend
  « à vérifier » en nommant le champ (tests). Une signature d'Acrobat (PKCS#7,
  état archivé dans la signature) est reconnue « LTV » comme dans Acrobat.
- Export JPG : une image par page à 150 ou 300 ppp, résolution inscrite dans le
  fichier, très grande page réduite et signalée (tests, recette).
- Aucune release GitHub sans son installateur vérifié (`scripts\release.ps1`).
- Jamais d'instance sans fenêtre : fenêtre absente après 20 s → relance unique,
  puis message et fin (tests, recette `surveillance_demarrage.py` sur
  l'exécutable figé) ; démarrage journalisé avec le programme lanceur.
- Avec une autorité qui publie ses listes de révocation, le document signé
  contient leur état et la chaîne se vérifie hors ligne ; autorité injoignable :
  signature sans LTV après un seul PIN ; certificat révoqué : refus sans PIN
  (tests, et test de fumée de l'exécutable figé avec autorité simulée).
- Annuler/rétablir couvre toutes les opérations de modification.
- Aucune requête externe hors du moment de signer (état de révocation auprès
  de l'autorité du certificat, horodatage réglé) ; API inaccessible sans jeton
  ou avec un `Host` étranger.
