const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/app.js', 'utf8');
const start = source.indexOf('class ResultsTable {');
const end = source.indexOf('\n// ----------', start);
const ResultsTable = vm.runInNewContext(source.slice(start, end) + '\nResultsTable', {
  Intl, $$: () => [],
});
const table = Object.create(ResultsTable.prototype);
table.capitalSort = true;
table.render = () => {};
table.sort = null;
const rows = [
  { jobNo: 'missing', jobCompanyName: 'A', jobCompanyCapital: null },
  { jobNo: 'small', jobCompanyName: 'B', jobCompanyCapital: 3000000 },
  { jobNo: 'large1', jobCompanyName: 'C', jobCompanyCapital: 120000000 },
  { jobNo: 'large2', jobCompanyName: 'C', jobCompanyCapital: 120000000 },
  { jobNo: 'zero', jobCompanyName: 'D', jobCompanyCapital: 0 },
];
const ids = () => Array.from(table.sorted(rows), r => r.jobNo);
table.toggleSort('company');
assert.deepEqual(ids(), ['large1', 'large2', 'small', 'zero', 'missing']);
table.toggleSort('company');
assert.deepEqual(ids(), ['zero', 'small', 'large1', 'large2', 'missing']);
table.toggleSort('company');
assert.equal(table.sorted(rows), rows);
table.capitalSort = false;
table.toggleSort('company');
assert.deepEqual(ids(), ['missing', 'small', 'large1', 'large2', 'zero']);
console.log('Company sorting tests passed');
