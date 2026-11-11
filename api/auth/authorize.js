import { createHmac } from 'node:crypto';
import { neon } from '@neondatabase/serverless';

import {
  SESSION_COOKIE,
  ACCESS_COOKIE,
  readCookie,
  hashToken,
  createAccessPayload,
  accessCookie,
  clearAccessCookie,
  clearSessionCookie,
  mapSubscriptionsRequired
} from '../../lib/auth.js';

function safeReturnPath(value) {
  if (
    typeof value !== 'string' ||
    !value.startsWith('/') ||
    value.startsWith('//')
  ) {
    return '/';
  }

  return value;
}

function encode(value) {
  return Buffer
    .from(JSON.stringify(value))
    .toString('base64url');
}

function sign(payload, secret) {
  return createHmac('sha256', secret)
    .update(payload)
    .digest('base64url');
}

function redirect(res, location, cookies = []) {
  res.statusCode = 302;
  res.setHeader('Location', location);
  res.setHeader('Cache-Control', 'no-store');

  if (cookies.length) {
    res.setHeader('Set-Cookie', cookies);
  }

  res.end();
}

function hubLoginUrl(returnPath) {
  const returnUrl = new URL(
    returnPath,
    'https://prospectors.americanexplorationmaps.com'
  );

  const hubUrl = new URL(
    'https://americanexplorationmaps.com/'
  );

  hubUrl.searchParams.set(
    'return',
    returnUrl.toString()
  );

  return hubUrl.toString();
}

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    res.statusCode = 405;
    res.setHeader('Allow', 'GET');
    res.end('Method Not Allowed');
    return;
  }

  const returnPath =
    safeReturnPath(req.query?.return || '/');

  const sessionToken =
    readCookie(
      req.headers.cookie || '',
      SESSION_COOKIE
    );

  if (!sessionToken) {
    redirect(
      res,
      hubLoginUrl(returnPath),
      [clearAccessCookie()]
    );
    return;
  }

  const databaseUrl =
    process.env.DATABASE_URL ||
    process.env.POSTGRES_URL;

  const accessSecret =
    process.env.ACCESS_COOKIE_SECRET;

  if (!databaseUrl || !accessSecret) {
    res.statusCode = 500;
    res.end('Authentication configuration unavailable');
    return;
  }

  try {
    const sql = neon(databaseUrl);
    const tokenHash = hashToken(sessionToken);

    const rows = await sql`
      SELECT
        s.user_id,
        s.expires_at,
        s.revoked_at,
        u.status AS user_status,
        e.status AS entitlement_status,
        e.starts_at,
        e.expires_at AS entitlement_expires_at
      FROM sessions s
      JOIN users u
        ON u.id = s.user_id
      LEFT JOIN map_entitlements e
        ON e.user_id = s.user_id
       AND e.map_slug = 'prospectors'
      WHERE s.token_hash = ${tokenHash}
      LIMIT 1
    `;

    const row = rows[0];
    const now = new Date();

    const validSession =
      row &&
      !row.revoked_at &&
      new Date(row.expires_at) > now &&
      row.user_status === 'active';

    if (!validSession) {
      redirect(
        res,
        hubLoginUrl(returnPath),
        [
          clearSessionCookie(),
          clearAccessCookie()
        ]
      );
      return;
    }

    const validEntitlement =
      row.entitlement_status === 'active' &&
      new Date(row.starts_at) <= now &&
      (
        !row.entitlement_expires_at ||
        new Date(row.entitlement_expires_at) > now
      );

    if (mapSubscriptionsRequired() && !validEntitlement) {
      res.statusCode = 403;
      res.setHeader(
        'Set-Cookie',
        clearAccessCookie()
      );
      res.end('Prospectors access is not active.');
      return;
    }

    const accessPayload =
      encode(createAccessPayload(row.user_id));

    const accessToken =
      accessPayload +
      '.' +
      sign(accessPayload, accessSecret);

    await sql`
      UPDATE sessions
      SET last_seen_at = NOW()
      WHERE token_hash = ${tokenHash}
    `;

    redirect(
      res,
      returnPath,
      [accessCookie(accessToken)]
    );

  } catch (error) {
    console.error('Authorize error:', error);
    res.statusCode = 500;
    res.end('Unable to authorize map access');
  }
}
