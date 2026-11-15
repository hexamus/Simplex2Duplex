"""
Notifications de Simplex2Duplex : Telegram, ntfy, Apprise (bibliothèque) et
Apprise API (serveur apprise-api).

Chaque service est activé dès que sa variable principale est renseignée ;
plusieurs services peuvent fonctionner en même temps. Les envois partent dans
un fil d'exécution séparé : un service lent ou injoignable ne bloque jamais
l'assemblage des scans.

Événements :
  success   assemblage recto-verso réussi
  partial   PDF publié, mais avec un problème (OCR/optimisation en échec,
            original impossible à archiver…)
  single    fichier resté seul, publié en simple face après PAIR_TIMEOUT
  error     assemblage impossible (fichiers déplacés dans _erreurs) ou
            erreur inattendue du service
  startup   démarrage du conteneur

Filtre : NOTIFY_EVENTS=all | none | liste séparée par des virgules
(ex. "error,partial"). Chaque service peut avoir son propre filtre
(TELEGRAM_EVENTS, NTFY_EVENTS, APPRISE_EVENTS, APPRISE_API_EVENTS) ;
à défaut, NOTIFY_EVENTS s'applique.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("simplex2duplex.notify")

EVENTS = ("success", "partial", "single", "error", "startup")

# Noms français acceptés dans les variables.
_ALIASES = {
    "succes": "success", "succès": "success", "ok": "success", "reussi": "success", "réussi": "success",
    "partiel": "partial", "warning": "partial", "avertissement": "partial",
    "simple": "single", "simple_face": "single", "simplex": "single",
    "erreur": "error", "erreurs": "error", "echec": "error", "échec": "error", "failure": "error",
    "demarrage": "startup", "démarrage": "startup", "start": "startup",
}

DEFAULT_EVENTS = "error,partial"

_ICONS = {"success": "✅", "partial": "⚠️", "single": "📄", "error": "❌", "startup": "🚀"}
_NTFY_PRIORITY = {"success": 3, "partial": 4, "single": 3, "error": 5, "startup": 2}
_NTFY_TAGS = {
    "success": "white_check_mark", "partial": "warning", "single": "page_facing_up",
    "error": "x", "startup": "rocket",
}
_APPRISE_TYPE = {
    "success": "success", "partial": "warning", "single": "info", "error": "failure", "startup": "info",
}

TIMEOUT = 15      # secondes par requête HTTP
RETRIES = 3       # tentatives par service
RETRY_DELAY = 5   # secondes entre deux tentatives


def parse_events(raw: str | None, name: str, default: frozenset[str] | None = None) -> frozenset[str]:
    """Convertit 'all', 'none' ou une liste 'error,partial' en ensemble d'événements."""
    if raw is None or raw.strip() == "":
        if default is not None:
            return default
        raw = DEFAULT_EVENTS
    value = raw.strip().lower()
    if value in ("all", "tout", "tous", "*"):
        return frozenset(EVENTS)
    if value in ("none", "aucun", "off", "0", "false"):
        return frozenset()
    result = set()
    for item in value.replace(";", ",").replace(" ", ",").split(","):
        item = item.strip()
        if not item:
            continue
        item = _ALIASES.get(item, item)
        if item not in EVENTS:
            raise SystemExit(
                f"Variable {name} invalide : événement {item!r} inconnu "
                f"(valeurs possibles : all, none, {', '.join(EVENTS)})"
            )
        result.add(item)
    return frozenset(result)


@dataclass
class Message:
    event: str
    title: str
    body: str

    @property
    def icon(self) -> str:
        return _ICONS.get(self.event, "")

    def text(self) -> str:
        return f"{self.icon} {self.title}\n{self.body}".strip()


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #

def _http(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", "replace").strip()
        raise RuntimeError(f"HTTP {exc.code} {exc.reason} {detail}") from None
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        raise RuntimeError(f"connexion impossible : {getattr(exc, 'reason', exc)}") from None


def _json(url: str, payload: dict, headers: dict[str, str] | None = None) -> None:
    h = {"Content-Type": "application/json", "User-Agent": "Simplex2Duplex"}
    h.update(headers or {})
    _http(url, json.dumps(payload).encode("utf-8"), h)


@dataclass
class Backend:
    name: str
    events: frozenset[str]

    def wants(self, event: str) -> bool:
        return event in self.events

    def send(self, msg: Message) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> str:
        return f"{self.name}[{','.join(e for e in EVENTS if e in self.events) or 'aucun'}]"


@dataclass
class Telegram(Backend):
    token: str = ""
    chat_ids: list[str] = field(default_factory=list)
    thread_id: str = ""
    api_url: str = "https://api.telegram.org"
    silent_events: frozenset[str] = frozenset()

    def send(self, msg: Message) -> None:
        url = f"{self.api_url.rstrip('/')}/bot{self.token}/sendMessage"
        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": msg.text(),
                "disable_web_page_preview": True,
                "disable_notification": msg.event in self.silent_events,
            }
            if self.thread_id:
                payload["message_thread_id"] = int(self.thread_id)
            try:
                _json(url, payload)
            except RuntimeError as exc:
                # ne jamais afficher le jeton dans les logs
                raise RuntimeError(str(exc).replace(self.token, "***")) from None


@dataclass
class Ntfy(Backend):
    server: str = ""
    topic: str = ""
    token: str = ""
    user: str = ""
    password: str = ""
    priority: str = ""
    tags: str = ""
    click: str = ""

    @classmethod
    def split_url(cls, url: str) -> tuple[str, str]:
        """https://ntfy.sh/mon-sujet -> ('https://ntfy.sh', 'mon-sujet')"""
        parsed = urllib.parse.urlsplit(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise SystemExit(f"NTFY_URL invalide : {url!r} (ex. https://ntfy.sh/mon-sujet)")
        path = parsed.path.rstrip("/")
        base, _, topic = path.rpartition("/")
        if not topic:
            raise SystemExit(f"NTFY_URL invalide : {url!r} — le sujet (topic) manque après le serveur")
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, base, "", "")), topic

    def send(self, msg: Message) -> None:
        # Publication JSON (accents et emojis gérés, contrairement aux en-têtes HTTP)
        payload = {
            "topic": self.topic,
            "title": msg.title,
            "message": msg.body or msg.title,
            "priority": int(self.priority) if self.priority else _NTFY_PRIORITY.get(msg.event, 3),
            "tags": [t.strip() for t in self.tags.split(",") if t.strip()] or [_NTFY_TAGS.get(msg.event, "")],
        }
        if self.click:
            payload["click"] = self.click
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.user:
            cred = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {cred}"
        _json(self.server + "/", payload, headers)


@dataclass
class AppriseLib(Backend):
    urls: list[str] = field(default_factory=list)
    _apobj: object = None

    def __post_init__(self):
        try:
            import apprise  # type: ignore
        except ImportError:
            raise SystemExit("APPRISE_URLS est défini mais la bibliothèque apprise n'est pas installée "
                             "(pip install apprise)")
        self._apprise = apprise
        if not log.isEnabledFor(logging.DEBUG):
            logging.getLogger("apprise").setLevel(logging.WARNING)
        self._apobj = apprise.Apprise()
        for url in self.urls:
            if not self._apobj.add(url) or len(self._apobj) == 0:
                raise SystemExit("APPRISE_URLS : aucune URL reconnue par Apprise "
                                 "(voir https://github.com/caronc/apprise/wiki)")

    def send(self, msg: Message) -> None:
        ntype = {
            "success": self._apprise.NotifyType.SUCCESS,
            "warning": self._apprise.NotifyType.WARNING,
            "failure": self._apprise.NotifyType.FAILURE,
        }.get(_APPRISE_TYPE.get(msg.event, "info"), self._apprise.NotifyType.INFO)
        if not self._apobj.notify(title=f"{msg.icon} {msg.title}", body=msg.body or msg.title,
                                  notify_type=ntype):
            raise RuntimeError("au moins un service Apprise a refusé la notification")


@dataclass
class AppriseApi(Backend):
    url: str = ""
    tag: str = ""
    urls: str = ""   # pour le mode « stateless » (/notify/ sans clé)

    def send(self, msg: Message) -> None:
        payload = {
            "title": f"{msg.icon} {msg.title}",
            "body": msg.body or msg.title,
            "type": _APPRISE_TYPE.get(msg.event, "info"),
        }
        if self.tag:
            payload["tag"] = self.tag
        if self.urls:
            payload["urls"] = self.urls
        _json(self.url, payload)


# --------------------------------------------------------------------------- #
# Répartiteur
# --------------------------------------------------------------------------- #

class Notifier:
    """Envoie les notifications en arrière-plan vers tous les services configurés."""

    def __init__(self, backends: list[Backend], prefix: str = ""):
        self.backends = backends
        self.prefix = prefix
        self._queue: "queue.Queue[Message | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        if backends:
            self._thread = threading.Thread(target=self._worker, name="notify", daemon=True)
            self._thread.start()

    @classmethod
    def from_env(cls) -> "Notifier":
        env = os.environ
        default = parse_events(env.get("NOTIFY_EVENTS"), "NOTIFY_EVENTS")

        def events(var: str) -> frozenset[str]:
            return parse_events(env.get(var), var, default)

        backends: list[Backend] = []

        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        chats = [c.strip() for c in env.get("TELEGRAM_CHAT_ID", "").replace(";", ",").split(",") if c.strip()]
        if token or chats:
            if not (token and chats):
                raise SystemExit("Telegram : TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID doivent être définis ensemble")
            thread = env.get("TELEGRAM_THREAD_ID", "").strip()
            if thread and not thread.lstrip("-").isdigit():
                raise SystemExit("TELEGRAM_THREAD_ID doit être un nombre")
            backends.append(Telegram(
                "telegram", events("TELEGRAM_EVENTS"), token=token, chat_ids=chats, thread_id=thread,
                api_url=env.get("TELEGRAM_API_URL", "").strip() or "https://api.telegram.org",
                silent_events=parse_events(env.get("TELEGRAM_SILENT_EVENTS"), "TELEGRAM_SILENT_EVENTS",
                                           frozenset({"success", "single", "startup"})),
            ))

        ntfy_url = env.get("NTFY_URL", "").strip()
        if ntfy_url:
            server, topic = Ntfy.split_url(ntfy_url)
            prio = env.get("NTFY_PRIORITY", "").strip()
            if prio and prio not in ("1", "2", "3", "4", "5"):
                raise SystemExit("NTFY_PRIORITY doit être compris entre 1 et 5")
            backends.append(Ntfy(
                "ntfy", events("NTFY_EVENTS"), server=server, topic=topic,
                token=env.get("NTFY_TOKEN", "").strip(),
                user=env.get("NTFY_USER", "").strip(), password=env.get("NTFY_PASSWORD", ""),
                priority=prio, tags=env.get("NTFY_TAGS", ""), click=env.get("NTFY_CLICK", "").strip(),
            ))

        apprise_urls = env.get("APPRISE_URLS", "").strip()
        if apprise_urls:
            # Apprise découpe lui-même une liste séparée par espaces, virgules ou retours à la ligne.
            backends.append(AppriseLib("apprise", events("APPRISE_EVENTS"), urls=[apprise_urls]))

        api_url = env.get("APPRISE_API_URL", "").strip()
        if api_url:
            if not api_url.startswith(("http://", "https://")):
                raise SystemExit("APPRISE_API_URL doit commencer par http:// ou https://")
            backends.append(AppriseApi(
                "apprise-api", events("APPRISE_API_EVENTS"), url=api_url,
                tag=env.get("APPRISE_API_TAG", "").strip(), urls=env.get("APPRISE_API_URLS", "").strip(),
            ))

        return cls(backends, prefix=env.get("NOTIFY_PREFIX", "").strip())

    # -- API publique ------------------------------------------------------- #

    @property
    def enabled(self) -> bool:
        return bool(self.backends)

    def describe(self) -> str:
        return " ".join(b.describe() for b in self.backends) if self.backends else "aucune"

    def notify(self, event: str, title: str, body: str = "") -> None:
        if not self.backends or not any(b.wants(event) for b in self.backends):
            return
        if self.prefix:
            title = f"{self.prefix} — {title}"
        self._queue.put(Message(event, title, body))

    def send_now(self, event: str, title: str, body: str = "", force: bool = False) -> bool:
        """Envoi synchrone (commande notify-test). Retourne True si tout a réussi."""
        msg = Message(event, f"{self.prefix} — {title}" if self.prefix else title, body)
        ok = True
        targets = [b for b in self.backends if force or b.wants(event)]
        if not targets:
            log.warning("aucun service n'est abonné à l'événement %r (voir NOTIFY_EVENTS / *_EVENTS)", event)
            return False
        for b in targets:
            try:
                b.send(msg)
                log.info("notification %s : envoyée", b.name)
            except Exception as exc:
                ok = False
                log.error("notification %s : échec — %s", b.name, exc)
        return ok

    def close(self, timeout: float = 8) -> None:
        """Vide la file avant l'arrêt (au plus `timeout` secondes)."""
        if not self._thread:
            return
        self._queue.put(None)
        self._thread.join(timeout)

    # -- interne ------------------------------------------------------------ #

    def _worker(self) -> None:
        while True:
            msg = self._queue.get()
            if msg is None:
                return
            for b in self.backends:
                if b.wants(msg.event):
                    self._deliver(b, msg)

    @staticmethod
    def _deliver(backend: Backend, msg: Message) -> None:
        for attempt in range(1, RETRIES + 1):
            try:
                backend.send(msg)
                log.debug("notification %s envoyée (%s)", backend.name, msg.event)
                return
            except Exception as exc:
                if attempt == RETRIES:
                    log.warning("notification %s abandonnée après %d essais : %s", backend.name, attempt, exc)
                    return
                log.debug("notification %s : essai %d échoué (%s), nouvel essai dans %ds",
                          backend.name, attempt, exc, RETRY_DELAY)
                time.sleep(RETRY_DELAY)
