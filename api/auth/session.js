import {
  database,
  SESSION_COOKIE,
  readCookie,
  hashToken,
  clearSessionCookie,
  jsonResponse
} from '../../lib/auth.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return jsonResponse(res, 405, {
      ok: false,
      error: 'Method not allowed'
    });
  }

  try {
    const token = readCookie(
      req.headers.cookie || '',
      SESSION_COOKIE
    );

    if (!token) {
      return jsonResponse(res, 401, {
        ok: false,
        authenticated: false
      });
    }

    const sql = database();
    const tokenHash = hashToken(token);

    const sessions = await sql`
      SELECT
        s.id,
        s.user_id,
        s.expires_at,
        s.revoked_at,
        u.email,
        u.status AS user_status
      FROM sessions s
      JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ${tokenHash}
      LIMIT 1
    `;

    const session = sessions[0];

    const valid =
      session &&
      session.user_status === 'active' &&
      session.revoked_at === null &&
      new Date(session.expires_at) > new Date();

    if (!valid) {
      res.setHeader('Set-Cookie', clearSessionCookie());

      return jsonResponse(res, 401, {
        ok: false,
        authenticated: false
      });
    }

    await sql`
      UPDATE sessions
      SET last_seen_at = NOW()
      WHERE id = ${session.id}
    `;

    const entitlements = await sql`
      SELECT map_slug, status, starts_at, expires_at
      FROM map_entitlements
      WHERE user_id = ${session.user_id}
        AND status = 'active'
        AND starts_at <= NOW()
        AND (
          expires_at IS NULL OR
          expires_at > NOW()
        )
    `;

    return jsonResponse(res, 200, {
      ok: true,
      authenticated: true,
      user: {
        email: session.email
      },
      maps: entitlements.map(row => row.map_slug)
    });

  } catch (error) {
    console.error('Session validation error:', error);

    return jsonResponse(res, 500, {
      ok: false,
      error: 'Unable to validate session'
    });
  }
}
