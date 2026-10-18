"""Deterministic publication receipts from freshly verified official bytes."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .policy import ROOT, REPOSITORY, TARGETS, fingerprint, require
from .process_candidate import git
from .process_state import atomic_bytes, atomic_json


GUIDES = ("docs/release.md", "docs/release/qualified-promotion.md")


def pinned_verification(progress, public, qualified):
    """Freeze presentation identity only after fresh independent public verification."""
    facts = {key: public[key] for key in ("version", "tag", "commit", "qualificationRun",
        "qualificationAttempt", "promotionRun", "promotionAttempt")}
    facts["manifest"] = qualified["manifest_sha256"]
    facts["targets"] = sorted((r["target"], r["sha256"], r["bytes"]) for r in public["targets"])
    identity = fingerprint(facts)
    prior = progress.intents.get("verification")
    if prior is None:
        prior = {"identity": identity, "verified_at": public["verifiedAt"]}
        progress.intents["verification"] = prior
        progress.save()
    require(prior["identity"] == identity, "Original verified receipt facts differ")
    first = datetime.fromisoformat(prior["verified_at"].replace("Z", "+00:00"))
    latest = datetime.fromisoformat(public["verifiedAt"].replace("Z", "+00:00"))
    require(first.utcoffset() is not None and latest.utcoffset() is not None and first <= latest,
        "Receipt verification anchor is invalid")
    return {**public, "verifiedAt": prior["verified_at"]}


def checked_public(directory, candidate):
    directory = Path(directory)
    public = json.loads((directory / "verification.json").read_text())
    qualified = json.loads((directory / "qualified.json").read_text())
    publisher = json.loads((directory / "publisher-proof.json").read_text())
    require(qualified.get("status") == "validated-for-publication"
        and qualified["manifest_sha256"] == fingerprint(qualified["manifest"])
        and qualified["manifest"]["source"] == qualified["source"]
        and all(qualified["source"].get(k) == v for k, v in candidate.items()), "Receipt qualification differs")
    require(public.get("schema") == 1 and public["version"] == candidate["version"]
        and public["commit"] == candidate["sha"] and public["tag"] == qualified["tag"]
        and public["qualificationRun"] == qualified["qualification_run"]
        and public["qualificationAttempt"] == qualified["qualification_attempt"]
        and public["promotionRun"] == qualified["promotion"]["run"]
        and public["promotionAttempt"] == qualified["promotion"]["attempt"], "Receipt run/tag identity differs")
    require(publisher.get("promotion") == qualified["promotion"]
        and publisher.get("prior_intents") == dict.fromkeys(TARGETS, True), "Missing retained publisher intents")
    rows = public.get("targets", [])
    require(len(rows) == len(TARGETS) and {r["target"] for r in rows} == set(TARGETS), "Public targets incomplete")
    for row in rows:
        target = row["target"]
        expected = qualified["manifest"]["packages"][target]
        data = (directory / f"official-{target}.vsix").read_bytes()
        require(row.get("qualifiedArtifactEqual") is True and row.get("catalogHashEqual") is True
            and row["sha256"] == expected["sha256"] == sha256(data).hexdigest()
            and row["bytes"] == expected["bytes"] == len(data), "Official receipt bytes differ")
    return public, qualified


def receipt_text(public, qualified, dry_run):
    instant = datetime.fromisoformat(public["verifiedAt"].replace("Z", "+00:00"))
    require(instant.utcoffset() is not None, "Verification needs an offset")
    local = instant.astimezone(ZoneInfo("America/Toronto"))
    source = qualified["source"]
    def run(identifier):
        return f"https://github.com/{REPOSITORY}/actions/runs/{identifier}"
    lines = [f"# {source['version']} Published Receipt", "",
        f"Public verification: {instant.isoformat()} ({local.strftime('%Y-%m-%d %H:%M:%S %Z')}).", "",
        "Both official packages match qualified bytes and declared Marketplace hashes.", "",
        f"- Tag: `{public['tag']}`.", f"- Source: `{source['sha']}`.",
        f"- Qualification contract: `{source['contract']}`.",
        f"- Manifest SHA-256: `{qualified['manifest_sha256']}`.",
        f"- [Normal qualification]({run(public['qualificationRun'])}), attempt {public['qualificationAttempt']}.",
        f"- [Credential-free dry-run]({run(dry_run['id'])}), attempt {dry_run['run_attempt']}.",
        f"- [Explicit promotion]({run(public['promotionRun'])}), attempt {public['promotionAttempt']}.", "",
        "| Target | SHA-256 | Bytes |", "| --- | --- | ---: |"]
    for row in sorted(public["targets"], key=lambda r: r["target"]):
        lines.append(f"| {row['target']} | `{row['sha256']}` | {row['bytes']:,} |")
    lines += ["", "Original producer, complete gate/case inventories, exact-package native proof",
        "and retained before-upload intents were independently verified. Promotion",
        "did not rebuild packages. Native Windows UI remains a coverage gap.", "",
        f"Timing disposition: `{qualified.get('timing_disposition', 'unavailable')}`.",
        "This records the verified policy, not a claim that hosted input latency is fixed.", "",
        "Publication does not install an extension or alter the live usage ledger.",
        "Receipt-only documentation commits do not move the tag or change its packages.", ""]
    return local.strftime("%Y-%m-%d"), "\n".join(lines)


def guide_updates(originals, version, filename):
    main = originals[GUIDES[0]]
    require(re.search(r"^Codex Usage [0-9]+\.[0-9]+\.[0-9]+ ships only", main, re.M), "Unknown release guide layout")
    main = re.sub(r"^Codex Usage [0-9]+\.[0-9]+\.[0-9]+ ships only", f"Codex Usage {version} ships only", main, count=1, flags=re.M)
    current = f"Current verified release: [{version} receipt](release/{filename})."
    if re.search(r"^Current verified release: .+$", main, re.M):
        main = re.sub(r"^Current verified release: .+$", current, main, count=1, flags=re.M)
    else:
        main = main.replace("# VSIX Releases\n", "# VSIX Releases\n\n" + current + "\n", 1)
    guide = originals[GUIDES[1]]
    parts = guide.split("\n\n", 2)
    require(len(parts) == 3 and parts[0] == "# Qualified VSIX Promotion" and parts[1].startswith("Status:"),
        "Unknown promotion guide layout")
    # Retain historical paragraphs; update only the first version/latest-receipt references.
    status = re.sub(r"Status: [0-9]+\.[0-9]+\.[0-9]+", f"Status: {version}", parts[1], count=1)
    status = re.sub(r"(\[latest receipt\]\()[^)]+(\))", rf"\g<1>{filename}\2", status, count=1)
    require(f"[latest receipt]({filename})" in status, "Missing current receipt slot")
    return {GUIDES[0]: main, GUIDES[1]: "\n\n".join([parts[0], status, parts[2]])}


def write_receipt(progress, public, qualified, dry_run, *, root=ROOT):
    day, text = receipt_text(public, qualified, dry_run)
    filename = f"{day}-{qualified['source']['version']}-published.md"
    originals = {name: git("show", f"{progress.candidate['sha']}:{name}", root=root, raw=True) for name in GUIDES}
    updates = guide_updates(originals, qualified["source"]["version"], filename)
    updates["docs/release/" + filename] = text
    # Check every destination before writing any; partially completed writes are idempotent.
    for name, desired in updates.items():
        path = root / name
        require(not path.is_symlink(), "Symlinked documentation destination")
        if path.exists():
            actual = path.read_text()
            require(actual == desired or (name in originals and actual == originals[name]),
                f"Preserve existing/manual documentation: {name}")
    for name, desired in updates.items():
        path = root / name
        if not path.exists() or path.read_text() != desired:
            atomic_bytes(path, desired.encode())
    atomic_json(progress.directory / "receipt.json", {"path": "docs/release/" + filename,
        "sha256": sha256(text.encode()).hexdigest(), "verified_at": public["verifiedAt"]})
    return "docs/release/" + filename
