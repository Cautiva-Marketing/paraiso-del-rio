#!/usr/bin/env node
/**
 * tools/create_admin.mjs
 *
 * Crea (si no existe) el usuario de Firebase Authentication con el correo indicado, escribe su perfil
 * usuarios/{uid} = { role: 'admin', ... } y le envía el correo de "restablecer contraseña" para que ponga su clave.
 *
 * Uso:
 *   node tools/create_admin.mjs --account ticautivamarketing@gmail.com --email ticautivamarketing@gmail.com [--name "Admin"]
 */
import crypto from 'crypto';
import {
  PROJECT_ID, API_KEY, FIRESTORE_BASE, accountArg, getToken, fetchJson, toFirestoreFields,
} from './_firebase.mjs';

const arg = (name) => { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : null; };

async function main() {
  const email = (arg('--email') || '').trim().toLowerCase();
  const name = arg('--name') || 'Administrador';
  if (!email) throw new Error('Falta --email');

  const headers = { Authorization: `Bearer ${getToken(accountArg())}`, 'Content-Type': 'application/json' };
  const idt = `https://identitytoolkit.googleapis.com/v1/projects/${PROJECT_ID}`;

  // 1. Buscar o crear el usuario de Authentication
  let uid;
  const found = await fetchJson(`${idt}/accounts:lookup`, { method: 'POST', headers, body: JSON.stringify({ email: [email] }) });
  if (found.users && found.users.length) {
    uid = found.users[0].localId;
    console.log(`Usuario de Authentication ya existe: ${uid}`);
  } else {
    const password = crypto.randomBytes(18).toString('base64url'); // temporal: se reemplaza con el correo de restablecimiento
    const created = await fetchJson(`${idt}/accounts`, { method: 'POST', headers, body: JSON.stringify({ email, password, emailVerified: true, displayName: name }) });
    uid = created.localId;
    console.log(`Usuario de Authentication creado: ${uid}`);
  }

  // 2. Perfil admin en Firestore (usuarios/{uid})
  await fetchJson(`${FIRESTORE_BASE}/usuarios/${uid}`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ fields: toFirestoreFields({ role: 'admin', name, email, color: '#8b5cf6', active: true }) }),
  });
  console.log(`Perfil usuarios/${uid} escrito (role: admin)`);

  // 3. Correo para que el admin ponga su contraseña
  await fetchJson(`https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=${API_KEY}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ requestType: 'PASSWORD_RESET', email }),
  });
  console.log(`Correo de restablecimiento de contraseña enviado a ${email}`);
}

main().catch(err => { console.error('\n[ERROR]', err.message || err); process.exit(1); });
