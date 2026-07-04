# Packaging And Release

The product changed when it moved from "works on my machine" to "works on another user's machine."

## Local Development Runtime

During early extension development, running the Python CLI through `uv run codex-usage` was good enough. It made iteration fast and kept the TypeScript wrapper thin.

That was not a user-ready runtime. It assumed:

- the repo exists on the target machine;
- Python exists;
- `uv` exists;
- dependencies can be installed;
- the working directory is the source checkout.

Those assumptions are fine for development and wrong for Marketplace users.

## Bundled Windows Runtime

The Windows preview VSIX bundles:

```text
extensions/vscode/bin/win32-x64/codex-usage.exe
```

The executable is built from the Python core with PyInstaller. The extension spawns that executable directly with argument arrays.

Future me: the lesson is not "always use PyInstaller." The lesson is "extension runtime strategy is part of product design." A VS Code extension cannot assume the user's machine has your development environment.

## Bundled macOS Runtime

The macOS Apple Silicon preview VSIX bundles:

```text
extensions/vscode/bin/darwin-arm64/codex-usage
```

The executable is built from the Python core with PyInstaller on Apple Silicon. Intel macOS is intentionally unsupported.

## VSIX Contents

The VSIX should include:

- `extension/package.json`
- `extension/readme.md`
- `extension/changelog.md`
- `extension/SUPPORT.md`
- `extension/LICENSE.txt`
- `extension/media/icon.png`
- `extension/out/*.js`
- `extension/bin/win32-x64/codex-usage.exe`
- `extension/bin/darwin-arm64/codex-usage`

It should exclude TypeScript source, tests, and dev-only configs.

Inspect with:

```powershell
tar -tf output\releases\codex-usage-dashboard-win32-x64.vsix
```

## Marketplace Metadata

Marketplace readiness is not just code.

Required release surfaces:

- publisher id;
- semantic version;
- preview flag;
- repository, bugs, homepage;
- icon;
- screenshot;
- license;
- changelog;
- support document;
- privacy document;
- clear supported-platform preview note.

## Version Discipline

Marketplace versions are immutable. Once a version is published, the next upload must use a higher version.

Release flow:

Windows x64 on Windows/PowerShell:

```powershell
uv run pytest
cd extensions\vscode
npm test
npm run package:vsix:win
```

macOS Apple Silicon on macOS/bash:

```bash
uv run pytest
cd extensions/vscode
npm test
npm run package:vsix:mac
```

Then upload the VSIX or publish with `vsce` if login is configured.

After Marketplace accepts the release:

```powershell
git tag -a v0.1.31 -m "v0.1.31 Marketplace preview release"
git push origin v0.1.31
```

## Things To Watch After Publish

- Does Marketplace search index the extension?
- Does install work from Marketplace, not only local VSIX?
- Do users have old local publisher builds installed?
- Does Windows Defender or macOS Gatekeeper object to the bundled executable?
- Does first-run cache initialization feel understandable?
- Do users understand pricing is estimated from checked-in rates?
