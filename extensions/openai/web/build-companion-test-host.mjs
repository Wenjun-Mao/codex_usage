import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
const root = new URL(".", import.meta.url);
const fixtures = execFileSync("uv", ["run", "--frozen", "python", "extensions/openai/tests/export_companion_fixture.py"], {
  cwd: new URL("../../..", root), encoding: "utf8", env: { ...process.env, PYTHONPATH: "src" },
});
await writeFile(new URL("dist/companion-fixtures.json", root), fixtures);
const result = await build({ entryPoints: [new URL("companion-test-host.js", root).pathname], bundle: true, write: false, format: "iife", minify: true, target: "es2022" });
await writeFile(new URL("dist/companion-test-host.html", root), '<!doctype html><title>Disposable private companion harness</title><style>body{margin:0}iframe{border:0;width:100%;height:1400px;display:block}</style><iframe id="companion" title="Codex Usage"></iframe>' + `<script>${result.outputFiles[0].text.replace(/<\/script/gi, "<\\/script")}</script>`);
