const fs = require("node:fs");
const path = require("node:path");

function cleanOutput(outputPath) {
  fs.rmSync(outputPath, { recursive: true, force: true });
}

if (require.main === module) {
  cleanOutput(path.resolve(__dirname, "..", "out"));
}

module.exports = { cleanOutput };
