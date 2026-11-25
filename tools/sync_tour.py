#!/usr/bin/env python3
"""Sincroniza el export de 3DVista de Paraiso del Rio con el CRM.

Pasos (idempotente, se puede correr tras cada re-export):
  1. Copia  <3D/Paraiso del Rio/paraiso>/*  ->  tour/   (omite project.vtp, hotspots/, .DS_Store / __MACOSX) y borra de tour/
     lo que ya no esta en el export (deja tour/ como espejo, salvo los archivos propios del proyecto).
  2. Inyecta <script src="crm-bridge.js"></script> despues de script.js en tour/index.htm
     (es la UNICA edicion al export; script.js y script_general.js no se tocan).
  3. Lee tour/script_general.js (solo lectura) y busca los overlays de lote ("LM1-V" ... "LM30-V" -> mzm-01 ... mzm-30).
  4. Genera <imagen>_disponible.webp / _reservado.webp / _vendido.webp: en el export el poligono es invisible
     (relleno con alfa 1), asi que cada estado lleva su propio relleno de color y conserva el borde blanco.
  5. Escribe crm/lots.js (catalogo Mz M: area y precio del Excel; los lotes que no estan en el Excel van con 0)
     y tour/lots-map.json.

Uso:  python tools/sync_tour.py [--src RUTA_AL_EXPORT_WEB] [--skip-copy] [--regen-variants]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT.parent.parent / "3D" / "Paraiso del Rio" / "paraiso"
EXCEL = DEFAULT_SRC.parent / "Lotes_Manzana_M.xlsx"
BLOCK = "m"            # manzana del catalogo (Mz M)
TOTAL_LOTS = 30        # poligonos LM1-V ... LM30-V
TOUR = ROOT / "tour"
LOTS_JS = ROOT / "crm" / "lots.js"
LOTS_MAP = TOUR / "lots-map.json"

BRIDGE_TAG = '<script src="crm-bridge.js"></script>'
SKIP_NAMES = {".DS_Store", "__MACOSX", "Thumbs.db"}
SKIP_TOP = {"project.vtp", "hotspots"}  # archivos del proyecto 3DVista, no del export web
OWN_FILES = {"crm-bridge.js", "lots-map.json", ".htaccess"}
VARIANT_RE = re.compile(r"_(disponible|reservado|vendido)\.webp$")

COLORS = {
    "disponible": (16, 185, 129),  # #10b981 verde
    "reservado": (245, 158, 11),   # #f59e0b ambar
    "vendido": (239, 68, 68),      # #ef4444 rojo
}
FILL_ALPHA = 150     # opacidad (0-255) del relleno de color
BORDER_MIN_ALPHA = 64  # pixeles con alfa >= esto se consideran borde y se conservan tal cual

SCRIPT_MARKER = "var script = {"
OVERLAY_CLASS = '"class":"HotspotPanoramaOverlay"'
EXPORT_FILES = ("index.htm", "script_general.js")


def is_export(folder: Path) -> bool:
    return all((folder / name).is_file() for name in EXPORT_FILES)


def resolve_export(src: Path) -> Path:
    """Devuelve la carpeta del export. Acepta web/ o web/<subcarpeta> cuando web/ solo trae una."""
    if not src.is_dir():
        sys.exit(f"[ERROR] No existe la carpeta del export: {src}")
    if is_export(src):
        stale = [p.name for p in src.iterdir() if p.is_dir() and p.name not in SKIP_NAMES and is_export(p)]
        if stale:
            print(f"  [AVISO] web/ ya es un export y ademas tiene subcarpetas de export ({', '.join(stale)}): se usa web/. "
                  "Si el export nuevo esta en la subcarpeta, borra el export viejo de web/ o pasa --src.")
        return src
    nested = [p for p in src.iterdir() if p.is_dir() and p.name not in SKIP_NAMES and is_export(p)]
    if len(nested) == 1:
        print(f"  (el export esta en la subcarpeta {nested[0].name}/)")
        return nested[0]
    sys.exit(f"[ERROR] {src} no parece un export de 3DVista (falta {' / '.join(EXPORT_FILES)}).")


def warn_if_unlicensed() -> None:
    """Un export con licencia trae el correo en lib/tdvplayer.json y 'watermark':false en script_general.js."""
    player = TOUR / "lib" / "tdvplayer.json"
    script = TOUR / "script_general.js"
    problems = []
    if not player.is_file() or '"email"' not in player.read_text(encoding="utf-8"):
        problems.append('lib/tdvplayer.json sin "email" de la licencia')
    if not script.is_file() or '"watermark":false' not in script.read_text(encoding="utf-8"):
        problems.append('script_general.js sin "watermark":false')
    if problems:
        print("  [AVISO] export SIN licencia de 3DVista (saldria con marca de agua): " + "; ".join(problems))
        print("          No lo publiques en SiteGround. tools/build_zip.py se negara a generar el zip.")
    else:
        print("  licencia de 3DVista detectada")


def copy_export(src: Path) -> int:
    """Copia el export a tour/ sin borrar nada. Devuelve cuantos archivos copio."""
    copied = 0
    for path in src.rglob("*"):
        parts = path.relative_to(src).parts
        if any(part in SKIP_NAMES for part in parts) or parts[0] in SKIP_TOP:
            continue
        dest = TOUR / path.relative_to(src)
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        if dest.exists():
            if path.name == "index.htm" and path.parent == src:
                # El index del tour lleva nuestra inyeccion: comparar sin ella.
                injected = dest.read_text(encoding="utf-8").replace("\n    " + BRIDGE_TAG, "")
                if injected == path.read_text(encoding="utf-8"):
                    continue
            else:
                s, d = path.stat(), dest.stat()
                if s.st_size == d.st_size and int(s.st_mtime) <= int(d.st_mtime):
                    continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
    return copied


def prune_tour(src: Path) -> int:
    """Borra de tour/ lo que ya no existe en el export. Respeta OWN_FILES y las variantes de color."""
    in_export = {p.relative_to(src) for p in src.rglob("*")
                 if p.is_file() and p.relative_to(src).parts[0] not in SKIP_TOP}
    removed = 0
    for path in TOUR.rglob("*"):
        if not path.is_file():
            continue
        if path.relative_to(TOUR) in in_export or path.name in OWN_FILES or VARIANT_RE.search(path.name):
            continue
        path.unlink()
        removed += 1
    dirs = [p for p in TOUR.rglob("*") if p.is_dir()]
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return removed


def inject_bridge() -> str:
    """Agrega el script del puente a tour/index.htm (idempotente)."""
    index = TOUR / "index.htm"
    html = index.read_text(encoding="utf-8")
    if "crm-bridge.js" in html:
        return "ya estaba inyectado"
    pattern = re.compile(r'(<script\s+src="script\.js[^"]*"\s*>\s*</script>)')
    if not pattern.search(html):
        sys.exit("[ERROR] No encontre <script src=\"script.js...\"> en tour/index.htm")
    html = pattern.sub(lambda m: m.group(1) + "\n    " + BRIDGE_TAG, html, count=1)
    index.write_text(html, encoding="utf-8")
    return "inyectado"


def iter_overlay_objects(script_text: str):
    """Rinde el texto de cada objeto `{...}` que declara 'class':'HotspotPanoramaOverlay' directamente."""
    start = script_text.find(SCRIPT_MARKER)
    if start < 0:
        return
    i, n = start + len(SCRIPT_MARKER) - 1, len(script_text)
    stack, in_str = [], False
    while i < n:
        c = script_text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            if stack and script_text.startswith(OVERLAY_CLASS, i):
                stack[-1][1] = True
                i += len(OVERLAY_CLASS) - 1
            else:
                in_str = True
        elif c == "{":
            stack.append([i, False])
        elif c == "}":
            opened, is_overlay = stack.pop()
            if is_overlay:
                yield script_text[opened:i + 1]
            if not stack:
                return
        i += 1


def parse_overlay_label(raw_label: str) -> Optional[Tuple[str, str, str, int]]:
    """Parsea una etiqueta de overlay y devuelve (lot_id, lot_name, block_display, lot_number).

    Soporta:
      - "Mz A' - Lote 01 · 206.79 m²" / "Mz C - Lote 05"
      - "A'1", "A'10", "C`10", "O-12", "P-5", "M24"
      - "LA1-V", "LAp1-V"
      - "mzap-01", "mzo-12"
    """
    if not isinstance(raw_label, str):
        return None
    s = raw_label.strip()
    if "·" in s:
        s = s.split("·")[0].strip()
    s = s.replace("`", "'").replace("´", "'")

    # 1. Mz <Block> - Lote <N>
    m = re.match(r"^mz\.?\s+([a-zA-Z]['pP]?)\s*-\s*lote\s*0*(\d+)$", s, re.IGNORECASE)
    if not m:
        # 2. L<Block><N>-V
        m = re.match(r"^l([a-zA-Z]['pP]?)0*(\d+)-v$", s, re.IGNORECASE)
    if not m:
        # 3. Mz<Block>-<N>
        m = re.match(r"^mz[-_]?([a-zA-Z]['pP]?)[-_]?0*(\d+)$", s, re.IGNORECASE)
    if not m:
        # 4. <Block>-<N> o <Block><N>
        m = re.match(r"^([a-zA-Z]['pP]?)[-_]?0*(\d+)$", s, re.IGNORECASE)

    if not m:
        return None

    raw_block = m.group(1).upper()
    num = int(m.group(2))

    if raw_block.endswith("'"):
        block_key = raw_block[:-1].lower() + "p"
        block_display = raw_block
    elif len(raw_block) > 1 and raw_block.endswith("P"):
        block_key = raw_block.lower()
        block_display = raw_block[:-1] + "'"
    else:
        block_key = raw_block.lower()
        block_display = raw_block

    lot_id = f"mz{block_key}-{num:02d}"
    lot_name = f"Mz {block_display} - Lote {num:02d}"
    return lot_id, lot_name, block_display, num


def find_lot_overlays(script_text: str):
    """Devuelve [(label, lot_id, lot_name, block_display, number, url_relativa)] leyendo script_general.js."""
    lots, no_image = [], []
    for segment in iter_overlay_objects(script_text):
        try:
            overlay = json.loads(segment)
        except ValueError:
            print("  [AVISO] overlay con JSON no legible, se omite")
            continue
        label = (overlay.get("data") or {}).get("label")
        parsed = parse_overlay_label(label)
        if not parsed:
            continue
        try:
            url = overlay["items"][0]["image"]["levels"][0]["url"]
        except (KeyError, IndexError, TypeError):
            no_image.append(label)
            continue
        lots.append((label, *parsed, url))
    return lots, no_image


def make_variant(src_png: Path, dst: Path, rgb) -> None:
    """Mismo poligono, pero con relleno de color. El original trae el relleno casi transparente (alfa 1-2)
    y un borde blanco opaco: el relleno se pinta de `rgb` con FILL_ALPHA y el borde se conserva."""
    base = Image.open(src_png).convert("RGBA")
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    src_px, out_px = base.load(), out.load()
    for y in range(base.size[1]):
        for x in range(base.size[0]):
            r, g, b, a = src_px[x, y]
            if a >= BORDER_MIN_ALPHA:
                out_px[x, y] = (r, g, b, a)
            elif a > 0:
                out_px[x, y] = rgb + (FILL_ALPHA,)
    out.save(dst, "WEBP", lossless=True, quality=100, method=6)


def load_catalog() -> List[dict]:
    """Catalogo Mz M: 30 lotes (LM1-V ... LM30-V). Area y precio salen del Excel; los que no estan van con 0."""
    from openpyxl import load_workbook

    data = {}
    if EXCEL.is_file():
        ws = load_workbook(EXCEL, data_only=True).worksheets[0]
        for row in ws.iter_rows(values_only=True):
            manzana, lote, area, price = (list(row) + [None] * 4)[:4]
            if str(manzana).strip().upper() == BLOCK.upper() and isinstance(lote, (int, float)):
                data[int(lote)] = (float(area or 0), float(price or 0))
    else:
        print(f"  [AVISO] No existe el Excel {EXCEL}: area y precio quedan en 0")
    catalog = []
    for n in range(1, TOTAL_LOTS + 1):
        area, price = data.get(n, (0.0, 0.0))
        catalog.append({
            "id": f"mz{BLOCK}-{n:02d}",
            "name": f"Mz {BLOCK.upper()} - Lote {n:02d}",
            "area": round(area, 2),
            "price": round(price, 2),
        })
    extra = sorted(set(data) - set(range(1, TOTAL_LOTS + 1)))
    if extra:
        print(f"  [AVISO] lotes del Excel fuera de 1..{TOTAL_LOTS}: {extra}")
    print(f"  catalogo: {len(catalog)} lotes, {len(data)} con datos del Excel")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="carpeta web/ exportada por 3DVista")
    parser.add_argument("--skip-copy", action="store_true", help="no copiar el export, solo regenerar datos e imagenes")
    parser.add_argument("--regen-variants", action="store_true", help="regenerar todas las imagenes dorada/verde oscura aunque esten vigentes (tras cambiar COLORS)")
    args = parser.parse_args()

    print("== Paso 1: copiar export ==")
    if args.skip_copy:
        print("  (omitido)")
    else:
        print(f"  origen: {args.src}")
        src = resolve_export(args.src)
        print(f"  archivos copiados/actualizados: {copy_export(src)}")
        print(f"  archivos obsoletos borrados de tour/: {prune_tour(src)}")

    print("== Paso 2: puente en tour/index.htm ==")
    print(f"  {inject_bridge()}")
    warn_if_unlicensed()

    print("== Paso 3: detectar lotes en script_general.js ==")
    script = (TOUR / "script_general.js").read_text(encoding="utf-8")
    found, no_image = find_lot_overlays(script)
    if no_image:
        print(f"  [AVISO] overlays de lote sin imagen .webp: {no_image}")

    by_label = {}
    for label, lid, lname, bdisp, num, url in found:
        if label in by_label:
            print(f"  [AVISO] etiqueta duplicada {label}: se conserva la primera")
            continue
        by_label[label] = (lid, lname, bdisp, num, url)

    rows = sorted(by_label.items(), key=lambda kv: (kv[1][2], kv[1][3]))
    print(f"  overlays de lote detectados en el tour: {len(rows)}")

    print("== Paso 4: generar imagenes disponible / reservado / vendido ==")
    media = TOUR / "media"
    wanted = set()
    generated = 0
    for label, (lid, lname, bdisp, num, url) in rows:
        base_path = TOUR / url
        if not base_path.is_file():
            sys.exit(f"[ERROR] Falta la imagen {base_path}")
        for state, rgb in COLORS.items():
            dst = base_path.with_name(base_path.stem + f"_{state}.webp")
            wanted.add(dst.name)
            if not args.regen_variants and dst.exists() and dst.stat().st_mtime >= base_path.stat().st_mtime:
                continue
            make_variant(base_path, dst, rgb)
            generated += 1
    stale = [p for p in media.glob("*.webp") if VARIANT_RE.search(p.name) and p.name not in wanted]
    for p in stale:
        p.unlink()
    print(f"  generadas: {generated}  | ya vigentes: {len(wanted) - generated}  | obsoletas borradas: {len(stale)}")

    print("== Paso 5: escribir crm/lots.js y tour/lots-map.json ==")
    lots_map = {}
    lot_to_label = {}
    for label, (lid, lname, bdisp, num, url) in rows:
        base = Path(url)
        lots_map[label] = {
            "id": lid,
            "base": url,
            "disponible": f"{base.parent.as_posix()}/{base.stem}_disponible.webp",
            "reservado": f"{base.parent.as_posix()}/{base.stem}_reservado.webp",
            "vendido": f"{base.parent.as_posix()}/{base.stem}_vendido.webp",
        }
        if lid not in lot_to_label:
            lot_to_label[lid] = label

    # Base: catálogo de Mz M (Excel) o los detectados
    catalog = load_catalog()
    if catalog:
        lots = []
        for item in catalog:
            entry = dict(item)
            if entry["id"] in lot_to_label:
                entry["label"] = lot_to_label[entry["id"]]
            lots.append(entry)
    else:
        # Fallback si no hay el Excel
        lots = []
        seen = set()
        for label, (lid, lname, bdisp, num, url) in rows:
            if lid not in seen:
                lots.append({"id": lid, "name": lname, "label": label})
                seen.add(lid)

    LOTS_JS.parent.mkdir(parents=True, exist_ok=True)
    body = ",\n".join("  " + json.dumps(l, ensure_ascii=False) for l in lots)
    LOTS_JS.write_text(
        "// GENERADO por tools/sync_tour.py - no editar a mano.\n"
        f"// {len(lots)} lotes registrados (Mz M de Paraiso del Rio; area y precio del Excel).\n"
        f"export const LOTS = [\n{body}\n];\n",
        encoding="utf-8",
    )
    LOTS_MAP.write_text(json.dumps(lots_map, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nListo: {len(lots)} lotes -> crm/lots.js, {len(lots_map)} overlays -> tour/lots-map.json")


if __name__ == "__main__":
    main()
