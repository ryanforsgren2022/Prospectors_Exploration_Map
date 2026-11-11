import { neon } from '@neondatabase/serverless';
import {
  hashPassword,
  normalizeEmail
} from '../lib/auth.js';

const email = normalizeEmail(process.env.AEM_EMAIL || '');
const password = process.env.AEM_PASSWORD || '';

if (!email || !password) {
  console.error('Email and password are required.');
  process.exit(1);
}

if (password.length < 12) {
  console.error('Password must be at least 12 characters.');
  process.exit(1);
}

const connection =
  process.env.DATABASE_URL ||
  process.env.POSTGRES_URL;

if (!connection) {
  console.error('Database connection is unavailable.');
  process.exit(1);
}

const sql = neon(connection);

const existing = await sql`
  SELECT id
  FROM users
  WHERE LOWER(email) = LOWER(${email})
  LIMIT 1
`;

if (existing.length) {
  console.error('That account already exists. No changes made.');
  process.exit(1);
}

const passwordHash = await hashPassword(password);

const rows = await sql`
  INSERT INTO users (
    email,
    password_hash,
    status
  )
  VALUES (
    ${email},
    ${passwordHash},
    'active'
  )
  RETURNING id
`;

const userId = rows[0].id;

await sql`
  INSERT INTO map_entitlements (
    user_id,
    map_slug,
    status
  )
  VALUES (
    ${userId},
    'prospectors',
    'active'
  )
`;

console.log('✓ Private account created');
console.log('✓ Prospectors access granted');
