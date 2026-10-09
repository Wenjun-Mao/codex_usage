const assert = require("node:assert/strict");
const test = require("node:test");

const {
  usageReportNeedsRefresh,
  usageStatusFingerprint,
} = require("../out/usageRefreshPolicy");

function status(overrides = {}) {
  return {
    ledger_revision: 12,
    last_capture_at: "2026-09-04T12:00:00Z",
    last_capture_outcome: "success",
    last_capture_error: "",
    coverage: {
      complete: false,
      fraction: 0.5,
      stale_sources: 0,
      pending_files: 10,
      pending_bytes: 1_000,
    },
    ...overrides,
  };
}

test("an open usage report refreshes only after meaningful ledger status changes", () => {
  const rendered = status();
  const fingerprint = usageStatusFingerprint(rendered);

  assert.equal(usageReportNeedsRefresh(undefined, rendered), false);
  assert.equal(usageReportNeedsRefresh(fingerprint, rendered), false);
  assert.equal(
    usageReportNeedsRefresh(fingerprint, status({
      last_capture_at: "2026-09-04T12:01:00Z",
    })),
    false,
  );
  assert.equal(
    usageReportNeedsRefresh(fingerprint, status({ ledger_revision: 13 })),
    true,
  );
  assert.equal(
    usageReportNeedsRefresh(fingerprint, status({
      coverage: { ...rendered.coverage, fraction: 0.75, pending_bytes: 500 },
    })),
    true,
  );
});

test("quota freshness and elapsed deadlines refresh without ledger mutations", () => {
  const originalNow = Date.now;
  try {
    Date.now = () => 99_000;
    const quota = { probe_status: "fresh", active_buckets: [{ limit_id: "codex", duration_minutes: 10080, resets_at: 100 }] };
    const current = status({ plan_allowance: quota });
    const fingerprint = usageStatusFingerprint(current);
    assert.equal(usageReportNeedsRefresh(fingerprint, current), false);
    Date.now = () => 101_000;
    assert.equal(usageReportNeedsRefresh(fingerprint, current), true);
    Date.now = () => 99_000;
    assert.equal(usageReportNeedsRefresh(fingerprint, status({ plan_allowance: { ...quota, probe_status: "stale" } })), true);
  } finally {
    Date.now = originalNow;
  }
});
