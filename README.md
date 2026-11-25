# Paraíso del Río - Plano 360° con estados de lotes

Plano 360° (tour de 3DVista) incrustado en un CRM con login. Cada lote se ve **verde** `#10b981` (disponible), **ámbar** `#f59e0b` (reservado)
o **rojo** `#ef4444` (vendido), y lo controlan los asesores desde el CRM. Clon de `garden-beach-360` con su propia base de datos.

- Base de datos: proyecto Firebase **`paraiso-del-rio-605e3`** (propio, no compartido). Colecciones: `lotes`, `config/public`, `usuarios`.
- Hosting: SiteGround (`360paraiso.cautivamarketing.com`, producción) y Vercel (preview interno). Mismo código y misma base de datos.
- Moneda: `$` (editable en Configuración del CRM).

```
index.html, manifest.json, img/   shell del CRM (PWA). img/ sale de 3D/Paraiso del Rio/logo.jpeg (logo.jpeg, logo-panel.jpg, icon-192/512.png)
crm/app.jsx  ->  crm/app.js       CRM (React). app.js es el compilado; app.jsx es el código fuente
crm/lots.js                       GENERADO: 30 lotes de la Mz M (LM1-V ... LM30-V), con área y precio del Excel
crm/firebase-config.js            config web del proyecto Firebase
tour/                             export de 3DVista + tour/crm-bridge.js (pinta los estados en vivo)
tools/sync_tour.py                copia el export de 3DVista y genera lotes e imágenes verde/ámbar/rojo
tools/seed_lots.mjs               carga lotes (Excel) y config en Firestore
tools/create_admin.mjs            crea el primer admin (Auth + usuarios/{uid}) y le envía el correo para su contraseña
tools/build_zip.py                genera dist/360paraiso.zip para SiteGround (se niega si el tour no tiene licencia)
firestore.rules, firebase.json    reglas de seguridad de Firestore
```

## Cómo funciona el color de cada lote
Cada lote del tour es un polígono con etiqueta `LM<n>-V` (→ id `mzm-<nn>`). En el export el polígono es **invisible** (relleno con alfa 1), así que
`sync_tour.py` genera tres imágenes por lote (`_disponible`, `_reservado`, `_vendido`: relleno de color + borde blanco original).
`tour/crm-bridge.js` recibe el estado desde el CRM (`update_lots`) y cambia la imagen del polígono en vivo.
**No se modifica `script.js` ni `script_general.js`** del export: lo único que se toca es una línea en `tour/index.htm` que carga `crm-bridge.js`.

## Datos de los lotes (Excel)
`3D/Paraiso del Rio/Lotes_Manzana_M.xlsx` trae 21 lotes con área y precio (M-2, 4 al 19, 22 al 25). Los otros 9 polígonos del tour
(M-1, 3, 20, 21, 26 al 30) se crean **disponibles, sin área ni precio**: complétalos desde el CRM (Lista de lotes → editar).
Si cambia el Excel: `python tools/sync_tour.py --skip-copy` y luego `node tools/seed_lots.mjs --account <correo> --force` (el `--force` sobrescribe precio y área).

## Capas del plano (botón del ojo)
Los overlays con tag son capas (Educación, Comunal, Recreación, Mz-A…Mz-L y **Letreros**; el tag `LetrerosM` de 3DVista se renombra a `letreros` en `crm-bridge.js`).
`crm-bridge.js` además agrupa cada letrero de manzana con la capa de su manzana, así que al apagar una manzana se ocultan su polígono y su letrero,
y el switch **Letreros** oculta solo los letreros. Los letreros se asocian a su manzana por su **imagen** (tabla `SIGN_IMAGE_BLOCK`), porque sus etiquetas en 3DVista
están duplicadas (varios dicen `MZD`/`MZE`). También crea la capa **Mz-M** (polígono `MZ M`, números `MZ M - Numeros` y letrero `MZM`).
Si se re-exporta y cambian los recursos `res_…` de los letreros, actualiza esa tabla (o corrige las etiquetas en 3DVista a `MZF`…`MZL`). No hace falta tocar los tags en 3DVista.

## Re-exportar desde 3DVista (cuando cambies el tour)
1. Exporta **desde el 3DVista con licencia** (un export sin licencia trae marca de agua y `sync_tour.py` / `build_zip.py` lo detectan).
2. Deja el resultado en `3D/Paraiso del Rio/paraiso` (o en su subcarpeta `web/`, se detecta sola; o pasa `--src`). `project.vtp` y `hotspots/` se ignoran.
3. `python tools/sync_tour.py` (necesita Python con `pillow` y `openpyxl`). Es seguro repetirlo.
4. Si cambió la lista de lotes, `node tools/seed_lots.mjs --account <correo>` (crea los nuevos sin tocar los existentes).

## Compilar el CRM (tras editar `crm/app.jsx`)
```bash
npm install       # una sola vez
npm run build     # compila crm/app.jsx -> crm/app.js
```

## Ver en local
```bash
npm run dev       # http://localhost:8083
```
Abre **`http://localhost:8083`** (con `localhost`, no `127.0.0.1`: Firebase Auth autoriza `localhost` por defecto).
Usa la base real de Firebase: lo que cambies como admin/asesor queda guardado de verdad.

## Puesta en marcha de Firebase
Todos los scripts usan la sesión de la Firebase CLI de la cuenta dueña del proyecto: `npx firebase-tools login:add`.
1. **Firestore** debe existir (Console → Firestore Database → Crear base de datos, o `npx firebase-tools firestore:databases:create "(default)" --location southamerica-east1`).
2. **Authentication** → Sign-in method → habilitar **Correo/contraseña**.
3. **Reglas:** `npx firebase-tools deploy --only firestore:rules --project paraiso-del-rio-605e3 --account <correo>`
4. **Dominios autorizados** (Authentication → Settings): `360paraiso.cautivamarketing.com` y el dominio de Vercel.
5. `node tools/seed_lots.mjs --account <correo>` (30 lotes + `config/public`).
6. `node tools/create_admin.mjs --account <correo> --email <correo-admin>` (llega un correo para poner la contraseña).

## Publicar en SiteGround (`360paraiso.cautivamarketing.com`) - producción
1. `python tools/sync_tour.py` y `npm run build`.
2. `python tools/build_zip.py` → `dist/360paraiso.zip` (los archivos van directo en la raíz del zip).
3. SiteGround → Site Tools → **Domain → Subdomains**: crea `360paraiso`. Instala el SSL (**Security → SSL Manager**, Let's Encrypt) **antes** de subir: el `.htaccess` obliga a https.
4. **File Manager** → `360paraiso.cautivamarketing.com/public_html` → **Upload** `360paraiso.zip` → clic derecho → **Extract**.
5. Borra el zip del servidor. Si ves contenido viejo: Site Tools → Speed → Caching → **Flush Cache**.
