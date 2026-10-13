const path = require('node:path');

// Stable test events are authority; human-readable reporter formatting is not.
module.exports = async function* qualificationReporter(events) {
  const collected = [];
  const cases = [];
  const summaries = [];
  for await (const { type, data } of events) {
    if (type === 'test:summary' && data.file === undefined) {
      summaries.push({ success: data.success, counts: data.counts });
    }
    if (!data.file || !Number.isInteger(data.line) || data.type === 'suite' || data.details?.type === 'suite') continue;
    // Process-isolation envelopes are file executions, not declared test cases.
    if (data.line === 1 && data.column === 1 && path.resolve(data.name) === path.resolve(data.file)) continue;
    const file = path.relative(process.cwd(), data.file).split(path.sep).join('/');
    const identity = [file, data.name];
    if (type === 'test:enqueue') collected.push(identity);
    if (type === 'test:pass' || type === 'test:fail') {
      cases.push({ identity, outcome: type === 'test:pass' ? 'passed' : 'failed',
        skipped: Boolean(data.skip), todo: Boolean(data.todo) });
    }
  }
  yield JSON.stringify({ schema: 1, complete: summaries.length === 1, summaries, collected, cases }) + '\n';
};
