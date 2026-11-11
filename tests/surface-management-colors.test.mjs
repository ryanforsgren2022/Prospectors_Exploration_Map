import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = readFileSync(new URL('../source-dist/app.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('const SURFACE_CATEGORY_COLORS'), source.indexOf('const isMobile')), context);
const expression = vm.runInContext('surfaceManagementColorExpression()', context);
function evaluate(e, properties) {
  if (!Array.isArray(e)) return e;
  const [op, ...args] = e;
  if (op === 'get') return properties[args[0]] ?? null;
  if (op === 'has') return Object.hasOwn(properties, args[0]);
  if (op === '!') return !evaluate(args[0], properties);
  if (op === 'any') return args.some(x => evaluate(x, properties));
  if (op === 'all') return args.every(x => evaluate(x, properties));
  if (op === 'coalesce') return args.map(x => evaluate(x, properties)).find(x => x !== null && x !== undefined) ?? null;
  if (op === 'to-string') return String(evaluate(args[0], properties));
  if (op === 'upcase') return evaluate(args[0], properties).toUpperCase();
  if (op === 'case') return evaluate(evaluate(args[0], properties) ? args[1] : args[2], properties);
  if (op === 'match') {
    const input = evaluate(args[0], properties);
    for (let i = 1; i < args.length - 1; i += 2) {
      if (Array.isArray(args[i]) ? args[i].includes(input) : args[i] === input) return evaluate(args[i + 1], properties);
    }
    return evaluate(args.at(-1), properties);
  }
  throw Error(`Unexpected operator ${op}`);
}

test('surface management uses shared colors for available state schemas', () => {
  const cases = {
    az: [{CATEGORY:'BLM'}, 'rgb(254,230,121)'],
    ca: [{source_agency:'BLM California', SMA_ID: 2}, 'rgb(254,230,121)'],
    co: [{adm_code:'BLM'}, 'rgb(254,230,121)'],
    id: [{MGMT_AGNCY:'USFS'}, 'rgb(204,235,197)'],
    mt: [{OWNER:'US Bureau of Land Management'}, 'rgb(254,230,121)'],
    nm: [{own:'BLM'}, 'rgb(254,230,121)'],
    nv: [{ABBR:'BLM'}, 'rgb(254,230,121)'],
    or: [{PROPERTY_STATUS:'BLM'}, 'rgb(254,230,121)'],
    ut: [{ADMIN:'USFS'}, 'rgb(204,235,197)'],
    wa: [{ADMIN_AGENCY_CODE:'BLM'}, 'rgb(254,230,121)'],
    wy: [{JURIS_NAME:'BLM'}, 'rgb(254,230,121)']
  };
  for (const [state, [properties, expected]] of Object.entries(cases)) assert.equal(evaluate(expression, properties), expected, state);
  assert.equal(evaluate(expression, {SMA_ID: 915}), 'rgb(204,235,197)');
  assert.equal(evaluate(expression, {SMA_ID: 2, PROPERTY_STATUS:'UND'}), 'rgb(190,190,190)');
  assert.equal(evaluate(expression, {source_agency:'BLM California'}), 'rgb(190,190,190)');
  assert.equal(evaluate(expression, {ABBR:'WTR'}), 'rgb(190,190,190)');
  assert.equal(evaluate(expression, {CATEGORY:'State', ADMIN_AGENCY_CODE:'BLM'}), 'rgb(179,227,238)');
  assert.match(source, /'fill-color': surfaceManagementColorExpression\(\)/);
});
