import { build } from "esbuild";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const root = new URL(".", import.meta.url);
const result = await build({
  entryPoints: [new URL("app.js", root).pathname],
  bundle: true,
  write: false,
  format: "iife",
  minify: true,
  target: "es2022",
});
const css = await readFile(new URL("app.css", root), "utf8");
const html = await readFile(new URL("index.html", root), "utf8");
const script = result.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");
await mkdir(new URL("dist/", root), { recursive: true });
await writeFile(
  new URL("dist/probe.html", root),
  html.replace("<!-- STYLE -->", () => `<style>${css}</style>`)
    .replace("<!-- SCRIPT -->", () => `<script>${script}</script>`),
);
