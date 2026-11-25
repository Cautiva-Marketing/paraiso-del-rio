// Utilidades compartidas por los scripts de tools/ (sin dependencias: Node 18+).
// Usan el token de la Firebase CLI (npx firebase-tools login / login:add) para hablar con las APIs REST de Google.
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

export const PROJECT_ID = 'paraiso-del-rio-605e3';
export const API_KEY = 'AIzaSyCs-DnaEVYyqsOesT9_Li4PbqQi10mV-Hw'; // apiKey web (no es secreta)
export const FIRESTORE_BASE = `https://firestore.googleapis.com/v1/projects/${PROJECT_ID}/databases/(default)/documents`;
export const DOC_PATH = `projects/${PROJECT_ID}/databases/(default)/documents`;

/** Lee `--account correo@x.com` de los argumentos (o null). */
export function accountArg() {
  const i = process.argv.indexOf('--account');
  return i >= 0 ? process.argv[i + 1] : null;
}

function readConfig() {
  const configPath = path.join(os.homedir(), '.config', 'configstore', 'firebase-tools.json');
  if (!fs.existsSync(configPath)) throw new Error(`No hay configuración de Firebase CLI en ${configPath}. Ejecuta 'npx firebase-tools login'.`);
  return JSON.parse(fs.readFileSync(configPath, 'utf8'));
}

function pickTokens(config, account) {
  if (!account) return config.tokens;
  if (config.user && config.user.email === account) return config.tokens;
  const extra = (config.additionalAccounts || []).find(a => a.user && a.user.email === account);
  if (!extra) throw new Error(`La cuenta ${account} no está en la Firebase CLI. Ejecuta: npx firebase-tools login:add`);
  return extra.tokens;
}

/** Devuelve un access_token vigente de la cuenta indicada (refrescándolo con la CLI si hace falta). */
export function getToken(account) {
  let tokens = pickTokens(readConfig(), account);
  if (!tokens || !tokens.access_token) throw new Error('No hay tokens de acceso en firebase-tools.json.');
  if (tokens.expires_at && tokens.expires_at < Date.now() + 60_000) {
    // Cualquier comando de la CLI refresca el token y lo guarda en el configstore.
    const args = ['--yes', 'firebase-tools', 'projects:list'];
    if (account) args.push('--account', account);
    execFileSync(process.platform === 'win32' ? 'npx.cmd' : 'npx', args, { stdio: 'ignore', shell: process.platform === 'win32' });
    tokens = pickTokens(readConfig(), account);
  }
  return tokens.access_token;
}

export async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = data.error ? (data.error.message || JSON.stringify(data.error)) : JSON.stringify(data);
    const err = new Error(`HTTP ${res.status}: ${msg}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export function toFirestoreValue(val) {
  if (val === null || val === undefined) return { nullValue: null };
  if (typeof val === 'boolean') return { booleanValue: val };
  if (typeof val === 'number') return Number.isInteger(val) ? { integerValue: String(val) } : { doubleValue: val };
  if (typeof val === 'string') return { stringValue: val };
  if (Array.isArray(val)) return { arrayValue: { values: val.map(toFirestoreValue) } };
  if (typeof val === 'object') {
    const fields = {};
    for (const [k, v] of Object.entries(val)) fields[k] = toFirestoreValue(v);
    return { mapValue: { fields } };
  }
  return { stringValue: String(val) };
}

export function toFirestoreFields(obj) {
  const fields = {};
  for (const [k, v] of Object.entries(obj)) fields[k] = toFirestoreValue(v);
  return fields;
}

export function fromFirestoreValue(v) {
  if (!v) return null;
  if ('stringValue' in v) return v.stringValue;
  if ('integerValue' in v) return Number(v.integerValue);
  if ('doubleValue' in v) return v.doubleValue;
  if ('booleanValue' in v) return v.booleanValue;
  if ('nullValue' in v) return null;
  if ('arrayValue' in v) return (v.arrayValue.values || []).map(fromFirestoreValue);
  if ('mapValue' in v) return Object.fromEntries(Object.entries(v.mapValue.fields || {}).map(([k, x]) => [k, fromFirestoreValue(x)]));
  return null;
}

export function fromFirestoreDoc(doc) {
  return Object.fromEntries(Object.entries(doc.fields || {}).map(([k, v]) => [k, fromFirestoreValue(v)]));
}
