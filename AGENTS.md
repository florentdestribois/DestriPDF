# Consignes agents — DestriPDF

Application Windows de lecture, modification, annotation et signature de PDF.
Interface unique : SPA vanilla servie par un serveur HTTP local et affichée dans
une fenêtre pywebview (Edge WebView2). Voir `README.md` pour l'architecture.

## Pilotage

- `plan.md` (objectif, périmètre, architecture, critères) et `task.md`
  (avancement, validations, suite) font autorité. Les lire avant toute
  modification de code ; les mettre à jour après, avant d'annoncer la fin.
- Dépôt : `https://github.com/florentdestribois/DestriPDF` (privé, branche
  `main`). Ne créer ni branche, ni commit, ni push, ni tag, ni publication sans
  demande explicite.
- Chaque release porte son installateur (demande de Florent) : publier
  uniquement par `scripts\release.ps1 -Publish`, qui construit et vérifie
  l'installateur (`build.ps1`) puis le joint à la release GitHub `vX.Y.Z`.

## Règles techniques

- PyMuPDF n'est pas sûr entre fils d'exécution : tout appel MuPDF passe sous
  `document.FITZ_LOCK`, y compris dans `signing/pades.py`.
- Le document s'ouvre depuis la mémoire : ne jamais verrouiller le fichier de
  l'utilisateur. Écriture toujours atomique (`document.atomic_write`).
- Un document déjà signé s'enregistre en une seule mise à jour incrémentale
  (`PdfSession._incremental_bytes`) : ne jamais le réécrire entièrement.
- Le journal MuPDF (`journal_*`) est proscrit : l'annulation repose sur les
  instantanés de `History`.
- Texte modifiable : `_contents_textpage` (contenu de page seul, sans
  annotations ni champs).
- La clé privée ne quitte jamais son fournisseur : signature par
  `wincert.CertStore.sign_digest`, PIN saisi dans la fenêtre du fournisseur.
- Serveur : 127.0.0.1, jeton dans le chemin, contrôle `Host`, en-tête
  `X-DestriPDF` et `Origin` pour toute mutation, CSP stricte (aucun style ni
  script en ligne, aucune ressource externe). Toute route nouvelle reçoit un
  test, y compris de refus.
- Interface : charte DestriMix (support `atelier`, `graphite` en sombre), jetons
  CSS de `static/app.css`, modales maison (`ui.modal`), jamais
  `window.alert/confirm`. Échapper toute donnée issue du PDF (`textContent`,
  jamais `innerHTML`).
- Accès réseau limité au moment de signer : état de révocation (OCSP/CRL) aux
  adresses publiées dans la chaîne du certificat (réglage `sign_ltv`, actif par
  défaut, comme Acrobat) et horodatage (TSA) réglé par l'utilisateur. Tests :
  certificats, autorité de révocation et autorité d'horodatage simulés en local.
- Une signature ne demande jamais deux fois le PIN : un échec de l'état de
  révocation avant la signature retombe sur une signature sans LTV.
- Ne jamais lire, afficher ni exporter les certificats ou clés de l'utilisateur
  pendant le développement : la recette remplace le magasin Windows par un PFX
  de test (`DESTRIPDF_TEST_PFX`).

## Validation

- `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`
- Interface : `scripts\recette.ps1` (Edge sans fenêtre, 1024×680 à 1920×1080,
  captures dans `recette_output\`), puis lecture des captures.
- Paquet : `build.ps1` (tests, exécutable, test de fumée de l'exécutable figé,
  installateur).
- Rapporter commandes, résultats, échecs et limites.
