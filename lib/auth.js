import {
  createHash,
  randomBytes,
  scrypt as scryptCallback,
  timingSafeEqual
} from 'node:crypto';
import { promisify } from 'node:util';
import { neon } from '@neondatabase/serverless';

const scrypt = promisify(scryptCallback);

export const SESSION_COOKIE = '__Secure-aem_platform_session';
export const ACCESS_COOKIE = '__Secure-prospectors_access';

const SESSION_LIFETIME_SECONDS = 60 * 60 * 24 * 30;
export const ACCESS_LIFETIME_SECONDS = 60 * 60 * 12;

/* Leave false for temporary free verified-account access.
   Set ENFORCE_MAP_SUBSCRIPTIONS=true in Production later to require entitlements. */
export function mapSubscriptionsRequired() {
  return process.env.VERCEL_ENV === 'production' &&
    process.env.ENFORCE_MAP_SUBSCRIPTIONS === 'true';
}

export function database() {
  const connectionString =
    process.env.DATABASE_URL ||
    process.env.POSTGRES_URL ||
    process.env.NEON_DATABASE_URL;

  if (!connectionString) {
    throw new Error('Database connection environment variable is missing.');
  }

  return neon(connectionString);
}

export function normalizeEmail(value = '') {
  return String(value).trim().toLowerCase();
}

export async function hashPassword(password) {
  const salt = randomBytes(16);
  const derived = await scrypt(String(password), salt, 64);

  return [
    'scrypt',
    salt.toString('base64url'),
    Buffer.from(derived).toString('base64url')
  ].join('$');
}

export async function verifyPassword(password, storedHash) {
  try {
    const [algorithm, saltText, hashText] = String(storedHash).split('$');

    if (algorithm !== 'scrypt' || !saltText || !hashText) return false;

    const expected = Buffer.from(hashText, 'base64url');
    const actual = Buffer.from(
      await scrypt(String(password), Buffer.from(saltText, 'base64url'), expected.length)
    );

    return (
      expected.length === actual.length &&
      timingSafeEqual(expected, actual)
    );
  } catch {
    return false;
  }
}

export function hashToken(token) {
  return createHash('sha256').update(String(token)).digest('hex');
}

export function sessionExpiration() {
  return new Date(Date.now() + SESSION_LIFETIME_SECONDS * 1000);
}

function platformCookieDomain() {
  const value = String(process.env.PLATFORM_COOKIE_DOMAIN || '').trim();
  return value ? `Domain=${value}` : '';
}

export function clearSessionCookie() {
  return [
    `${SESSION_COOKIE}=`,
    'Max-Age=0',
    'Path=/',
    platformCookieDomain(),
    'Secure',
    'HttpOnly',
    'SameSite=Lax'
  ].filter(Boolean).join('; ');
}

export function readCookie(cookieHeader, name) {
  if (!cookieHeader) return '';

  for (const pair of cookieHeader.split(';')) {
    const separator = pair.indexOf('=');
    if (separator === -1) continue;

    if (pair.slice(0, separator).trim() === name) {
      return pair.slice(separator + 1).trim();
    }
  }

  return '';
}

export function jsonResponse(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}


export function createAccessPayload(userId) {
  return {
    userId,
    map: 'prospectors',
    expires:
      Math.floor(Date.now() / 1000) +
      ACCESS_LIFETIME_SECONDS
  };
}

export function accessCookie(value) {
  return [
    `${ACCESS_COOKIE}=${value}`,
    'Path=/',
    'HttpOnly',
    'Secure',
    'SameSite=Lax',
    `Max-Age=${ACCESS_LIFETIME_SECONDS}`
  ].join('; ');
}

export function clearAccessCookie() {
  return [
    `${ACCESS_COOKIE}=`,
    'Path=/',
    'HttpOnly',
    'Secure',
    'SameSite=Lax',
    'Max-Age=0'
  ].join('; ');
}
