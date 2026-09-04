const assert = require("node:assert/strict");
const test = require("node:test");

const {
  captureIntervalChoices,
  captureScheduleMessage,
  collectorSetupChoices,
  projectTransitionChoices,
  validateCaptureInterval,
} = require("../out/setupPresentation");

test("collector setup exposes Manual only and preserves the current capture interval", () => {
  const choices = captureIntervalChoices(15);
  assert.equal(choices[0].value, null);
  assert.equal(choices.find((choice) => choice.value === 15).description, "Current");
  assert.match(captureScheduleMessage(null), /Manual only/);
  assert.match(captureScheduleMessage(60), /60 minutes while VS Code is open/);
  assert.equal(validateCaptureInterval("1440"), undefined);
  assert.match(validateCaptureInterval("1441"), /1 to 1,440/);
});

test("collector setup exposes project transitions and the shared Task Transfer folder", () => {
  const actions = collectorSetupChoices("/tmp/codex-home");
  assert.ok(actions.some((choice) => choice.action === "transitions"));
  assert.ok(actions.some((choice) => choice.action === "transferFolder"));
  assert.equal(projectTransitionChoices(true).find((choice) => choice.enabled)?.description, "Current");
  assert.equal(projectTransitionChoices(false).find((choice) => !choice.enabled)?.description, "Current");
});
