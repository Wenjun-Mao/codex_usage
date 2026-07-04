# GitHub Actions VSIX Publish Design

## Goal

Build and publish the Windows x64 and macOS Apple Silicon VS Code Marketplace packages from GitHub Actions, without requiring local access to both operating systems.

## Requirements

- Provide a manual workflow trigger so a maintainer can build both platform packages on demand.
- Provide a tag trigger for release tags matching `v*`, so a normal release tag can build and publish both packages.
- Build Windows x64 on a Windows GitHub-hosted runner and macOS Apple Silicon on an Apple Silicon macOS GitHub-hosted runner.
- Use the existing package scripts:
  - `npm run package:vsix:win`
  - `npm run package:vsix:mac`
- Upload each `.vsix` as a workflow artifact before publishing.
- Publish only with the repository secret `VSCE_PAT`.
- Avoid accidental manual publishing by making manual runs package-only unless a `publish` input is explicitly enabled.
- Publish automatically for `v*` tag pushes.
- Keep the workflow scoped to standard GitHub-hosted runners so this public repository can use GitHub Actions without paid larger-runner usage.

## Architecture

The workflow will have independent `windows` and `macos` packaging jobs. Each job checks out the repository, installs Python through `actions/setup-python`, installs `uv`, installs Node.js through `actions/setup-node`, runs the relevant test suite, packages the platform-specific VSIX, and uploads the VSIX artifact.

A final publish job will depend on both packaging jobs. It downloads both artifacts and runs `npx vsce publish --packagePath ...` for each VSIX only when either the workflow is running for a `v*` tag or a manual `publish` input is true. If either packaging job fails, publishing does not run.

## Data Flow

1. GitHub Actions checks out the repository.
2. Python dependencies are resolved by `uv` from `pyproject.toml` and `uv.lock`.
3. VS Code extension dependencies are installed from `extensions/vscode/package-lock.json`.
4. Platform build scripts create:
   - `output/releases/codex-usage-dashboard-win32-x64.vsix`
   - `output/releases/codex-usage-dashboard-darwin-arm64.vsix`
5. The publish job downloads both artifacts into `output/releases`.
6. `vsce publish` reads `VSCE_PAT` from the job environment and publishes both package files.

## Error Handling

- A missing or invalid `VSCE_PAT` fails only the publish job, after packaging artifacts have already been uploaded.
- A duplicate Marketplace version fails during publish because Marketplace versions are immutable.
- A runner/platform mismatch fails inside the existing build script checks, especially the macOS Apple Silicon script.
- Manual package-only runs never read `VSCE_PAT`.

## Testing

- Validate the workflow syntax locally with a YAML parser.
- Verify the workflow references the exact package scripts and expected VSIX paths.
- Run the existing Python and VS Code extension tests locally before committing workflow changes.
- After pushing, run the workflow manually with `publish=false` to prove artifact generation.
- Use a release tag to perform the first automated publish once the artifact-only workflow run is healthy.

## Open Decisions

No open product decisions remain. Manual runs default to package-only, and tag pushes publish automatically.
