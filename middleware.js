import { next, rewrite } from '@vercel/functions';

function redirect(location, status = 302) {
  return new Response(null, {
    status,
    headers: {
      Location: location
    }
  });
}

const BETA_PATH =
  '/beta-404b87eaa6a7b90cc88f57111d565a25';

const ACCESS_COOKIE =
  '__Secure-prospectors_access';

function getCookie(request, name) {
  const header = request.headers.get('cookie') || '';

  for (const pair of header.split(';')) {
    const separator = pair.indexOf('=');

    if (separator === -1) continue;

    const key = pair.slice(0, separator).trim();
    const value = pair.slice(separator + 1).trim();

    if (key === name) {
      return value;
    }
  }

  return '';
}

function base64UrlToBytes(value) {
  const normalized = value
    .replace(/-/g, '+')
    .replace(/_/g, '/');

  const padding =
    '='.repeat((4 - normalized.length % 4) % 4);

  const binary = atob(normalized + padding);

  return Uint8Array.from(
    binary,
    character => character.charCodeAt(0)
  );
}

function decodePayload(value) {
  const bytes = base64UrlToBytes(value);
  const text = new TextDecoder().decode(bytes);

  return JSON.parse(text);
}

async function verifyAccessCookie(value) {
  try {
    const secret =
      process.env.ACCESS_COOKIE_SECRET;

    if (!secret || !value) {
      return false;
    }

    const pieces = value.split('.');

    if (pieces.length !== 2) {
      return false;
    }

    const [payload, suppliedSignature] = pieces;

    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(secret),
      {
        name: 'HMAC',
        hash: 'SHA-256'
      },
      false,
      ['verify']
    );

    const validSignature =
      await crypto.subtle.verify(
        'HMAC',
        key,
        base64UrlToBytes(suppliedSignature),
        new TextEncoder().encode(payload)
      );

    if (!validSignature) {
      return false;
    }

    const data = decodePayload(payload);

    if (data.map !== 'prospectors') {
      return false;
    }

    if (
      !Number.isFinite(data.expires) ||
      data.expires <= Math.floor(Date.now() / 1000)
    ) {
      return false;
    }

    if (!data.userId) {
      return false;
    }

    return true;

  } catch {
    return false;
  }
}

function isProspectorsHost(hostname) {
  return (
    hostname === 'prospectors.americanexplorationmaps.com' ||
    hostname.endsWith('.vercel.app')
  );
}

function loginRedirect(request, returnPath) {
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

  return redirect(hubUrl.toString(), 302);
}

export default async function middleware(request) {
  const url = new URL(request.url);
  const pathname = url.pathname;
  const hostname =
    (request.headers.get('host') || '')
      .split(':')[0]
      .toLowerCase();

  /*
   * Do not interfere with authentication endpoints,
   * the login page, or unrelated site files.
   */
  if (
    pathname.startsWith('/api/auth/') ||
    pathname === '/favicon.ico'
  ) {
    return next();
  }

  const prospectorsHost =
    isProspectorsHost(hostname);

  const cleanProspectorsRoot =
    prospectorsHost &&
    pathname === '/';

  const betaRequest =
    pathname === BETA_PATH ||
    pathname.startsWith(BETA_PATH + '/');

  const cleanMapAsset =
    prospectorsHost &&
    (
      pathname.startsWith('/data/') ||
      pathname.startsWith('/vendor/') ||
      /^\/map\.[a-f0-9]+\.js$/.test(pathname) ||
      /^\/map\.[a-f0-9]+\.css$/.test(pathname) ||
      /^\/styles\.[a-f0-9]+\.css$/.test(pathname)
    );

  if (
    !cleanProspectorsRoot &&
    !betaRequest &&
    !cleanMapAsset
  ) {
    return next();
  }

  /*
   * Temporary Preview-only bypass:
   * Vercel Preview deployments open without map sign-in.
   * Production continues to require a valid account session.
   */
  const previewBypass = false;

  const accessToken =
    getCookie(request, ACCESS_COOKIE);

  const authorized =
    previewBypass ||
    await verifyAccessCookie(accessToken);

  /*
   * A request to the clean Prospectors root first
   * obtains/refreshes map authorization.
   */
  if (cleanProspectorsRoot) {
    if (!authorized) {
      const authUrl = new URL(
        '/api/auth/authorize',
        request.url
      );

      authUrl.searchParams.set(
        'return',
        '/'
      );

      return redirect(
        authUrl.toString(),
        302
      );
    }

    const destination =
      new URL(
        BETA_PATH + '/',
        request.url
      );

    /*
     * Internal rewrite:
     *
     * Browser displays:
     * prospectors.americanexplorationmaps.com/
     *
     * Vercel serves:
     * /beta-404.../
     */
    return rewrite(destination.toString());
  }

  /*
   * Clean-root map assets are also protected.
   * Their visible URL stays clean while Vercel
   * serves the existing file from BETA_PATH.
   */
  if (cleanMapAsset) {
    if (!authorized) {
      return loginRedirect(
        request,
        pathname + url.search
      );
    }

    const destination =
      new URL(
        BETA_PATH + pathname,
        request.url
      );

    destination.search = url.search;

    return rewrite(destination.toString());
  }

  /*
   * Direct access to the old beta path remains
   * available as our fallback, but it is protected.
   */
  if (!authorized) {
    return loginRedirect(
      request,
      pathname + url.search
    );
  }

  return next();
}

export const config = {
  matcher: [
    '/',
    '/data/:path*',
    '/vendor/:path*',
    '/map.:path*.js',
    '/map.:path*.css',
    '/styles.:path*.css',
    '/beta-404b87eaa6a7b90cc88f57111d565a25/:path*'
  ]
};
