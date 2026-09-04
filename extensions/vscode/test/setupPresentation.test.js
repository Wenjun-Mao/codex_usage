const assert = require("node:assert/strict");
const test = require("node:test");

const {
  captureIntervalChoices,
  captureScheduleMessage,
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
