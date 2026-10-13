const childProcess = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { npmCliPath } = require('./cliEntrypoints');

const root = path.resolve(__dirname, '..');
const output = path.resolve(process.argv[2]);
fs.mkdirSync(path.dirname(output), { recursive: true });
childProcess.execFileSync(process.execPath, [npmCliPath(), 'run', 'build'], { cwd: root, stdio: 'inherit' });
const tests = fs.readdirSync(path.join(root, 'test')).filter(file => file.endsWith('.test.js'))
  .sort().map(file => path.join(root, 'test', file));
childProcess.execFileSync(process.execPath, ['--test', '--test-reporter=junit', `--test-reporter-destination=${output}`,
  `--test-reporter=${pathToFileURL(path.join(__dirname, 'qualification-reporter.cjs')).href}`,
  `--test-reporter-destination=${path.join(path.dirname(output), 'extension-inventory.json')}`, ...tests],
{ cwd: root, stdio: 'inherit' });
const inventory = JSON.parse(fs.readFileSync(path.join(path.dirname(output), 'extension-inventory.json'), 'utf8'));
console.log(JSON.stringify({ extension: inventory.summaries, complete: inventory.complete }));
