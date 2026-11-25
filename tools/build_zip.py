#!/usr/bin/env python3
"""Genera dist/360paraiso.zip listo para subir a SiteGround (File Manager -> Extract).

El ZIP trae los archivos directo en la raíz (index.html, manifest.json, .htaccess, crm/, img/, tour/),
para extraerlo dentro de public_html de 360paraiso.cautivamarketing.com. Se deja fuera lo que no sirve
en producción: tools/, *.jsx, node_modules, archivos de Firebase/Vercel, dist/, README.

Se niega a generar el zip si el tour no tiene la huella de licencia de 3DVista (ver tour_license_problems).

Uso:  python tools/build_zip.py [--allow-unlicensed]
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
STAGE = DIST / "_stage"
OUT = DIST / "360paraiso.zip"

EXCLUDE_DIRS = {"tools", "dist", "node_modules", ".claude", ".git", ".vercel", ".firebase", ".codegraph", "__MACOSX"}
EXCLUDE_FILES = {
    "package.json", "package-lock.json", "firebase.json", "firestore.rules", ".firebaserc",
    "vercel.json", ".vercelignore", ".gitignore", "README.md", ".DS_Store", "Thumbs.db",
}
EXCLUDE_SUFFIXES = {".jsx"}


def keep(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if rel.name in EXCLUDE_FILES or rel.suffix in EXCLUDE_SUFFIXES:
        return False
    if rel.name.startswith(".env"):  # .env.local y similares: jamás a un servidor público
        return False
    return True


def tour_license_problems() -> list:
    """Un export de 3DVista con licencia trae el correo en lib/tdvplayer.json y 'watermark':false en
    script_general.js. Sin eso el tour sale con la marca de agua 'Created with 3DVista'."""
    problems = []
    player = ROOT / "tour" / "lib" / "tdvplayer.json"
    if not player.is_file() or '"email"' not in player.read_text(encoding="utf-8"):
        problems.append('tour/lib/tdvplayer.json no trae "email" de la licencia')
    script = ROOT / "tour" / "script_general.js"
    if not script.is_file() or '"watermark":false' not in script.read_text(encoding="utf-8"):
        problems.append('tour/script_general.js no tiene "watermark":false')
    return problems


def find_bsdtar():
    """tar de Windows/macOS (bsdtar). El GNU tar de Git Bash no sirve: lee 'D:' como un host remoto."""
    candidates = []
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidates.append(Path(system_root) / "System32" / "tar.exe")
    found = shutil.which("tar")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            try:
                version = subprocess.run([str(candidate), "--version"], capture_output=True, text=True).stdout
            except OSError:
                continue
            if "bsdtar" in version.lower():
                return str(candidate)
    return None


def main() -> None:
    app_jsx, app_js = ROOT / "crm" / "app.jsx", ROOT / "crm" / "app.js"
    if not app_js.is_file():
        sys.exit("[ERROR] Falta crm/app.js. Compila antes: npm run build")
    if app_jsx.is_file() and app_jsx.stat().st_mtime > app_js.stat().st_mtime:
        sys.exit("[ERROR] crm/app.js está desactualizado respecto a crm/app.jsx. Vuelve a compilar (npm run build).")
    for needed in ("index.html", "crm/lots.js", "crm/firebase-config.js", "tour/index.htm", "tour/crm-bridge.js"):
        if not (ROOT / needed).is_file():
            sys.exit(f"[ERROR] Falta {needed}. Corre tools/sync_tour.py.")
    if "REEMPLAZAR" in (ROOT / "crm" / "firebase-config.js").read_text(encoding="utf-8"):
        sys.exit("[ERROR] crm/firebase-config.js todavía tiene valores REEMPLAZAR_...")
    problems = tour_license_problems()
    if problems and "--allow-unlicensed" not in sys.argv:
        sys.exit(
            "[ERROR] El tour NO parece exportado con licencia de 3DVista (saldría con marca de agua):\n  - "
            + "\n  - ".join(problems)
            + "\n  Exporta desde el 3DVista con licencia, ponlo en 3D/Paraiso del Rio/paraiso y corre tools/sync_tour.py."
            "\n  (Solo para pruebas internas: python tools/build_zip.py --allow-unlicensed)"
        )

    if DIST.exists():
        shutil.rmtree(DIST)
    STAGE.mkdir(parents=True)

    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if not keep(rel):
            continue
        dest = STAGE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        files.append(rel.as_posix())

    tar = find_bsdtar()
    if tar:
        top_level = sorted(p.name for p in STAGE.iterdir())
        subprocess.run([tar, "-a", "-c", "-f", str(OUT), "-C", str(STAGE), *top_level], check=True)
    else:
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in files:
                zf.write(STAGE / rel, rel)

    shutil.rmtree(STAGE)
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Listo: {OUT}")
    print(f"  {len(files)} archivos, {size_mb:.1f} MB (extraer directo en public_html de 360paraiso.cautivamarketing.com)")


if __name__ == "__main__":
    main()
