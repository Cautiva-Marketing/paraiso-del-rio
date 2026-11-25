#!/usr/bin/env node
/**
 * tools/seed_lots.mjs
 *
 * Lee `crm/lots.js` (generado por sync_tour.py desde el Excel) y deja en Firestore (proyecto paraiso-del-rio-605e3):
 *   - lotes/{id}      un documento por lote (id, name, area, price, status, color, asesor, asesorUid)
 *   - config/public   configuración inicial (solo si no existe)
 *
 * No pisa el estado (status/color/asesor) de lotes que ya existan. Tampoco el precio/área si ya los editaste
 * en el CRM, salvo que pases --force.
 *
 * Uso:
 *   node tools/seed_lots.mjs --account ticautivamarketing@gmail.com [--force]
 */
import { LOTS } from '../crm/lots.js';
import {
  PROJECT_ID, FIRESTORE_BASE, DOC_PATH, accountArg, getToken, fetchJson,
  toFirestoreFields, fromFirestoreDoc,
} from './_firebase.mjs';

const FORCE = process.argv.includes('--force');

const STATUS_CONFIG = {
  disponible: { id: 'disponible', label: 'Disponible', color: '#10b981', isBlocked: false },
  reservado: { id: 'reservado', label: 'Reservado', color: '#f59e0b', isBlocked: false },
  vendido: { id: 'vendido', label: 'Vendido', color: '#ef4444', isBlocked: false },
};

async function listAll(headers, collection) {
  const docs = new Map();
  let pageToken = '';
  do {
    const res = await fetchJson(`${FIRESTORE_BASE}/${collection}?pageSize=300${pageToken ? `&pageToken=${pageToken}` : ''}`, { headers });
    for (const d of res.documents || []) docs.set(d.name.split('/').pop(), fromFirestoreDoc(d));
    pageToken = res.nextPageToken || '';
  } while (pageToken);
  return docs;
}

async function main() {
  const account = accountArg();
  console.log(`== Sembrado de lotes de Paraíso del Río en Firestore (${PROJECT_ID}) ==`);
  console.log(`Lotes en crm/lots.js: ${LOTS.length}${FORCE ? '  (--force: se sobrescriben precio y área)' : ''}`);

  const headers = { Authorization: `Bearer ${getToken(account)}`, 'Content-Type': 'application/json' };

  console.log('\n[1/3] Leyendo lotes existentes...');
  const existing = await listAll(headers, 'lotes');
  console.log(`  Documentos existentes en lotes: ${existing.size}`);

  console.log('\n[2/3] Escribiendo...');
  const writes = [];
  let created = 0, updated = 0;
  for (const lot of LOTS) {
    const prev = existing.get(lot.id);
    const data = {
      id: lot.id,
      name: lot.name,
      area: Number(lot.area) || 0,
      price: Number(lot.price) || 0,
      status: 'disponible',
      color: STATUS_CONFIG.disponible.color,
      asesor: '',
      asesorUid: null,
    };
    if (prev) {
      data.status = prev.status || 'disponible';
      data.color = prev.color || data.color;
      data.asesor = prev.asesor || '';
      data.asesorUid = prev.asesorUid ?? null;
      if (!FORCE) {
        if (prev.price) data.price = prev.price;
        if (prev.area) data.area = prev.area;
      }
      updated++;
    } else {
      created++;
    }
    writes.push({ update: { name: `${DOC_PATH}/lotes/${lot.id}`, fields: toFirestoreFields(data) } });
  }

  let configNote = 'ya existía (no se toca)';
  const hasConfig = await fetchJson(`${FIRESTORE_BASE}/config/public`, { headers }).then(() => true).catch(e => { if (e.status === 404) return false; throw e; });
  if (!hasConfig || FORCE) {
    writes.push({
      update: {
        name: `${DOC_PATH}/config/public`,
        fields: toFirestoreFields({
          appName: 'Plano 360° - Paraíso del Río',
          appIcon: 'img/icon-512.png',
          whatsapp: '',
          phone: '',
          currency: '$',
          hidePrice: false,
          showTourInfoPanel: false,
          statusConfig: STATUS_CONFIG,
          layerNames: {},
        }),
      },
    });
    configNote = 'creado';
  }

  console.log(`  ${created} lotes nuevos, ${updated} actualizados, config/public ${configNote}`);
  for (let i = 0; i < writes.length; i += 400) {
    await fetchJson(`${FIRESTORE_BASE}:commit`, { method: 'POST', headers, body: JSON.stringify({ writes: writes.slice(i, i + 400) }) });
  }

  console.log('\n[3/3] Verificación...');
  const after = await listAll(headers, 'lotes');
  const cfg = fromFirestoreDoc(await fetchJson(`${FIRESTORE_BASE}/config/public`, { headers }));
  const withPrice = [...after.values()].filter(l => l.price > 0).length;
  console.log(`  lotes: ${after.size} (esperados ${LOTS.length}), con precio: ${withPrice}`);
  console.log(`  config/public: appName="${cfg.appName}", currency="${cfg.currency}"`);
  if (after.size < LOTS.length) process.exit(1);
  console.log('\n¡Sembrado exitoso!');
}

main().catch(err => { console.error('\n[ERROR]', err.message || err); process.exit(1); });
