# GitHub Actions VSIX Publish Design

## Goal

Build and publish the Windows x64 and macOS Apple Silicon VS Code Marketplace packages from GitHub Actions, without requiring local access to both operating systems.

## Requirements

- Provide a manual workflow trigger so a maintainer can build both platform packages on demand.
- Provide a tag trigger for release tags matching `v*`, so a normal release tag can build and publish both packages after the tag is verified against the checked-in extension version and `origin/main`.
- Build Windows x64 on a Windows GitHub-hosted runner and macOS Apple Silicon on an Apple Silicon macOS GitHub-hosted runner.
- Use the existing package scripts:
  - `npm run package:vsix:win`
  - `npm run package:vsix:mac`
- Upload each `.vsix` as a workflow artifact before publishing.
- Publish only with the repository secret `VSCE_PAT`.
- Avoid accidental manual publishing by making manual runs package-only unless a `publish` input is explicitly enabled.
- Publish automatically for `v*` tag pushes only after the tag matches `v${extensions/vscode/package.json.version}` and the tagged commit is contained in `origin/main`.
- Keep the workflow scoped to standard GitHub-hosted runners so this public repository can use GitHub Actions without paid larger-runner usage.

## Architecture

The workflow will have independent `windows` and `macos` packaging jobs. Each job checks out the repository, installs Python through `actions/setup-python`, installs `uv`, installs Node.js through `actions/setup-node`, runs the relevant test suite, packages the platform-specific VSIX, and uploads the VSIX artifact.

A final publish job will depend on both packaging jobs. It downloads both artifacts and runs one duplicate-tolerant `npx vsce publish --skip-duplicate --packagePath <windows-vsix> <macos-vsix>` command only when either the workflow is running for a validated `v*` tag or a manual `publish` input is true from `main`. If either packaging job fails, publishing does not run.

## Data Flow

1. GitHub Actions checks out the repository.
2. Python dependencies are resolved by `uv` from `pyproject.toml` and `uv.lock`.
3. VS Code extension dependencies are installed from `extensions/vscode/package-lock.json`.
4. Platform build scripts create:
   - `output/releases/codex-usage-dashboard-win32-x64.vsix`
   - `output/releases/codex-usage-dashboard-darwin-arm64.vsix`
5. The publish job downloads both artifacts into `output/releases`.
6. For `v*` tags, the publish job verifies the tag name matches the checked-in extension version and the tagged commit is contained in `origin/main`.
7. `vsce publish` reads step-scoped `VSCE_PAT` only in the verify/publish steps and publishes both package files.

## Error Handling

- A missing or invalid `VSCE_PAT` fails only the publish job, after packaging artifacts have already been uploaded.
- A tag/version mismatch or tag outside `origin/main` fails before `VSCE_PAT` is read.
- A duplicate Marketplace version is skipped during publish reruns via `--skip-duplicate`.
- A runner/platform mismatch fails inside the existing build script checks, especially the macOS Apple Silicon script.
- Manual package-only runs never read `VSCE_PAT`.

## Testing

- Validate the workflow syntax locally with a YAML parser.
- Verify the workflow references the exact package scripts and expected VSIX paths.
- Run the existing Python and VS Code extension tests locally before committing workflow changes.
- After pushing, run the workflow manually with `publish=false` to prove artifact generation.
- Use a release tag matching the checked-in extension version on `main` to perform the first automated publish once the artifact-only workflow run is healthy.

## Open Decisions

No open product decisions remain. Manual runs default to package-only, and validated version tags on `main` publish automatically.
