import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { minify } from 'terser';

const BETA_PATH = 'beta-404b87eaa6a7b90cc88f57111d565a25';
const publicDirectory = join(process.cwd(), 'public');
const betaDirectory = join(publicDirectory, BETA_PATH);

mkdirSync(betaDirectory, { recursive: true });

const sourceDist = join(process.cwd(), 'source-dist');
const copies = [
  ['vendor', 'vendor'],
  ['data/geology', 'data/geology'],
];

for (const [source, destination] of copies) {
  // Add missing source assets, but keep every existing protected/static file.
  cpSync(join(sourceDist, source), join(betaDirectory, destination), {
    recursive: true,
    force: false,
    errorOnExist: false
  });
}

const applicationSource = readFileSync(join(sourceDist, 'app.js'), 'utf8')
;
const minified = await minify(applicationSource, {
  compress: { passes: 2 },
  mangle: true,
  sourceMap: false,
  format: { comments: false }
});

if (!minified.code) throw new Error('The protected browser build was empty.');

const applicationHash = createHash('sha256').update(minified.code).digest('hex').slice(0, 12);
const stylesheet = readFileSync(join(sourceDist, 'styles.css'), 'utf8');
const stylesheetHash = createHash('sha256').update(stylesheet).digest('hex').slice(0, 12);
const applicationName = `map.${applicationHash}.js`;
const stylesheetName = `map.${stylesheetHash}.css`;

for (const [name, contents] of [[applicationName, minified.code], [stylesheetName, stylesheet]]) {
  const output = join(betaDirectory, name);
  if (existsSync(output) && readFileSync(output, 'utf8') !== contents) {
    throw new Error(`Refusing to overwrite existing hashed asset with different content: ${name}`);
  }
  if (!existsSync(output)) writeFileSync(output, contents, { flag: 'wx' });
}

const documentSource = readFileSync(join(sourceDist, 'index.html'), 'utf8')
  .replace('./app.js', `./${applicationName}`)
  .replace('./styles.css', `./${stylesheetName}`)
  .replace(
    '<meta name="description"',
    '<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">\n  <meta name="description"'
  );

writeFileSync(join(betaDirectory, 'index.html'), documentSource);

const notFoundPath = join(publicDirectory, 'index.html');
if (!existsSync(notFoundPath)) {
  writeFileSync(
    notFoundPath,
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow,noarchive,nosnippet"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Not found</title></head><body><main><h1>Not found</h1></main></body></html>',
    { flag: 'wx' }
  );
}
const robotsPath = join(publicDirectory, 'robots.txt');
if (!existsSync(robotsPath)) {
  writeFileSync(robotsPath, 'User-agent: *\nDisallow: /\n', { flag: 'wx' });
}
