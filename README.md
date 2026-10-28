# Simplex2Duplex

**Le recto-verso pour les scanners qui ne savent faire que du recto.**

Votre chargeur de documents (ADF) ne scanne qu'une face ? Scannez la pile, retournez-la, scannez-la à nouveau : Simplex2Duplex récupère les deux PDF dans un dossier, remet les pages dans l'ordre (1, 2, 3, 4…) et dépose un PDF recto-verso unique dans le dossier de votre choix.

Remplaçant maintenu de [`cranium/pdfcollate`](https://hub.docker.com/r/cranium/pdfcollate) (plus mis à jour depuis 2022), avec en plus : choix libre des dossiers, assemblage **sans perte** qui conserve l'OCR du scanner, OCR optionnel, suppression des versos blancs, rotation des versos, gestion des erreurs et des scans simple face.

```text
 Scanner ─ SMB ─►  /input                              /output
                   ├─ scan_0001.pdf  (rectos 1-3-5) ┐
                   └─ scan_0002.pdf  (versos 6-4-2) ┴─►  Scan_2026-10-28_10-15-03.pdf (1-2-3-4-5-6)
```

Image multi-architecture (`amd64`, `arm64`) : `ghcr.io/hexamus/simplex2duplex`

---

## Sommaire

- [Démarrage rapide](#démarrage-rapide)
- [Comment scanner](#comment-scanner)
- [Choisir les dossiers](#choisir-les-dossiers)
- [Qualité et OCR](#qualité-et-ocr)
- [Toutes les variables](#toutes-les-variables)
- [Installation sur Synology](#installation-sur-synology)
- [Configurer le scanner (exemple Brother)](#configurer-le-scanner-exemple-brother)
- [Assemblage ponctuel en ligne de commande](#assemblage-ponctuel-en-ligne-de-commande)
- [Dépannage](#dépannage)
- [Construire l'image soi-même](#construire-limage-soi-même)

---

## Démarrage rapide

```yaml
services:
  simplex2duplex:
    image: ghcr.io/hexamus/simplex2duplex:latest
    container_name: simplex2duplex
    restart: unless-stopped
    user: "1000:1000"                 # utilisateur propriétaire des dossiers
    volumes:
      - /chemin/vers/depot_scanner:/input
      - /chemin/vers/documents:/output
    environment:
      TZ: Europe/Paris
```

```bash
docker compose up -d
docker logs -f simplex2duplex
```

Un fichier [`docker-compose.yml`](docker-compose.yml) complet et commenté, prêt pour un Synology, est fourni dans le dépôt.

---

## Comment scanner

1. Posez la pile dans le chargeur et scannez → un premier PDF (les **rectos** : pages 1, 3, 5…).
2. Reprenez la pile **sans la mélanger**, retournez-la d'un bloc et reposez-la dans le chargeur.
3. Scannez à nouveau → un second PDF (les **versos**, qui arrivent dans l'ordre inverse : 6, 4, 2…).
4. Quelques secondes plus tard, le PDF recto-verso apparaît dans le dossier de sortie.

Règles d'appariement :

- Les fichiers sont associés **deux par deux, dans leur ordre d'arrivée** (le plus ancien = rectos).
- Les deux fichiers doivent avoir **le même nombre de pages**. Une page de versos vierge ? Scannez-la quand même, et activez `REMOVE_BLANK` pour la retirer automatiquement.
- Si aucun second fichier n'arrive dans le délai `PAIR_TIMEOUT` (15 min par défaut), le premier est considéré comme un document **simple face** et publié tel quel.
- Si les nombres de pages diffèrent, les deux fichiers sont déplacés dans `/input/_erreurs` : rien n'est perdu, rien n'est publié à tort.

> **Astuce** : si votre scanner permet plusieurs profils, créez-en un « Recto-verso » qui envoie vers le dossier surveillé et un « Simple » qui envoie directement vers le dossier final. Vos scans simple face n'attendront alors jamais le délai d'appariement.

---

## Choisir les dossiers

Les emplacements se choisissent librement, de deux façons complémentaires.

**Avec les volumes Docker (recommandé)** : seul le côté gauche change.

```yaml
volumes:
  - /volume1/Papier/tmp_scan:/input     # dépôt du scanner
  - /volume1/Papier/Scans:/output       # PDF finaux
  - /volume1/Archives/scans_bruts:/archive   # (facultatif) originaux
```

**Avec les variables d'environnement** : utile si vous montez un seul volume, ou hors Docker.

| Variable | Défaut | Rôle |
|---|---|---|
| `INPUT_DIR` | `/input` | Dossier surveillé (seuls les PDF à la racine sont pris, pas les sous-dossiers) |
| `OUTPUT_DIR` | `/output` | Dossier où sont publiés les PDF assemblés |
| `ARCHIVE_DIR` | `$INPUT_DIR/_originaux` | Où ranger les originaux quand `ORIGINALS=keep` |
| `ERROR_DIR` | `$INPUT_DIR/_erreurs` | Où déplacer les paires impossibles à assembler |

Exemple avec un seul partage :

```yaml
volumes:
  - /volume1/Papier:/papier
environment:
  INPUT_DIR: /papier/tmp_scan
  OUTPUT_DIR: /papier/Scans
  ARCHIVE_DIR: /papier/Archives/originaux
```

Le PDF final est d'abord écrit sous un nom temporaire caché (`.nom.pdf.part`) puis renommé : un outil qui surveille le dossier de sortie (Paperless-ngx, Synology Drive…) ne verra jamais de fichier à moitié écrit.

---

## Qualité et OCR

### Par défaut : aucune perte

Avec les réglages par défaut (`OCR=keep`, `OPTIMIZE=0`, `OUTPUT_TYPE=pdf`), Simplex2Duplex **ne recompresse rien**. Les pages sont recopiées objet par objet avec [pikepdf](https://github.com/pikepdf/pikepdf) : images, résolution, couleurs et **calque de texte OCR produit par le scanner** arrivent intacts dans le PDF final. La qualité se règle donc là où elle doit l'être : **dans le profil de scan** (résolution, couleur/gris, format « PDF interrogeable » si votre scanner le propose).

### Quand ajouter de l'OCR ou optimiser

Si votre scanner produit des PDF sans texte, ou si vous voulez des fichiers plus légers, Simplex2Duplex s'appuie sur [OCRmyPDF](https://ocrmypdf.readthedocs.io/) et Tesseract (français et anglais inclus).

| `OCR` | Effet | Images d'origine |
|---|---|---|
| `keep` *(défaut)* | Aucun OCR. Le texte déjà présent est conservé. | Intactes |
| `auto` | OCR **uniquement** des pages qui n'ont pas encore de texte. | Intactes |
| `redo` | Remplace le calque OCR existant par celui de Tesseract (utile si l'OCR du scanner est médiocre). | Intactes |
| `force` | Rastérise chaque page puis refait l'OCR. À réserver aux PDF « bizarres ». | **Recréées** |

| `OPTIMIZE` | Effet |
|---|---|
| `0` *(défaut)* | Aucune optimisation |
| `1` | Optimisations sans perte visible |
| `2` | Recompression avec perte (JPEG, PNG via pngquant) |
| `3` | Compression la plus agressive |

`OUTPUT_TYPE=pdfa` produit un PDF/A (archivage longue durée) ; la conversion passe par Ghostscript, qui réécrit les images.

### Mesures

PDF de 6 pages A4 en couleur à 150 dpi, déjà OCRisé par le « scanner » (sources : 111 850 octets).

| Réglage | Taille | Images identiques aux sources | Texte |
|---|---:|:---:|:---:|
| défaut (`keep`) | 110 916 o | ✅ | ✅ conservé |
| `OCR=redo` | 113 474 o | ✅ | ✅ refait |
| `ROTATE_EVEN=180` | 110 922 o | ✅ | ✅ |
| `OPTIMIZE=1` | 108 927 o | — | ✅ |
| `OPTIMIZE=3` | 64 031 o | — | ✅ |
| `OUTPUT_TYPE=pdfa` | 339 398 o | — | ✅ |
| `OCR=force` | 1 592 345 o | — | ✅ refait |

**Recommandation** : scannez en 300 dpi (gris pour du courrier, couleur si nécessaire) et gardez les réglages par défaut. Si le scanner ne sait pas produire de PDF interrogeable, passez `OCR=auto`. Ajoutez `OPTIMIZE=2` seulement si l'espace disque compte.

En cas d'échec d'OCRmyPDF, le PDF assemblé est publié **sans** post-traitement plutôt que d'être perdu (un avertissement apparaît dans les logs).

---

## Toutes les variables

| Variable | Défaut | Description |
|---|---|---|
| `INPUT_DIR` | `/input` | Dossier surveillé |
| `OUTPUT_DIR` | `/output` | Dossier de sortie |
| `ARCHIVE_DIR` | `$INPUT_DIR/_originaux` | Destination des originaux (`ORIGINALS=keep`) |
| `ERROR_DIR` | `$INPUT_DIR/_erreurs` | Destination des paires en échec |
| `ORIGINALS` | `keep` | `keep` = archiver les originaux, `delete` = les supprimer |
| `PAIR_TIMEOUT` | `900` | Secondes avant de publier un fichier resté seul en simple face. `0` = attendre indéfiniment |
| `STABLE_SECONDS` | `10` | Secondes sans modification avant de considérer qu'un fichier est complètement reçu |
| `POLL_INTERVAL` | `5` | Fréquence de scrutation du dossier (secondes) |
| `SORT_BY` | `mtime` | Ordre d'appariement : `mtime` (date d'arrivée) ou `name` (nom de fichier) |
| `REVERSE_EVEN` | `true` | Inverser l'ordre des versos (pile retournée). `false` si votre scanner les sort déjà dans l'ordre |
| `ROTATE_EVEN` | `0` | Rotation appliquée aux versos : `0`, `90`, `180`, `270` |
| `REMOVE_BLANK` | `false` | Supprimer les versos blancs |
| `BLANK_THRESHOLD` | `0.5` | Pourcentage de surface « encrée » sous lequel un verso est jugé blanc |
| `OCR` | `keep` | `keep`, `auto`, `redo`, `force` (voir [Qualité et OCR](#qualité-et-ocr)) |
| `OCR_LANG` | `fra+eng` | Langues Tesseract (`fra`, `eng` inclus dans l'image) |
| `OPTIMIZE` | `0` | Niveau d'optimisation OCRmyPDF, de `0` à `3` |
| `JPEG_QUALITY` | *(vide)* | Qualité JPEG imposée quand `OPTIMIZE` ≥ 2 (1-100) |
| `OUTPUT_TYPE` | `pdf` | `pdf` ou `pdfa` |
| `FILENAME_PATTERN` | `Scan_%Y-%m-%d_%H-%M-%S` | Nom du fichier produit, au format [strftime](https://strftime.org/). `.pdf` est ajouté, ainsi que `_2`, `_3`… en cas de doublon |
| `TZ` | `Europe/Paris` | Fuseau horaire (horodatage des noms et des logs) |
| `LOG_LEVEL` | `INFO` | `DEBUG` affiche notamment le taux d'encre de chaque verso |

---

## Installation sur Synology

Instructions pour DSM 7.2 et Container Manager.

1. **Créer les dossiers**, par exemple `Papier/tmp_scan` et `Papier/Scans` dans File Station.
2. **Trouver l'UID/GID de l'utilisateur** qu'utilisera le scanner pour écrire en SMB. En SSH : `id scanner` → par exemple `uid=1026(scanner) gid=100(users)`. Cet utilisateur doit avoir les droits lecture/écriture sur les deux dossiers.
3. **Container Manager → Projet → Créer** : chemin `/volume1/docker/Simplex2Duplex`, source « Créer docker-compose.yml », collez le [`docker-compose.yml`](docker-compose.yml) du dépôt en ajustant `user:` et les chemins.
4. Lancez le projet, puis ouvrez **Conteneur → simplex2duplex → Journal** : la ligne `Simplex2Duplex … démarré` récapitule la configuration active.

Pourquoi `user:` ? Le conteneur tourne alors avec la même identité que le scanner : il peut archiver ou supprimer les PDF déposés, et les PDF produits vous appartiennent (pas de fichiers `root` impossibles à supprimer depuis File Station).

Les dossiers `@eaDir` créés par l'indexation Synology et les fichiers cachés sont ignorés.

**Mise à jour** : Container Manager → Projet → Simplex2Duplex → Action → *Construire* (re-télécharge `latest`), ou figez une version précise (`ghcr.io/hexamus/simplex2duplex:1.0.0`).

---

## Configurer le scanner (exemple Brother)

Exemple pour une multifonction Brother récente (ex. MFC-L3760CDW) ; les libellés peuvent varier selon le modèle et le firmware. Les autres marques proposent des réglages équivalents (« Scan vers dossier réseau », « Scan to SMB »).

Les profils se créent dans l'interface web de l'imprimante (**Gestion à partir du Web**, `https://<ip-imprimante>`), puis s'utilisent depuis l'écran tactile.

1. **Numériser → Numérisation vers FTP/SFTP/Réseau/HTTP/SharePoint** : choisissez **Réseau** pour un profil libre, donnez-lui un nom (ex. `Recto-verso`).
2. **Profil de numérisation vers le réseau** — renseignez :
   - Adresse de l'hôte : IP du NAS ; Répertoire de stockage : `Papier\tmp_scan`
   - Nom de fichier : au choix (Simplex2Duplex renomme le résultat)
   - Qualité : `Couleur 300 ppp` ou `Gris 300 ppp`
   - Type de fichier : **PDF multi-pages** (ou PDF interrogeable si proposé)
   - Méthode d'authentification : `Auto` ; utilisateur / mot de passe du compte SMB choisi plus haut
3. *(Facultatif)* Un second profil `Simple` vers `Papier\Scans` pour les documents simple face.
4. Vérifiez que l'horloge de l'imprimante est juste (**Réseau → Protocole → SNTP**) : un écart d'heure fait échouer l'authentification SMB.

Sur l'écran tactile : **Numériser → vers le réseau → Recto-verso**, une fois pour les rectos, une fois pour les versos.

**Orientation des versos** : retournez la pile comme on tourne la page d'un livre (autour du bord long) et les versos arriveront à l'endroit. Si vous la retournez de haut en bas, ils arriveront tête en bas : réglez alors `ROTATE_EVEN=180`.

---

## Assemblage ponctuel en ligne de commande

Sans surveillance de dossier, pour un fichier isolé :

```bash
docker run --rm -v "$PWD":/data ghcr.io/hexamus/simplex2duplex \
  merge /data/rectos.pdf /data/versos.pdf -o /data/document.pdf
```

Les variables (`OCR`, `ROTATE_EVEN`, `REMOVE_BLANK`…) s'appliquent aussi : `docker run --rm -e OCR=auto …`.

Le script fonctionne aussi hors Docker (Python ≥ 3.9 et `pip install pikepdf` ; OCRmyPDF et poppler-utils seulement pour les options correspondantes) :

```bash
python3 collate.py merge rectos.pdf versos.pdf -o document.pdf
INPUT_DIR=~/scans OUTPUT_DIR=~/documents python3 collate.py
```

---

## Dépannage

| Symptôme | Cause probable / solution |
|---|---|
| `rectos reçus (…), en attente des versos…` et rien ne se passe | Le second scan n'est pas arrivé dans le dossier surveillé : vérifiez que les deux scans utilisent le même profil. |
| Paire dans `_erreurs` avec « nombre de pages différent » | Une feuille a été oubliée ou double-alimentée. Rescannez ; les originaux sont dans `_erreurs`. |
| Pages dans le mauvais ordre (1, 6, 2, 5…) | Le scanner sort déjà les versos dans l'ordre : `REVERSE_EVEN=false`. |
| Versos à l'envers | `ROTATE_EVEN=180`. |
| Une vraie page est supprimée comme blanche | Baissez `BLANK_THRESHOLD` (ex. `0.2`) ; `LOG_LEVEL=DEBUG` affiche le taux mesuré. |
| Un verso blanc n'est pas supprimé | Montez `BLANK_THRESHOLD` (ex. `1.5`) : bruit, ombre ou transparence du recto. |
| `Permission denied` dans les logs | L'utilisateur de `user:` n'a pas les droits sur les dossiers montés. |
| Un fichier arrivé seul a été publié trop tôt | Augmentez `PAIR_TIMEOUT`. |
| Deux scans simultanés de personnes différentes se mélangent | L'appariement suit l'ordre d'arrivée : utilisez un dossier surveillé par personne (une instance par dossier). |

Le conteneur expose un *healthcheck* : il passe `unhealthy` si la boucle de surveillance se bloque.

---


## Construire l'image soi-même

```bash
git clone https://github.com/hexamus/Simplex2Duplex.git && cd Simplex2Duplex
docker build -t simplex2duplex .
```

L'image publiée est construite par GitHub Actions ([`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)) pour `linux/amd64` et `linux/arm64` :

- chaque push sur `main` → `ghcr.io/hexamus/simplex2duplex:latest` et `:sha-xxxxxxx` ;
- chaque tag `vX.Y.Z` → `:X.Y.Z` et `:X.Y`.

Base : Debian trixie-slim, OCRmyPDF 16, pikepdf 9, Tesseract 5 (fra, eng).

---

## Licence

Distribué sous licence [MIT](LICENSE). Image construite à partir de logiciels libres : OCRmyPDF (MPL-2.0), pikepdf (MPL-2.0), Tesseract (Apache-2.0), Ghostscript (AGPL-3.0), Poppler (GPL).
