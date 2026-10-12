# DestriPDF

Lecture, modification, annotation et signature électronique de documents PDF,
pour les postes Windows de Menuiserie Destribois. Pensé comme un remplaçant
simple et rapide d'Adobe Acrobat pour l'usage courant : corriger un texte,
commenter un plan, remplir un formulaire et surtout signer avec la clé de
signature (certificat eIDAS, marchés publics).

- Ouverture d'un PDF en 1 seconde environ, première page comprise.
- Signature PAdES avec le certificat de la clé USB : le code PIN est demandé par
  le logiciel de la clé, la clé privée ne quitte jamais la clé. Présentation et
  validation à long terme (LTV) identiques à celles d'Acrobat.
- Accès Internet au seul moment de signer : état de révocation du certificat
  auprès de l'autorité de certification (désactivable) et horodatage facultatif.

## Installation

1. Lancer `installer_output\DestriPDF-1.2.0-installation.exe` (ou l'installateur
   joint à la release GitHub de la version) et accepter la
   demande d'autorisation de Windows. DestriPDF s'installe pour tous les
   utilisateurs du poste dans `C:\Program Files\DestriPDF` (« Programmes » dans
   l'Explorateur). En ligne de commande, `/CURRENTUSER` installe pour le seul
   utilisateur courant, sans droits, dans `%LOCALAPPDATA%\Programs\DestriPDF`.
2. Option « Proposer DestriPDF pour ouvrir les fichiers PDF » : DestriPDF apparaît
   dans « Ouvrir avec » et dans Paramètres › Applications › Applications par
   défaut. Windows laisse à l'utilisateur le choix de l'application par défaut :
   clic droit sur un PDF › Ouvrir avec › Choisir une autre application ›
   DestriPDF › Toujours.
3. Le moteur Microsoft Edge WebView2 est présent sur Windows 11 ; l'installateur
   prévient s'il manque.

La désinstallation (Paramètres › Applications, droits d'administrateur) retire
le programme et ses entrées « Ouvrir avec ». Les réglages et l'image de
signature de chaque utilisateur restent dans `%APPDATA%\DestriPDF`.

## Utilisation

### Ouvrir, naviguer, rechercher

- Ouvrir : bouton « Ouvrir » (Ctrl+O), glisser-déposer, double-clic dans
  l'Explorateur, ou un document récent de l'écran d'accueil.
- Vignettes à gauche (bouton en début de barre) : clic pour aller à la page,
  glisser pour déplacer une page, clic droit pour pivoter, insérer ou supprimer.
  Onglet « Signets » pour la table des matières du document.
- Pastille en bas : page précédente et suivante, numéro de page, zoom (clic sur
  le pourcentage : ajuster à la largeur, page entière, 50 à 200 %). Ctrl+molette
  zoome sous le pointeur.
- Rechercher : Ctrl+F, Entrée pour le résultat suivant, Maj+Entrée pour le
  précédent.

### Modifier le texte

Outil « Modifier » (touche E) : cliquer sur une ligne. Un éditeur se pose
exactement sur la ligne, avec la police, la taille, la couleur et l'alignement
d'origine ; une colonne de montants alignés à droite reste alignée à droite.

- Entrée valide, Échap annule, Tab valide puis passe à la ligne suivante.
- La barre au-dessus de la ligne change la police, la taille, le gras,
  l'italique, la couleur, l'alignement, ou supprime la ligne.
- Un point d'attention signale une police d'origine absente du poste et la
  police de remplacement employée.
- Une page numérisée (image) n'a pas de texte modifiable : « Effacer une zone »
  puis « Ajouter du texte ».

Seul le texte de la ligne est retiré : images, traits de tableau et lignes
voisines restent intacts. Le document est vérifié après chaque modification.

### Annoter

| Outil | Touche | Usage |
|---|---|---|
| Sélection | V | Copier du texte ; cliquer une annotation pour la déplacer, la modifier ou la supprimer (Suppr) |
| Texte | T | Cliquer puis écrire ; Ctrl+Entrée ou clic ailleurs pour valider |
| Note | N | Cliquer pour poser une note avec son commentaire |
| Surligner | H | Sélectionner le texte : surligner, souligner ou barrer |
| Dessin | D | Main levée, couleur et épaisseur au choix |
| Formes | R | Rectangle, ellipse ou flèche |
| Effacer | X | Tracer un cadre : texte, images et traits recouverts sont supprimés |

Les annotations sont standard : Acrobat, Edge et les autres lecteurs les
affichent. Le panneau « Commentaires » (menu ⋯) les liste toutes.

Les champs d'un formulaire PDF se remplissent directement en mode Sélection.

### Exporter en JPG

Menu ⋯ › Exporter en JPG : la page affichée ou toutes les pages, en 150 ppp
(écran, courriel) ou 300 ppp (impression). Une image par page, numérotée d'après
le nom choisi (« devis - page 1.jpg », « devis - page 2.jpg »…). Les images
reprennent la page telle qu'affichée : annotations, champs remplis et
signatures visibles compris. Une très grande page (plan A0) est exportée à une
résolution réduite, signalée à la fin de l'export.

Ctrl+Z annule, Ctrl+Y rétablit ; chaque bouton indique l'action concernée.

### Signer avec la clé

1. Brancher la clé USB de signature (son logiciel doit être installé).
2. « Signer avec ma clé » : le panneau liste les certificats du magasin Windows
   qui ont une clé privée. Les certificats qualifiés eIDAS et les clés
   matérielles sont signalés ; le plus adapté est présélectionné.
3. Signature visible : tracer le cadre sur la page (ou cliquer pour le poser).
   L'image de votre signature manuscrite peut y figurer (« Dessiner » ou
   « Importer », conservée sur ce poste).
4. Motif et lieu sont facultatifs et mémorisés.
5. « Signer et enregistrer » : choisir le fichier signé (par défaut
   « nom - signé.pdf », l'original reste intact), puis saisir le code PIN dans la
   fenêtre du logiciel de la clé.

Le cadre visible reprend la mise en page d'Acrobat : à gauche le nom du
signataire en grand, coupé au besoin dans le mot comme le fait Acrobat
(« Florent / DESTRIB / OIS »), ou l'image de la signature manuscrite ; à droite
« Signature numérique de … », le motif et le lieu s'ils sont renseignés, puis la
date au format d'Acrobat (« Date : 2026.10.12 13:14:05 +02'00' »). Chaque moitié
est remplie au plus grand, en noir, en Segoe UI (la police de Windows la plus
proche de Myriad Pro, police d'Acrobat). Le filigrane central est l'emblème de
DestriPDF : le logo d'Acrobat est une marque d'Adobe. Le cadre n'est que la
représentation de la signature : la preuve est la signature électronique
elle-même, contrôlée par Acrobat et par DestriPDF à l'ouverture.

La signature produite est une signature PAdES (ETSI.CAdES.detached, SHA-256)
avec la chaîne de certification. Comme Acrobat, DestriPDF demande avant le code
PIN l'état de révocation du certificat à l'autorité de certification (OCSP ou
liste de révocation publiée dans le certificat), puis l'intègre au document : la
signature reste vérifiable après l'expiration du certificat et Acrobat la dit
« compatible LTV ». Un certificat révoqué est refusé avant toute saisie du PIN.
Sans connexion, la signature est faite sans cet état et un message le signale.
Réglage : menu ⋯ › Réglages › Validation à long terme. Un document déjà signé
peut être contresigné : les signatures précédentes restent valides, et la
vérification les dit valides comme Acrobat. Une annotation, une valeur de champ
(un montant) ou une métadonnée (titre, auteur) modifiée après une signature la
fait signaler « à vérifier », avec le champ en cause. Format produit : PAdES
(ETSI.CAdES.detached), le format européen qu'Acrobat nomme « équivalent
CAdES » ; Acrobat peut aussi produire l'ancien format « PKCS#7 détaché ».

À l'ouverture d'un document signé, un bandeau donne le résultat de la
vérification : intégrité, couverture du document, modifications après signature
et confiance de la chaîne de certification selon Windows. « Détails » ouvre le
panneau « Signatures », qui indique aussi si l'état de révocation est intégré
(LTV, dans le document ou, pour Acrobat, dans la signature elle-même) et si
l'heure est attestée par une autorité d'horodatage reconnue par Windows.

« Apposer ma signature manuscrite » (menu ⋯) pose seulement l'image de la
signature : elle n'a pas valeur de signature électronique.

### Réglages

Menu ⋯ › Réglages : auteur des annotations, thème (Windows, clair, sombre),
validation à long terme des signatures (état de révocation intégré, actif par
défaut), adresse d'un service d'horodatage (TSA) facultatif, image de signature.

## Dépannage

- « Aucun certificat de signature trouvé » : brancher la clé, attendre quelques
  secondes, « Actualiser ». Vérifier que le logiciel de la clé est installé et
  que le certificat apparaît dans `certmgr.msc` › Personnel › Certificats.
- « Code PIN incorrect » ou « Code PIN bloqué » : messages de la clé elle-même ;
  le déblocage se fait avec le logiciel de l'autorité de certification.
- « État de révocation du certificat non intégré » : l'autorité de certification
  n'a pas répondu (connexion Internet, pare-feu). La signature est valide ;
  signer à nouveau une fois connecté pour une signature « compatible LTV ».
- « Votre certificat est révoqué » : l'autorité l'a déclaré invalide ; aucune
  signature n'est produite. Contacter l'autorité de certification.
- « Ce fichier est ouvert ou verrouillé par un autre logiciel » : fermer le
  fichier dans l'autre logiciel ou enregistrer sous un autre nom.
- Journal : `%LOCALAPPDATA%\DestriPDF\logs\destripdf.log`.

## Développement

Dépôt privé : https://github.com/florentdestribois/DestriPDF

```powershell
# Environnement (Python 3.12)
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Lancer l'application
.venv\Scripts\python.exe -m destripdf [fichier.pdf]

# Tests
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider

# Recette dans Edge sans fenêtre (scénarios utilisateur, captures)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\recette.ps1

# Exécutable, test de fumée de l'exécutable et installateur
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

### Publier une version

Chaque release porte son installateur. Après avoir aligné la version
(`destripdf/__init__.py`, `installer.iss`, `build_version.txt`) et commité :

```powershell
# Contrôles et construction complète, rien n'est publié
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1
# Puis étiquette vX.Y.Z, push et release GitHub avec l'installateur joint
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1 -Publish
```

Le script refuse de publier si les versions diffèrent, si l'arbre n'est pas
propre, hors de `main`, si l'étiquette existe ou si `build.ps1` échoue ; la
release indique l'empreinte SHA-256 de l'installateur.

### Architecture

- `destripdf/app.py` : lancement ; le serveur et la lecture du PDF partent avant
  la fenêtre pywebview (Edge WebView2).
- `destripdf/server.py` : serveur HTTP local (127.0.0.1, port aléatoire, jeton
  secret dans le chemin, contrôle Host/Origin/en-tête applicatif, CSP stricte).
- `destripdf/document.py` : document ouvert depuis la mémoire (le fichier n'est
  jamais verrouillé), rendu, texte, modification de ligne, annotations,
  formulaires, pages, annulation par instantanés, enregistrement complet ou
  incrémental (document signé).
- `destripdf/fonts.py` : choix de la police (même nom, équivalent Windows,
  police de base) et réduction aux glyphes utiles (fontTools).
- `destripdf/signing/wincert.py` : magasin de certificats Windows, chaîne de
  certification et signature par CryptoAPI/CNG (ctypes).
- `destripdf/signing/pades.py` : signature PAdES (pyHanko), apparence visible
  à la manière d'Acrobat, état de révocation intégré (LTV), vérification.
- `destripdf/static/` : interface (modules JavaScript sans framework, charte
  DestriMix, polices locales).

Mode recette : `--serve --port N` sert l'interface à un navigateur ;
`DESTRIPDF_TOKEN`, `DESTRIPDF_SETTINGS_DIR` et `DESTRIPDF_TEST_PFX` (+
`DESTRIPDF_TEST_PFX_PASSWORD`) fixent le jeton, isolent les réglages et
remplacent le magasin Windows par un certificat de test.

## Licences

DestriPDF s'appuie sur PyMuPDF/MuPDF (AGPL-3.0 ou licence commerciale
d'Artifex), pyHanko (MIT), pywebview (BSD), fontTools (MIT), cryptography
(Apache-2.0/BSD) et les polices Roboto (Apache-2.0), Barlow Condensed et Abhaya
Libre (OFL). L'usage interne à l'entreprise ne pose pas de difficulté ; une
diffusion hors de l'entreprise imposerait de publier le code source (AGPL) ou
d'acquérir une licence commerciale de MuPDF.
