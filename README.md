# Simplex2Duplex

**English** | [Français](README.fr.md)

**Double-sided scanning for scanners that can only do one side.**

Your document feeder (ADF) only scans one side? Scan the stack, flip it over, scan it again: Simplex2Duplex picks up both PDFs from a folder, puts the pages back in order (1, 2, 3, 4…) and drops a single double-sided PDF in the folder of your choice.

A maintained replacement for [`cranium/pdfcollate`](https://hub.docker.com/r/cranium/pdfcollate) (not updated since 2022), with extras: freely chosen folders, **lossless** merging that keeps the scanner's OCR, optional OCR, blank back-page removal, back-page rotation, error handling and single-sided scans, **notifications** (Telegram, ntfy, Apprise).

```text
 Scanner ─ SMB ─►  /input                              /output
                   ├─ scan_0001.pdf  (fronts 1-3-5) ┐
                   └─ scan_0002.pdf  (backs  6-4-2) ┴─►  Scan_2026-10-28_10-15-03.pdf (1-2-3-4-5-6)
```

Multi-architecture image (`amd64`, `arm64`): `ghcr.io/hexamus/simplex2duplex`

---

## Contents

- [Quick start](#quick-start)
- [How to scan](#how-to-scan)
- [Choosing folders](#choosing-folders)
- [Quality and OCR](#quality-and-ocr)
- [Notifications](#notifications)
- [All variables](#all-variables)
- [Installing on Synology](#installing-on-synology)
- [Setting up the scanner (Brother example)](#setting-up-the-scanner-brother-example)
- [One-off merge from the command line](#one-off-merge-from-the-command-line)
- [Troubleshooting](#troubleshooting)
- [Building the image yourself](#building-the-image-yourself)

---

## Quick start

```yaml
services:
  simplex2duplex:
    image: ghcr.io/hexamus/simplex2duplex:latest
    container_name: simplex2duplex
    restart: unless-stopped
    user: "1000:1000"                 # user that owns the folders
    volumes:
      - /path/to/scanner_drop:/input
      - /path/to/documents:/output
    environment:
      TZ: Europe/Paris
      APP_LANG: en                    # language of logs and notifications: en | fr
```

```bash
docker compose up -d
docker logs -f simplex2duplex
```

A complete, commented [`docker-compose.yml`](docker-compose.yml), ready for a Synology, is included in the repository.

> **Language**: `APP_LANG` (`fr` by default, or `en`) sets the language of logs, notifications and error messages, as well as the default OCR languages. The examples below assume `APP_LANG=en`.

---

## How to scan

1. Put the stack in the feeder and scan → a first PDF (the **fronts**: pages 1, 3, 5…).
2. Take the stack **without shuffling it**, flip it over as a whole and put it back in the feeder.
3. Scan again → a second PDF (the **backs**, which arrive in reverse order: 6, 4, 2…).
4. A few seconds later, the double-sided PDF appears in the output folder.

Pairing rules:

- Files are paired **two by two, in order of arrival** (the oldest = fronts).
- Both files must have **the same number of pages**. A blank back page? Scan it anyway, and enable `REMOVE_BLANK` to drop it automatically.
- If no second file arrives within `PAIR_TIMEOUT` (15 min by default), the first one is treated as a **single-sided** document and published as is.
- If the page counts differ, both files are moved to `/input/_erreurs`: nothing is lost, nothing is published by mistake.

> **Tip**: if your scanner supports several profiles, create a "Double-sided" one that sends to the watched folder and a "Single" one that sends straight to the final folder. Your single-sided scans will then never wait for the pairing timeout.

---

## Choosing folders

Locations can be chosen freely, in two complementary ways.

**With Docker volumes (recommended)**: only the left-hand side changes.

```yaml
volumes:
  - /volume1/Paper/tmp_scan:/input          # scanner drop folder
  - /volume1/Paper/Scans:/output            # final PDFs
  - /volume1/Archives/raw_scans:/archive    # (optional) originals
```

**With environment variables**: useful if you mount a single volume, or outside Docker.

| Variable | Default | Purpose |
|---|---|---|
| `INPUT_DIR` | `/input` | Watched folder (only PDFs at the root are picked up, not subfolders) |
| `OUTPUT_DIR` | `/output` | Folder where merged PDFs are published |
| `ARCHIVE_DIR` | `$INPUT_DIR/_originaux` | Where originals are stored when `ORIGINALS=keep` |
| `ERROR_DIR` | `$INPUT_DIR/_erreurs` | Where pairs that cannot be merged are moved |

Example with a single share:

```yaml
volumes:
  - /volume1/Paper:/paper
environment:
  INPUT_DIR: /paper/tmp_scan
  OUTPUT_DIR: /paper/Scans
  ARCHIVE_DIR: /paper/Archives/originals
```

The final PDF is first written under a hidden temporary name (`.name.pdf.part`) and then renamed: a tool watching the output folder (Paperless-ngx, Synology Drive…) will never see a half-written file.

---

## Quality and OCR

### By default: no loss

With the default settings (`OCR=keep`, `OPTIMIZE=0`, `OUTPUT_TYPE=pdf`), Simplex2Duplex **recompresses nothing**. Pages are copied object by object with [pikepdf](https://github.com/pikepdf/pikepdf): images, resolution, colours and the **OCR text layer produced by the scanner** reach the final PDF untouched. Quality is therefore set where it belongs: **in the scan profile** (resolution, colour/grey, "searchable PDF" format if your scanner offers it).

### When to add OCR or optimise

If your scanner produces PDFs without text, or if you want lighter files, Simplex2Duplex relies on [OCRmyPDF](https://ocrmypdf.readthedocs.io/) and Tesseract (French and English included). OCR languages follow `APP_LANG` (`fra+eng` in French, `eng` in English) unless `OCR_LANG` is set.

| `OCR` | Effect | Original images |
|---|---|---|
| `keep` *(default)* | No OCR. Existing text is kept. | Untouched |
| `auto` | OCR **only** on pages that have no text yet. | Untouched |
| `redo` | Replaces the existing OCR layer with Tesseract's (useful if the scanner's OCR is poor). | Untouched |
| `force` | Rasterises every page then redoes the OCR. For "odd" PDFs only. | **Re-created** |

| `OPTIMIZE` | Effect |
|---|---|
| `0` *(default)* | No optimisation |
| `1` | Optimisations with no visible loss |
| `2` | Lossy recompression (JPEG, PNG via pngquant) |
| `3` | Most aggressive compression |

`OUTPUT_TYPE=pdfa` produces a PDF/A (long-term archiving); the conversion goes through Ghostscript, which rewrites the images.

### Measurements

6-page A4 colour PDF at 150 dpi, already OCR'd by the "scanner" (sources: 111,850 bytes).

| Setting | Size | Images identical to sources | Text |
|---|---:|:---:|:---:|
| default (`keep`) | 110,916 B | ✅ | ✅ kept |
| `OCR=redo` | 113,474 B | ✅ | ✅ redone |
| `ROTATE_EVEN=180` | 110,922 B | ✅ | ✅ |
| `OPTIMIZE=1` | 108,927 B | — | ✅ |
| `OPTIMIZE=3` | 64,031 B | — | ✅ |
| `OUTPUT_TYPE=pdfa` | 339,398 B | — | ✅ |
| `OCR=force` | 1,592,345 B | — | ✅ redone |

**Recommendation**: scan at 300 dpi (grey for letters, colour when needed) and keep the default settings. If the scanner cannot produce searchable PDFs, set `OCR=auto`. Add `OPTIMIZE=2` only if disk space matters.

If OCRmyPDF fails, the merged PDF is published **without** post-processing rather than lost (a warning appears in the logs).

---

## Notifications

Simplex2Duplex can let you know when a scan is ready, or only when something goes wrong. Four services are supported; each one is enabled as soon as its main variable is set, and several can run at the same time.

| Service | Minimum variables |
|---|---|
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **ntfy** | `NTFY_URL` (e.g. `https://ntfy.sh/my-scans`) |
| **Apprise** (built-in library, 100+ services: Discord, Gotify, Pushover, e-mail, Matrix, Home Assistant…) | `APPRISE_URLS` |
| **Apprise API** (an existing [apprise-api](https://github.com/caronc/apprise-api) server) | `APPRISE_API_URL` |

### Choosing events

| Event | When | Accepted aliases |
|---|---|---|
| `success` | Double-sided merge succeeded | `succes`, `ok`, `reussi` |
| `partial` | PDF published, but with a problem: OCR/optimisation failed, original could not be archived… | `partiel`, `warning` |
| `single` | File left alone, published single-sided after `PAIR_TIMEOUT` | `simple` |
| `error` | Merge impossible (files in `_erreurs`), cannot write, unexpected error | `erreur`, `echec` |
| `startup` | Container started | `demarrage` |

`NOTIFY_EVENTS` sets the shared filter: `all`, `none` or a list, for example `error,partial` *(default)*. Each service can have its own filter, which then replaces `NOTIFY_EVENTS` for that service only: `TELEGRAM_EVENTS`, `NTFY_EVENTS`, `APPRISE_EVENTS`, `APPRISE_API_EVENTS`.

Example: only problems on Telegram, everything on ntfy.

```yaml
environment:
  NOTIFY_EVENTS: "error,partial"          # shared filter
  TELEGRAM_BOT_TOKEN: "123456:ABC-DEF…"
  TELEGRAM_CHAT_ID: "123456789"
  NTFY_URL: "https://ntfy.example.com/scans"
  NTFY_TOKEN: "tk_…"
  NTFY_EVENTS: "all"                      # ntfy gets everything
```

An error that repeats identically (output folder unreachable, for example) is only notified once. Messages are sent in the background with 3 attempts: an unreachable service never blocks merging.

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send a message to your bot (or add it to a group), then open `https://api.telegram.org/bot<TOKEN>/getUpdates`: the `chat.id` value goes into `TELEGRAM_CHAT_ID` (groups start with `-100`).

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_CHAT_ID` | | One or more IDs separated by commas |
| `TELEGRAM_THREAD_ID` | | Topic of a forum group |
| `TELEGRAM_SILENT_EVENTS` | `success,single,startup` | Events sent without sound; `none` to always ring |
| `TELEGRAM_API_URL` | `https://api.telegram.org` | Self-hosted Bot API server |

### ntfy

| Variable | Purpose |
|---|---|
| `NTFY_URL` | Server + topic: `https://ntfy.sh/my-secret-topic` or your own instance |
| `NTFY_TOKEN` | Access token (`tk_…`) — or `NTFY_USER` + `NTFY_PASSWORD` |
| `NTFY_PRIORITY` | Forces a priority 1-5. Default: error 5, partial 4, success/single 3, startup 2 |
| `NTFY_TAGS` | Replaces the automatic tags/emojis (e.g. `printer,fr`) |
| `NTFY_CLICK` | URL opened when tapping the notification (e.g. your Paperless) |

### Apprise

`APPRISE_URLS` accepts one or more [Apprise URLs](https://github.com/caronc/apprise/wiki) separated by spaces or commas:

```yaml
APPRISE_URLS: "discord://webhook_id/webhook_token gotify://gotify.example.com/AbCdEf"
```

If you already run an **apprise-api** server, use instead:

| Variable | Purpose |
|---|---|
| `APPRISE_API_URL` | `http://apprise:8000/notify/my-key` (configuration stored on the server) or `http://apprise:8000/notify/` |
| `APPRISE_API_URLS` | Destination URL(s), only with `/notify/` without a key |
| `APPRISE_API_TAG` | Only notify targets with this tag |

### Testing

```bash
docker exec simplex2duplex python3 /app/collate.py notify-test          # all services, no filter
docker exec simplex2duplex python3 /app/collate.py notify-test error    # simulates an error, filters applied
```

At startup, the log lists active services and their events: `notifications: telegram[partial,error] ntfy[success,partial,single,error,startup]`.

`NOTIFY_PREFIX` (e.g. `Office`) prefixes every title: handy with several instances.

---

## All variables

| Variable | Default | Description |
|---|---|---|
| `APP_LANG` | `fr` | Language of logs, notifications and error messages: `fr` or `en`. Also sets the default `OCR_LANG` |
| `INPUT_DIR` | `/input` | Watched folder |
| `OUTPUT_DIR` | `/output` | Output folder |
| `ARCHIVE_DIR` | `$INPUT_DIR/_originaux` | Destination for originals (`ORIGINALS=keep`) |
| `ERROR_DIR` | `$INPUT_DIR/_erreurs` | Destination for failed pairs |
| `ORIGINALS` | `keep` | `keep` = archive originals, `delete` = delete them |
| `PAIR_TIMEOUT` | `900` | Seconds before a file left alone is published single-sided. `0` = wait forever |
| `STABLE_SECONDS` | `10` | Seconds without changes before a file is considered fully received |
| `POLL_INTERVAL` | `5` | Folder polling interval (seconds) |
| `SORT_BY` | `mtime` | Pairing order: `mtime` (arrival time) or `name` (file name) |
| `REVERSE_EVEN` | `true` | Reverse the order of back pages (flipped stack). `false` if your scanner already outputs them in order |
| `ROTATE_EVEN` | `0` | Rotation applied to back pages: `0`, `90`, `180`, `270` |
| `REMOVE_BLANK` | `false` | Remove blank back pages |
| `BLANK_THRESHOLD` | `0.5` | Percentage of "inked" area below which a back page is considered blank |
| `OCR` | `keep` | `keep`, `auto`, `redo`, `force` (see [Quality and OCR](#quality-and-ocr)) |
| `OCR_LANG` | `fra+eng` (fr) / `eng` (en) | Tesseract languages (`fra`, `eng` included in the image). Default depends on `APP_LANG` |
| `OPTIMIZE` | `0` | OCRmyPDF optimisation level, `0` to `3` |
| `JPEG_QUALITY` | *(empty)* | JPEG quality enforced when `OPTIMIZE` ≥ 2 (1-100) |
| `OUTPUT_TYPE` | `pdf` | `pdf` or `pdfa` |
| `FILENAME_PATTERN` | `Scan_%Y-%m-%d_%H-%M-%S` | Output file name, in [strftime](https://strftime.org/) format. `.pdf` is appended, plus `_2`, `_3`… on duplicates |
| `TZ` | `Europe/Paris` | Time zone (timestamps in names and logs) |
| `LOG_LEVEL` | `INFO` | `DEBUG` notably shows the ink ratio of each back page |
| `NOTIFY_EVENTS` | `error,partial` | Notified events: `all`, `none` or a list (see [Notifications](#notifications), which also details each service's variables) |

---

## Installing on Synology

Instructions for DSM 7.2 and Container Manager.

1. **Create the folders**, for example `Paper/tmp_scan` and `Paper/Scans` in File Station.
2. **Find the UID/GID of the user** the scanner will use to write over SMB. Over SSH: `id scanner` → for example `uid=1026(scanner) gid=100(users)`. This user needs read/write access to both folders.
3. **Container Manager → Project → Create**: path `/volume1/docker/Simplex2Duplex`, source "Create docker-compose.yml", paste the repository's [`docker-compose.yml`](docker-compose.yml) and adjust `user:` and the paths.
4. Start the project, then open **Container → simplex2duplex → Log**: the `Simplex2Duplex … started` line summarises the active configuration.

Why `user:`? The container then runs with the same identity as the scanner: it can archive or delete the dropped PDFs, and the PDFs it produces belong to you (no `root` files that File Station cannot delete).

`@eaDir` folders created by Synology indexing and hidden files are ignored.

**Updating**: Container Manager → Project → Simplex2Duplex → Action → *Build* (pulls `latest` again), or pin a specific version (`ghcr.io/hexamus/simplex2duplex:1.0.0`).

---

## Setting up the scanner (Brother example)

Example for a recent Brother multifunction printer (e.g. MFC-L3760CDW); labels may vary by model and firmware. Other brands offer equivalent settings ("Scan to network folder", "Scan to SMB").

Profiles are created in the printer's web interface (**Web Based Management**, `https://<printer-ip>`), then used from the touchscreen.

1. **Scan → Scan to FTP/SFTP/Network/HTTP/SharePoint**: choose **Network** for a free profile and give it a name (e.g. `Duplex`).
2. **Scan to Network Profile** — fill in:
   - Host Address: NAS IP; Store Directory: `Paper\tmp_scan`
   - File Name: anything (Simplex2Duplex renames the result)
   - Quality: `Color 300 dpi` or `Gray 300 dpi`
   - File Type: **multi-page PDF** (or searchable PDF if available)
   - Auth. Method: `Auto`; username / password of the SMB account chosen above
3. *(Optional)* A second `Single` profile pointing to `Paper\Scans` for single-sided documents.
4. Make sure the printer's clock is correct (**Network → Protocol → SNTP**): a time offset makes SMB authentication fail.

On the touchscreen: **Scan → to Network → Duplex**, once for the fronts, once for the backs.

**Back-page orientation**: flip the stack like turning a book page (around the long edge) and the backs will arrive the right way up. If you flip it top to bottom, they will arrive upside down: then set `ROTATE_EVEN=180`.

---

## One-off merge from the command line

Without folder watching, for a single document:

```bash
docker run --rm -v "$PWD":/data ghcr.io/hexamus/simplex2duplex \
  merge /data/fronts.pdf /data/backs.pdf -o /data/document.pdf
```

Variables (`OCR`, `ROTATE_EVEN`, `REMOVE_BLANK`…) apply here too: `docker run --rm -e OCR=auto …`.

The script also works outside Docker (Python ≥ 3.9 and `pip install pikepdf`; OCRmyPDF and poppler-utils only for the matching options):

```bash
python3 collate.py merge fronts.pdf backs.pdf -o document.pdf
INPUT_DIR=~/scans OUTPUT_DIR=~/documents python3 collate.py
```

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `fronts received (…), waiting for backs…` and nothing happens | The second scan did not reach the watched folder: check that both scans use the same profile. |
| Pair in `_erreurs` with "page count mismatch" | A sheet was missed or double-fed. Rescan; the originals are in `_erreurs`. |
| Pages in the wrong order (1, 6, 2, 5…) | The scanner already outputs back pages in order: `REVERSE_EVEN=false`. |
| Back pages upside down | `ROTATE_EVEN=180`. |
| A real page is removed as blank | Lower `BLANK_THRESHOLD` (e.g. `0.2`); `LOG_LEVEL=DEBUG` shows the measured ratio. |
| A blank back page is not removed | Raise `BLANK_THRESHOLD` (e.g. `1.5`): noise, shadow or front-page show-through. |
| `Permission denied` in the logs | The `user:` account has no rights on the mounted folders. |
| A file that arrived alone was published too early | Increase `PAIR_TIMEOUT`. |
| No notification received | `notify-test` (see [Testing](#testing)); check the `NOTIFY_EVENTS` filter and that the NAS can reach the service (DNS, firewall). |
| Two simultaneous scans from different people get mixed | Pairing follows arrival order: use one watched folder per person (one instance per folder). |

The container exposes a *healthcheck*: it turns `unhealthy` if the watch loop gets stuck.

---

## Building the image yourself

```bash
git clone https://github.com/hexamus/Simplex2Duplex.git && cd Simplex2Duplex
docker build -t simplex2duplex .
```

The published image is built by GitHub Actions ([`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)) for `linux/amd64` and `linux/arm64`:

- every push to `main` → `ghcr.io/hexamus/simplex2duplex:latest` and `:sha-xxxxxxx`;
- every `vX.Y.Z` tag → `:X.Y.Z` and `:X.Y`.

Base: `python:3.13-alpine`, OCRmyPDF 17, pikepdf 10, Pillow 13, Apprise (from PyPI), Tesseract 5 (fra, eng). The image is rebuilt without cache every Monday to pick up the latest Alpine and PyPI security fixes.

---

## License

Released under the [MIT](LICENSE) license. Image built from free software: OCRmyPDF (MPL-2.0), pikepdf (MPL-2.0), Tesseract (Apache-2.0), Ghostscript (AGPL-3.0), Poppler (GPL).
