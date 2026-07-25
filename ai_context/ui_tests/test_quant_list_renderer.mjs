// Exercises the REAL VifelQuantListRenderer logic: the file is read from disk,
// its Odoo imports stripped and the base class swapped for a stub, so what is
// tested is the shipped code rather than a re-typed copy.
import fs from 'node:fs';
import path from 'node:path';

const SRC = 'C:/Odoo17E/server/addons/custom_addons/vifel-20250717/multiple_relocation/static/src/js/quant_report_button.js';
let src = fs.readFileSync(SRC, 'utf8');

// Strip only the odoo imports; every symbol they provided is stubbed below so
// the rest of the file — including the renderer under test — runs verbatim.
src = src.replace(/^import .*$/gm, '');
src = src.replace(/^\/\*\* @odoo-module \*\/$/gm, '');
src = src.replace(/^export class VifelQuantListRenderer extends ListRenderer/m,
                  'class VifelQuantListRenderer extends ListRenderer');

const STUB = `
let superCalls = 0;
const SUPER = Symbol('super');
class ListRenderer {
    computeColumnWidthsFromContent() { superCalls++; return SUPER; }
    freezeColumnWidths() { this.frozen = (this.frozen || 0) + 1; }
}
class ListController { setup() {} }
const listView = {};
const registry = { category: () => ({ add: () => {} }) };
const useService = () => ({});
`;
const TAIL = `
export { VifelQuantListRenderer, SUPER };
export const getSuperCalls = () => superCalls;
export const resetSuper = () => { superCalls = 0; };
`;
// Written to the scratch dir, never into the addons tree.
const tmp = path.join('C:/Users/templ/.claude/jobs/95e9c46c/tmp', '_vifel_test_tmp.mjs');
fs.writeFileSync(tmp, STUB + src + TAIL);
let mod;
try {
    mod = await import('file://' + tmp.replace(/\\/g, '/'));
} finally {
    fs.unlinkSync(tmp);
}
const { VifelQuantListRenderer, SUPER, getSuperCalls, resetSuper } = mod;

let pass = 0, fail = 0;
const check = (label, cond, detail = '') => {
    if (cond) { pass++; console.log(`  PASS ${label}`); }
    else { fail++; console.log(`  FAIL ${label} ${detail}`); }
};

// ---- fake DOM -------------------------------------------------------
function makeTable({ nCols = 30, colWidth = 150, containerWidth = 1200, throwOnMeasure = false }) {
    const classes = new Set();
    const ths = Array.from({ length: nCols }, () => ({
        getBoundingClientRect() {
            if (throwOnMeasure) throw new Error('boom');
            return { width: colWidth };
        },
        style: {},
    }));
    return {
        classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), has: (c) => classes.has(c) },
        querySelectorAll: () => ths,
        parentNode: { getBoundingClientRect: () => ({ width: containerWidth }), style: {} },
        _classes: classes,
    };
}
function makeRenderer(ctx, table) {
    const r = Object.create(VifelQuantListRenderer.prototype);
    r.props = { list: { context: ctx } };
    r.env = {};
    r.tableRef = { el: table };
    return r;
}

console.log('\n=== VifelQuantListRenderer safety ===');

// 1. gate off -> stock Odoo
resetSuper();
let t = makeTable({});
let r = makeRenderer({}, t);
let out = r.computeColumnWidthsFromContent();
check('without show_pkr_report falls back to Odoo', out === SUPER && getSuperCalls() === 1);

// 2. gate on + columns overflow -> our widths
resetSuper();
t = makeTable({ nCols: 30, colWidth: 150, containerWidth: 1200 });  // 4500 > 1200
r = makeRenderer({ show_pkr_report: true }, t);
out = r.computeColumnWidthsFromContent();
check('overflowing list keeps natural widths', Array.isArray(out) && out.length === 30 && getSuperCalls() === 0,
      `got ${Array.isArray(out) ? out.length + ' cols' : String(out)}`);
check('width cap applied', Array.isArray(out) && out.every((w) => w <= 320));

// 3. cap actually caps a very wide column
resetSuper();
t = makeTable({ nCols: 30, colWidth: 900, containerWidth: 1200 });
r = makeRenderer({ show_pkr_report: true }, t);
out = r.computeColumnWidthsFromContent();
check('a 900px column is capped to 320', Array.isArray(out) && Math.max(...out) === 320);

// 4. columns already fit -> stock Odoo (no right-hand gap)
resetSuper();
t = makeTable({ nCols: 4, colWidth: 100, containerWidth: 1200 });   // 400 < 1200
r = makeRenderer({ show_pkr_report: true }, t);
out = r.computeColumnWidthsFromContent();
check('already-fitting list falls back to Odoo', out === SUPER && getSuperCalls() === 1);

// 5. missing table -> stock Odoo
resetSuper();
r = makeRenderer({ show_pkr_report: true }, null);
out = r.computeColumnWidthsFromContent();
check('missing table falls back to Odoo', out === SUPER && getSuperCalls() === 1);

// 6. measurement throws -> stock Odoo, and helper class cleaned up
resetSuper();
t = makeTable({ throwOnMeasure: true });
r = makeRenderer({ show_pkr_report: true }, t);
out = r.computeColumnWidthsFromContent();
check('a throw mid-measure falls back to Odoo', out === SUPER && getSuperCalls() === 1);
check('helper class removed after the throw', !t._classes.has('o_list_computing_widths'),
      [...t._classes].join(','));

// 7. searchModel fallback for the context
resetSuper();
t = makeTable({ nCols: 30, colWidth: 150, containerWidth: 1200 });
r = makeRenderer({}, t);
r.env = { searchModel: { context: { show_pkr_report: true } } };
out = r.computeColumnWidthsFromContent();
check('searchModel context also enables wide mode', Array.isArray(out) && getSuperCalls() === 0);

// 8. freezeColumnWidths always calls super, and only scrolls when gated
t = makeTable({});
r = makeRenderer({}, t);
r.freezeColumnWidths();
check('freeze calls super when gate off', r.frozen === 1);
check('no overflow set when gate off', t.parentNode.style.overflowX === undefined);

t = makeTable({});
r = makeRenderer({ show_pkr_report: true }, t);
r.freezeColumnWidths();
check('freeze calls super when gate on', r.frozen === 1);
check('overflow-x set when gate on', t.parentNode.style.overflowX === 'auto');

r = makeRenderer({ show_pkr_report: true }, null);
let threw = false;
try { r.freezeColumnWidths(); } catch (e) { threw = true; }
check('freeze survives a missing table', !threw && r.frozen === 1);

console.log(`\n==== ${pass}/${pass + fail} passed ====`);
