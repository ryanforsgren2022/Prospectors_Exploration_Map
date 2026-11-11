import {
  database,
  SESSION_COOKIE,
  readCookie,
  hashToken,
  clearSessionCookie,
  jsonResponse
} from '../../lib/auth.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
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

    if (token) {
      const sql = database();
      const tokenHash = hashToken(token);

      await sql`
        UPDATE sessions
        SET revoked_at = NOW()
        WHERE token_hash = ${tokenHash}
          AND revoked_at IS NULL
      `;
    }

    res.setHeader('Set-Cookie', clearSessionCookie());

    return jsonResponse(res, 200, {
      ok: true
    });

  } catch (error) {
    console.error('Logout error:', error);

    // Clear the browser cookie even if database revocation
    // encounters a temporary problem.
    res.setHeader('Set-Cookie', clearSessionCookie());

    return jsonResponse(res, 200, {
      ok: true
    });
  }
}
