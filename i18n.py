"""
Messages of Simplex2Duplex in French and English (logs, notifications, errors).

The language is chosen with APP_LANG (fr | en). It also sets the default
Tesseract languages when OCR_LANG is not defined.

Messages de Simplex2Duplex en français et en anglais (journaux, notifications,
erreurs). La langue se choisit avec APP_LANG (fr | en) ; elle fixe aussi les
langues Tesseract par défaut quand OCR_LANG n'est pas défini.
"""

from __future__ import annotations

import os

LANGS = ("fr", "en")
DEFAULT_LANG = "fr"

# Langues Tesseract par défaut selon APP_LANG (OCR_LANG prend le dessus).
DEFAULT_OCR_LANG = {"fr": "fra+eng", "en": "eng"}

_ALIASES = {
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "francais": "fr", "français": "fr",
    "en": "en", "eng": "en", "english": "en", "anglais": "en",
}

_lang = DEFAULT_LANG


def parse_lang(raw: str | None) -> str:
    """'fr', 'fr_FR.UTF-8', 'English'… -> 'fr' | 'en'. Lève SystemExit si inconnu."""
    value = (raw or "").strip().lower()
    if not value:
        return DEFAULT_LANG
    value = value.split(".")[0].replace("-", "_").split("_")[0]
    if value not in _ALIASES:
        raise SystemExit(f"APP_LANG: {raw!r} — valeurs possibles / allowed values: {', '.join(LANGS)}")
    return _ALIASES[value]


def set_lang(lang: str) -> None:
    global _lang
    _lang = parse_lang(lang)


def get_lang() -> str:
    return _lang


def init_from_env() -> str:
    set_lang(os.environ.get("APP_LANG"))
    return _lang


def t(key: str, **kwargs) -> str:
    entry = MESSAGES[key]
    text = entry.get(_lang) or entry["en"]
    return text.format(**kwargs) if kwargs else text


MESSAGES: dict[str, dict[str, str]] = {
    # ---- Configuration ---------------------------------------------------- #
    "cfg.int": {
        "fr": "Variable {name} invalide : {raw!r} (entier attendu)",
        "en": "Invalid {name}: {raw!r} (integer expected)",
    },
    "cfg.float": {
        "fr": "Variable {name} invalide : {raw!r} (nombre attendu)",
        "en": "Invalid {name}: {raw!r} (number expected)",
    },
    "cfg.choice": {
        "fr": "Variable {name} invalide : {raw!r} (valeurs possibles : {choices})",
        "en": "Invalid {name}: {raw!r} (allowed values: {choices})",
    },
    "cfg.rotate": {
        "fr": "ROTATE_EVEN doit valoir 0, 90, 180 ou 270",
        "en": "ROTATE_EVEN must be 0, 90, 180 or 270",
    },
    "cfg.optimize": {
        "fr": "OPTIMIZE doit être compris entre 0 et 3",
        "en": "OPTIMIZE must be between 0 and 3",
    },
    "cfg.describe": {
        "fr": ("langue={lang} entrée={input} sortie={output} originaux={originals} "
               "versos_inversés={reverse} rotation_versos={rotate}° pages_blanches={blank} "
               "ocr={ocr}({ocr_lang}) optimize={optimize} type={type} délai_appariement={timeout}s"),
        "en": ("language={lang} input={input} output={output} originals={originals} "
               "reverse_backs={reverse} rotate_backs={rotate}° blank_pages={blank} "
               "ocr={ocr}({ocr_lang}) optimize={optimize} type={type} pairing_timeout={timeout}s"),
    },
    "cfg.blank_removed": {"fr": "supprimées", "en": "removed"},
    "cfg.blank_kept": {"fr": "conservées", "en": "kept"},

    # ---- Assemblage ------------------------------------------------------- #
    "err.page_count": {
        "fr": "nombre de pages différent : {a}={na}, {b}={nb}",
        "en": "page count mismatch: {a}={na}, {b}={nb}",
    },
    "log.ink": {
        "fr": "verso p.{page} : {ratio:.3f} % d'encre",
        "en": "back p.{page}: {ratio:.3f} % ink",
    },
    "log.blank_removed": {
        "fr": "{n} verso(s) blanc(s) supprimé(s)",
        "en": "{n} blank back page(s) removed",
    },
    "log.exec": {"fr": "exécution : {cmd}", "en": "running: {cmd}"},
    "log.original_not_stored": {
        "fr": "impossible de ranger l'original {name} : {exc}",
        "en": "cannot store original {name}: {exc}",
    },
    "warn.original_not_stored": {
        "fr": "original {name} non rangé : {exc}",
        "en": "original {name} not stored: {exc}",
    },
    "log.merge_failed": {
        "fr": "échec de l'assemblage ({names}) : {exc} → déplacés dans {dir}",
        "en": "merge failed ({names}): {exc} → moved to {dir}",
    },
    "log.cannot_move": {
        "fr": "impossible de déplacer {name} : {exc}",
        "en": "cannot move {name}: {exc}",
    },
    "notif.merge_failed.title": {"fr": "Échec de l'assemblage", "en": "Merge failed"},
    "notif.merge_failed.body": {
        "fr": "Fichiers : {names}\nCause : {exc}\n",
        "en": "Files: {names}\nCause: {exc}\n",
    },
    "notif.moved_to": {"fr": "Déplacés dans : {dir}", "en": "Moved to: {dir}"},
    "notif.not_moved": {"fr": "⚠️ fichiers non déplacés", "en": "⚠️ files not moved"},
    "warn.no_ocrmypdf": {
        "fr": "ocrmypdf introuvable : PDF publié sans OCR ni optimisation",
        "en": "ocrmypdf not found: PDF published without OCR or optimisation",
    },
    "log.ocrmypdf_failed": {
        "fr": "ocrmypdf a échoué (code {code}) {detail} — PDF publié sans post-traitement",
        "en": "ocrmypdf failed (code {code}) {detail} — PDF published without post-processing",
    },
    "warn.ocrmypdf_failed": {
        "fr": "OCR/optimisation en échec (code {code}) {detail}",
        "en": "OCR/optimisation failed (code {code}) {detail}",
    },
    "warn.no_postprocess": {
        "fr": " — PDF publié sans post-traitement",
        "en": " — PDF published without post-processing",
    },
    "kind.duplex": {"fr": "recto-verso", "en": "double-sided"},
    "kind.simplex": {"fr": "simple face", "en": "single-sided"},
    "log.done": {
        "fr": "{names} → {final} ({pages} page(s), {kind}, {elapsed:.1f}s)",
        "en": "{names} → {final} ({pages} page(s), {kind}, {elapsed:.1f}s)",
    },
    "notif.done.body": {
        "fr": "{final} — {pages} page(s), {kind}, {elapsed:.1f}s\nSources : {names}",
        "en": "{final} — {pages} page(s), {kind}, {elapsed:.1f}s\nSources: {names}",
    },
    "notif.partial.title": {"fr": "Scan publié avec avertissement(s)", "en": "Scan published with warning(s)"},
    "notif.single.title": {"fr": "Scan simple face publié", "en": "Single-sided scan published"},
    "notif.success.title": {"fr": "Scan recto-verso prêt", "en": "Double-sided scan ready"},

    # ---- Surveillance ----------------------------------------------------- #
    "log.stop": {"fr": "arrêt demandé", "en": "shutdown requested"},
    "log.input_missing": {
        "fr": "dossier d'entrée introuvable : {dir}",
        "en": "input folder not found: {dir}",
    },
    "log.single_timeout": {
        "fr": "pas de second fichier pour {name} après {timeout}s : traité en simple face",
        "en": "no second file for {name} after {timeout}s: processed as single-sided",
    },
    "reason.single_timeout": {
        "fr": "Aucun second fichier reçu en {timeout}s",
        "en": "No second file received within {timeout}s",
    },
    "log.waiting_backs": {
        "fr": "rectos reçus ({name}), en attente des versos…",
        "en": "fronts received ({name}), waiting for backs…",
    },
    "log.processing_error": {
        "fr": "erreur pendant le traitement de {names}",
        "en": "error while processing {names}",
    },
    "notif.unexpected.title": {"fr": "Erreur inattendue", "en": "Unexpected error"},
    "notif.unexpected.body": {
        "fr": "{text}\nLa surveillance continue.",
        "en": "{text}\nWatching continues.",
    },
    "log.started": {
        "fr": "Simplex2Duplex {version} démarré — {config}",
        "en": "Simplex2Duplex {version} started — {config}",
    },
    "log.notifications": {"fr": "notifications : {services}", "en": "notifications: {services}"},
    "notif.startup.title": {
        "fr": "Simplex2Duplex {version} démarré",
        "en": "Simplex2Duplex {version} started",
    },
    "notif.startup.body": {
        "fr": "Surveillance de {input} → {output}",
        "en": "Watching {input} → {output}",
    },
    "log.unexpected": {
        "fr": "erreur inattendue (la surveillance continue)",
        "en": "unexpected error (watching continues)",
    },

    # ---- Ligne de commande ------------------------------------------------ #
    "cli.description": {
        "fr": "Assemble un PDF de rectos et un PDF de versos en un seul PDF recto-verso.",
        "en": "Merges a PDF of front pages and a PDF of back pages into one double-sided PDF.",
    },
    "cli.watch": {
        "fr": "surveille INPUT_DIR (comportement par défaut)",
        "en": "watch INPUT_DIR (default behaviour)",
    },
    "cli.merge": {"fr": "assemble deux fichiers une seule fois", "en": "merge two files once"},
    "cli.notify_test": {
        "fr": "envoie une notification de test à chaque service configuré",
        "en": "send a test notification to every configured service",
    },
    "cli.notify_test.event": {
        "fr": ("simule cet événement (success, partial, single, error, startup) "
               "en respectant les filtres ; sans argument, envoie à tous les services"),
        "en": ("simulate this event (success, partial, single, error, startup) "
               "honouring the filters; without argument, sends to every service"),
    },
    "cli.no_service": {
        "fr": ("aucun service de notification configuré "
               "(TELEGRAM_BOT_TOKEN, NTFY_URL, APPRISE_URLS ou APPRISE_API_URL)"),
        "en": ("no notification service configured "
               "(TELEGRAM_BOT_TOKEN, NTFY_URL, APPRISE_URLS or APPRISE_API_URL)"),
    },
    "cli.services": {"fr": "services : {services}", "en": "services: {services}"},
    "cli.event": {"fr": "événement", "en": "event"},
    "notif.test.title": {"fr": "Notification de test", "en": "Test notification"},
    "notif.test.body": {
        "fr": "Simplex2Duplex {version} — si vous lisez ceci, c'est configuré.",
        "en": "Simplex2Duplex {version} — if you can read this, it works.",
    },
    "cli.written": {"fr": "{path} écrit ({pages} pages)", "en": "{path} written ({pages} pages)"},

    # ---- Notifications ---------------------------------------------------- #
    "ntf.unknown_event": {
        "fr": "Variable {name} invalide : événement {item!r} inconnu (valeurs possibles : all, none, {events})",
        "en": "Invalid {name}: unknown event {item!r} (allowed values: all, none, {events})",
    },
    "ntf.none": {"fr": "aucun", "en": "none"},
    "ntf.none_f": {"fr": "aucune", "en": "none"},
    "ntf.connection": {"fr": "connexion impossible : {reason}", "en": "connection failed: {reason}"},
    "ntf.ntfy_url": {
        "fr": "NTFY_URL invalide : {url!r} (ex. https://ntfy.sh/mon-sujet)",
        "en": "Invalid NTFY_URL: {url!r} (e.g. https://ntfy.sh/my-topic)",
    },
    "ntf.ntfy_topic": {
        "fr": "NTFY_URL invalide : {url!r} — le sujet (topic) manque après le serveur",
        "en": "Invalid NTFY_URL: {url!r} — the topic is missing after the server",
    },
    "ntf.apprise_missing": {
        "fr": "APPRISE_URLS est défini mais la bibliothèque apprise n'est pas installée (pip install apprise)",
        "en": "APPRISE_URLS is set but the apprise library is not installed (pip install apprise)",
    },
    "ntf.apprise_no_url": {
        "fr": "APPRISE_URLS : aucune URL reconnue par Apprise (voir https://github.com/caronc/apprise/wiki)",
        "en": "APPRISE_URLS: no URL recognised by Apprise (see https://github.com/caronc/apprise/wiki)",
    },
    "ntf.apprise_refused": {
        "fr": "au moins un service Apprise a refusé la notification",
        "en": "at least one Apprise service refused the notification",
    },
    "ntf.telegram_pair": {
        "fr": "Telegram : TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID doivent être définis ensemble",
        "en": "Telegram: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set together",
    },
    "ntf.telegram_thread": {
        "fr": "TELEGRAM_THREAD_ID doit être un nombre",
        "en": "TELEGRAM_THREAD_ID must be a number",
    },
    "ntf.ntfy_priority": {
        "fr": "NTFY_PRIORITY doit être compris entre 1 et 5",
        "en": "NTFY_PRIORITY must be between 1 and 5",
    },
    "ntf.apprise_api_url": {
        "fr": "APPRISE_API_URL doit commencer par http:// ou https://",
        "en": "APPRISE_API_URL must start with http:// or https://",
    },
    "ntf.no_subscriber": {
        "fr": "aucun service n'est abonné à l'événement {event!r} (voir NOTIFY_EVENTS / *_EVENTS)",
        "en": "no service is subscribed to event {event!r} (see NOTIFY_EVENTS / *_EVENTS)",
    },
    "ntf.sent": {"fr": "notification {name} : envoyée", "en": "notification {name}: sent"},
    "ntf.failed": {"fr": "notification {name} : échec — {exc}", "en": "notification {name}: failed — {exc}"},
    "ntf.sent_debug": {
        "fr": "notification {name} envoyée ({event})",
        "en": "notification {name} sent ({event})",
    },
    "ntf.gave_up": {
        "fr": "notification {name} abandonnée après {n} essais : {exc}",
        "en": "notification {name} dropped after {n} attempts: {exc}",
    },
    "ntf.retry": {
        "fr": "notification {name} : essai {n} échoué ({exc}), nouvel essai dans {delay}s",
        "en": "notification {name}: attempt {n} failed ({exc}), retrying in {delay}s",
    },
}
