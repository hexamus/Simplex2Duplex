#!/usr/bin/env python3
"""
Simplex2Duplex — assemble deux PDF (rectos + versos) en un seul PDF recto-verso.

Remplaçant de cranium/pdfcollate pour les scanners dont le chargeur (ADF)
ne numérise qu'une face : on scanne la pile une première fois (rectos),
on la retourne, on la scanne une seconde fois (versos, en ordre inverse),
et Simplex2Duplex reconstitue le document dans le bon ordre.

Deux modes :
  collate.py                      -> surveille INPUT_DIR (mode service, Docker)
  collate.py merge A.pdf B.pdf -o sortie.pdf   -> assemblage ponctuel

L'assemblage est sans perte : les pages sont recopiées telles quelles
(images, polices, calque de texte OCR éventuel). Aucune recompression
n'a lieu tant que OCR=keep, OPTIMIZE=0 et OUTPUT_TYPE=pdf.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pikepdf

__version__ = os.environ.get("APP_VERSION", "dev")

log = logging.getLogger("simplex2duplex")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "oui", "vrai")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Variable {name} invalide : {raw!r} (entier attendu)")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        raise SystemExit(f"Variable {name} invalide : {raw!r} (nombre attendu)")


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    raw = os.environ.get(name, "").strip().lower() or default
    if raw not in choices:
        raise SystemExit(f"Variable {name} invalide : {raw!r} (valeurs possibles : {', '.join(choices)})")
    return raw


@dataclass
class Config:
    input_dir: Path
    output_dir: Path
    archive_dir: Path
    error_dir: Path
    originals: str            # keep | delete
    poll_interval: int
    stable_seconds: int
    pair_timeout: int         # 0 = attendre indéfiniment le 2e fichier
    sort_by: str              # mtime | name
    reverse_even: bool
    rotate_even: int          # 0 | 90 | 180 | 270
    remove_blank: bool
    blank_threshold: float    # % de pixels "encrés" en dessous duquel une page est blanche
    ocr: str                  # keep | auto | redo | force
    ocr_lang: str
    optimize: int             # 0..3 (ocrmypdf --optimize)
    output_type: str          # pdf | pdfa
    jpeg_quality: int         # 0 = défaut ocrmypdf
    filename_pattern: str

    @classmethod
    def from_env(cls) -> "Config":
        input_dir = Path(os.environ.get("INPUT_DIR", "/input"))
        output_dir = Path(os.environ.get("OUTPUT_DIR", "/output"))
        archive = os.environ.get("ARCHIVE_DIR", "").strip()
        errors = os.environ.get("ERROR_DIR", "").strip()
        rotate = _env_int("ROTATE_EVEN", 0)
        if rotate not in (0, 90, 180, 270):
            raise SystemExit("ROTATE_EVEN doit valoir 0, 90, 180 ou 270")
        optimize = _env_int("OPTIMIZE", 0)
        if not 0 <= optimize <= 3:
            raise SystemExit("OPTIMIZE doit être compris entre 0 et 3")
        return cls(
            input_dir=input_dir,
            output_dir=output_dir,
            archive_dir=Path(archive) if archive else input_dir / "_originaux",
            error_dir=Path(errors) if errors else input_dir / "_erreurs",
            originals=_env_choice("ORIGINALS", "keep", ("keep", "delete")),
            poll_interval=max(1, _env_int("POLL_INTERVAL", 5)),
            stable_seconds=max(0, _env_int("STABLE_SECONDS", 10)),
            pair_timeout=max(0, _env_int("PAIR_TIMEOUT", 900)),
            sort_by=_env_choice("SORT_BY", "mtime", ("mtime", "name")),
            reverse_even=_env_bool("REVERSE_EVEN", True),
            rotate_even=rotate,
            remove_blank=_env_bool("REMOVE_BLANK", False),
            blank_threshold=_env_float("BLANK_THRESHOLD", 0.5),
            ocr=_env_choice("OCR", "keep", ("keep", "auto", "redo", "force")),
            ocr_lang=os.environ.get("OCR_LANG", "fra+eng").strip() or "fra+eng",
            optimize=optimize,
            output_type=_env_choice("OUTPUT_TYPE", "pdf", ("pdf", "pdfa")),
            jpeg_quality=max(0, min(100, _env_int("JPEG_QUALITY", 0))),
            filename_pattern=os.environ.get("FILENAME_PATTERN", "Scan_%Y-%m-%d_%H-%M-%S").strip()
            or "Scan_%Y-%m-%d_%H-%M-%S",
        )

    @property
    def needs_postprocess(self) -> bool:
        return self.ocr != "keep" or self.optimize > 0 or self.output_type != "pdf"

    def describe(self) -> str:
        return (
            f"entrée={self.input_dir} sortie={self.output_dir} "
            f"originaux={self.originals}"
            + (f"→{self.archive_dir}" if self.originals == "keep" else "")
            + f" versos_inversés={self.reverse_even} rotation_versos={self.rotate_even}° "
            f"pages_blanches={'supprimées' if self.remove_blank else 'conservées'} "
            f"ocr={self.ocr}({self.ocr_lang}) optimize={self.optimize} "
            f"type={self.output_type} délai_appariement={self.pair_timeout or '∞'}s"
        )


# --------------------------------------------------------------------------- #
# Traitement PDF
# --------------------------------------------------------------------------- #

class CollateError(Exception):
    """Erreur métier : la paire ne peut pas être assemblée."""


def page_ink_ratio(pdf_path: Path, page_number: int) -> float:
    """Pourcentage de pixels sombres d'une page (rendu basse résolution, marges ignorées)."""
    from PIL import Image  # import tardif : seulement si REMOVE_BLANK

    with tempfile.TemporaryDirectory(prefix="blank-") as tmp:
        prefix = Path(tmp) / "p"
        subprocess.run(
            ["pdftoppm", "-f", str(page_number), "-l", str(page_number),
             "-r", "50", "-gray", "-png", "-singlefile", str(pdf_path), str(prefix)],
            check=True, capture_output=True,
        )
        with Image.open(f"{prefix}.png") as img:
            w, h = img.size
            mx, my = int(w * 0.05), int(h * 0.05)  # ignore 5 % de marge (ombres du chargeur)
            img = img.crop((mx, my, w - mx, h - my)).convert("L")
            hist = img.histogram()
            dark = sum(hist[:180])
            total = sum(hist) or 1
            return 100.0 * dark / total


def interleave(recto_path: Path, verso_path: Path, out_path: Path, cfg: Config) -> int:
    """Entrelace les pages. Retourne le nombre de pages écrites."""
    with pikepdf.open(recto_path) as rectos, pikepdf.open(verso_path) as versos:
        n_r, n_v = len(rectos.pages), len(versos.pages)
        if n_r != n_v:
            raise CollateError(
                f"nombre de pages différent : {recto_path.name}={n_r}, {verso_path.name}={n_v}"
            )
        order = list(range(n_v))
        if cfg.reverse_even:
            order.reverse()

        blank: set[int] = set()
        if cfg.remove_blank:
            for idx in order:
                ratio = page_ink_ratio(verso_path, idx + 1)
                if ratio < cfg.blank_threshold:
                    blank.add(idx)
                log.debug("verso p.%d : %.3f %% d'encre", idx + 1, ratio)
            if blank:
                log.info("%d verso(s) blanc(s) supprimé(s)", len(blank))

        out = pikepdf.new()
        for i in range(n_r):
            out.pages.append(rectos.pages[i])
            v_idx = order[i]
            if v_idx in blank:
                continue
            out.pages.append(versos.pages[v_idx])
            if cfg.rotate_even:
                out.pages[-1].rotate(cfg.rotate_even, relative=True)

        _copy_metadata(rectos, out)
        out.save(out_path)
        return len(out.pages)


def passthrough(src: Path, out_path: Path) -> int:
    """Document simple face : recopie à l'identique."""
    with pikepdf.open(src) as pdf:
        out = pikepdf.new()
        out.pages.extend(pdf.pages)
        _copy_metadata(pdf, out)
        out.save(out_path)
        return len(out.pages)


def _copy_metadata(src: pikepdf.Pdf, dst: pikepdf.Pdf) -> None:
    try:
        for key in ("/Author", "/Creator", "/CreationDate"):
            if key in src.docinfo:
                dst.docinfo[key] = src.docinfo[key]
        dst.docinfo["/Producer"] = f"Simplex2Duplex {__version__} (pikepdf {pikepdf.__version__})"
    except Exception:  # métadonnées non critiques
        pass


def postprocess(src: Path, dst: Path, cfg: Config) -> None:
    """OCR / optimisation / PDF-A via ocrmypdf. Lève CalledProcessError en cas d'échec."""
    cmd = ["ocrmypdf", "--output-type", cfg.output_type, "-l", cfg.ocr_lang,
           "--optimize", str(cfg.optimize), "--quiet"]
    if cfg.ocr == "keep":
        # Pas d'OCR : uniquement optimisation / conversion PDF-A.
        cmd += ["--skip-text", "--tesseract-timeout", "0"]
    elif cfg.ocr == "auto":
        cmd += ["--skip-text"]          # OCR des seules pages sans texte
    elif cfg.ocr == "redo":
        cmd += ["--redo-ocr"]           # remplace le calque OCR, images intactes
    elif cfg.ocr == "force":
        cmd += ["--force-ocr"]          # re-rastérise toutes les pages
    if cfg.jpeg_quality:
        cmd += ["--jpeg-quality", str(cfg.jpeg_quality)]
    cmd += [str(src), str(dst)]
    log.debug("exécution : %s", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd, res.stdout, res.stderr)


# --------------------------------------------------------------------------- #
# Fichiers
# --------------------------------------------------------------------------- #

def unique_path(directory: Path, stem: str, suffix: str = ".pdf") -> Path:
    candidate = directory / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{n}{suffix}"
        n += 1
    return candidate


def publish(tmp_file: Path, cfg: Config, when: datetime) -> Path:
    """Copie atomique vers OUTPUT_DIR (fichier .part puis renommage)."""
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    final = unique_path(cfg.output_dir, when.strftime(cfg.filename_pattern))
    part = final.with_name(f".{final.name}.part")
    shutil.copyfile(tmp_file, part)
    os.replace(part, final)
    return final


def move_to(src: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dst = unique_path(directory, src.stem, src.suffix)
    shutil.move(str(src), dst)
    return dst


def dispose_originals(files: list[Path], cfg: Config) -> None:
    for f in files:
        try:
            if cfg.originals == "delete":
                f.unlink()
            else:
                move_to(f, cfg.archive_dir)
        except OSError as exc:
            log.warning("impossible de ranger l'original %s : %s", f.name, exc)


def process(files: list[Path], cfg: Config) -> Path | None:
    """Traite une paire (2 fichiers) ou un fichier seul. Retourne le PDF produit."""
    when = datetime.now()
    names = " + ".join(f.name for f in files)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="21scan-") as tmp:
        merged = Path(tmp) / "merged.pdf"
        try:
            if len(files) == 2:
                pages = interleave(files[0], files[1], merged, cfg)
            else:
                pages = passthrough(files[0], merged)
        except (CollateError, pikepdf.PdfError) as exc:
            log.error("échec de l'assemblage (%s) : %s → déplacés dans %s", names, exc, cfg.error_dir)
            for f in files:
                try:
                    move_to(f, cfg.error_dir)
                except OSError as mv_exc:
                    log.error("impossible de déplacer %s : %s", f.name, mv_exc)
            return None

        result = merged
        if cfg.needs_postprocess:
            processed = Path(tmp) / "final.pdf"
            try:
                postprocess(merged, processed, cfg)
                result = processed
            except FileNotFoundError:
                log.warning("ocrmypdf introuvable : PDF publié sans OCR ni optimisation")
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or "").strip().splitlines()[-1:] or [""]
                log.warning("ocrmypdf a échoué (code %s) %s — PDF publié sans post-traitement",
                            exc.returncode, detail[0])

        final = publish(result, cfg, when)

    dispose_originals(files, cfg)
    kind = "recto-verso" if len(files) == 2 else "simple face"
    log.info("%s → %s (%d page(s), %s, %.1fs)", names, final.name, pages, kind, time.monotonic() - t0)
    return final


# --------------------------------------------------------------------------- #
# Surveillance du dossier
# --------------------------------------------------------------------------- #

class Watcher:
    HEARTBEAT = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/simplex2duplex.heartbeat"))

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.seen: dict[Path, tuple[int, float, float]] = {}  # chemin -> (taille, mtime, vu_stable_depuis)
        self.running = True
        self.waiting_logged: Path | None = None

    def stop(self, *_):
        log.info("arrêt demandé")
        self.running = False

    def candidates(self) -> list[Path]:
        try:
            entries = list(self.cfg.input_dir.iterdir())
        except FileNotFoundError:
            log.error("dossier d'entrée introuvable : %s", self.cfg.input_dir)
            return []
        return [
            p for p in entries
            if p.is_file()
            and p.suffix.lower() == ".pdf"
            and not p.name.startswith((".", "@", "~", "#"))
        ]

    def stable_files(self) -> list[Path]:
        now = time.time()
        current = set()
        ready: list[Path] = []
        for p in self.candidates():
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            current.add(p)
            prev = self.seen.get(p)
            if prev is None or prev[0] != st.st_size or prev[1] != st.st_mtime:
                self.seen[p] = (st.st_size, st.st_mtime, now)
                continue
            if st.st_size > 0 and now - prev[2] >= self.cfg.stable_seconds and self._readable(p):
                ready.append(p)
        for gone in set(self.seen) - current:
            self.seen.pop(gone, None)
        if self.cfg.sort_by == "name":
            ready.sort(key=lambda p: p.name)
        else:
            ready.sort(key=lambda p: (p.stat().st_mtime, p.name))
        return ready

    @staticmethod
    def _readable(p: Path) -> bool:
        try:
            with pikepdf.open(p):
                return True
        except Exception:
            return False  # encore en cours d'écriture, ou corrompu (réessayé au tour suivant)

    def tick(self) -> None:
        ready = self.stable_files()
        while len(ready) >= 2:
            pair, ready = ready[:2], ready[2:]
            self.waiting_logged = None
            process(pair, self.cfg)
            for p in pair:
                self.seen.pop(p, None)
        if len(ready) == 1:
            single = ready[0]
            age = time.time() - self.seen.get(single, (0, 0, time.time()))[2]
            if self.cfg.pair_timeout and age >= self.cfg.pair_timeout:
                log.info("pas de second fichier pour %s après %ds : traité en simple face",
                         single.name, self.cfg.pair_timeout)
                process([single], self.cfg)
                self.seen.pop(single, None)
                self.waiting_logged = None
            elif self.waiting_logged != single:
                log.info("rectos reçus (%s), en attente des versos…", single.name)
                self.waiting_logged = single

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.cfg.input_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)
        log.info("Simplex2Duplex %s démarré — %s", __version__, self.cfg.describe())
        while self.running:
            try:
                self.tick()
            except Exception:
                log.exception("erreur inattendue (la surveillance continue)")
            try:
                self.HEARTBEAT.touch()
            except OSError:
                pass
            for _ in range(self.cfg.poll_interval * 10):
                if not self.running:
                    break
                time.sleep(0.1)


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="collate.py",
        description="Assemble un PDF de rectos et un PDF de versos en un seul PDF recto-verso.",
    )
    parser.add_argument("--version", action="version", version=f"Simplex2Duplex {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("watch", help="surveille INPUT_DIR (comportement par défaut)")
    m = sub.add_parser("merge", help="assemble deux fichiers une seule fois")
    m.add_argument("rectos", type=Path)
    m.add_argument("versos", type=Path)
    m.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    cfg = Config.from_env()

    if args.cmd == "merge":
        with tempfile.TemporaryDirectory(prefix="21scan-") as tmp:
            merged = Path(tmp) / "merged.pdf"
            try:
                pages = interleave(args.rectos, args.versos, merged, cfg)
            except CollateError as exc:
                log.error("%s", exc)
                return 2
            if cfg.needs_postprocess:
                postprocess(merged, args.output, cfg)
            else:
                shutil.copyfile(merged, args.output)
        log.info("%s écrit (%d pages)", args.output, pages)
        return 0

    Watcher(cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
