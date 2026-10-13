"""Git Data model with real blob digests and fast-forward-only ref semantics."""
import base64
from copy import deepcopy
from hashlib import sha1
import json

from qualification_fixture import archives, package_bytes, policy
from release_tooling_support import load_tool

model = load_tool("release.journal_model")
storage = load_tool("release.git_journal")
GitWriteError = load_tool("release.journal_api").GitWriteError


class GitAPI:
    prefix = "repos/" + policy.REPOSITORY

    def __init__(self):
        self.blobs, self.trees, self.commits, self.heads, self.writes = {}, {}, {}, {}, []

    def raw(self, endpoint):
        ref = "refs/" + endpoint.split("/git/ref/")[1]
        if ref not in self.heads:
            raise ValueError("Missing retained ref")
        return policy.canonical({"ref": ref, "object": {"type": "commit", "sha": self.heads[ref]}})

    def json(self, endpoint):
        kind, key = endpoint.rsplit("/", 2)[-2:]
        return deepcopy(getattr(self, kind)[key])

    def write(self, method, endpoint, payload):
        self.writes.append((method, endpoint, deepcopy(payload)))
        if endpoint == "git/blobs":
            raw = base64.b64decode(payload["content"])
            key = storage.blob_sha(raw)
            self.blobs[key] = {"sha": key, "encoding": "base64", "size": len(raw), "content": payload["content"]}
        elif endpoint == "git/trees":
            key = sha1(policy.canonical(payload)).hexdigest()
            self.trees[key] = {"sha": key, "truncated": False, "tree": payload["tree"]}
        elif endpoint == "git/commits":
            key = sha1(policy.canonical(payload)).hexdigest()
            self.commits[key] = {"sha": key, "tree": {"sha": payload["tree"]},
                "parents": [{"sha": value} for value in payload["parents"]]}
        else:
            assert method == "PATCH" and payload["force"] is False
            ref = "refs/" + endpoint.removeprefix("git/refs/")
            cursor, ancestors = payload["sha"], set()
            while cursor not in ancestors:
                ancestors.add(cursor)
                parents = self.commits[cursor]["parents"]
                if not parents:
                    break
                cursor = parents[0]["sha"]
            if self.heads[ref] not in ancestors:
                raise GitWriteError("422", "Update is not a fast forward")
            self.heads[ref] = payload["sha"]
            return {"ref": ref, "object": {"sha": payload["sha"], "type": "commit"}}
        return {"sha": key}


class JournalFixture:
    def __init__(self, domain="production"):
        self.api = GitAPI()
        self.config = json.loads(model.CONFIG.read_text())
        self.config["domains"][domain]["workflow_id"] = 19
        selected = model.configuration(domain, self.config, pinned=False)
        self.root = self.commit(policy.canonical(model.origin(selected)), [])
        self.config["domains"][domain]["genesis"] = self.root
        self.selected = model.configuration(domain, self.config)
        self.api.heads[self.selected["ref"]] = self.root
        self.journal = storage.Journal(self.api, domain, self.config)
        self.api.writes.clear()

    def commit(self, data, parents):
        blob = self.api.write("POST", "git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        tree = self.api.write("POST", "git/trees", {"tree": [{"path": model.FILE, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        return self.api.write("POST", "git/commits", {"message": "fixture", "tree": tree["sha"], "parents": parents})["sha"]

    def event(self, target="darwin-arm64"):
        pilot = self.selected["domain"] == "pilot"
        version = "0.0.0-pilot.r77.a1" if pilot else "2.12.3"
        source = {"repository": policy.REPOSITORY, "repository_id": self.selected["repository_id"], "sha": "a"*40,
            "version": version, "contract": "b"*64, "workflow": self.selected["workflow"] if pilot else policy.WORKFLOW, "probe": pilot}
        body = {"schema": 1, "kind": "synthetic-journal-intent" if pilot else "publication-intent", "source": source,
            "tag": "v"+version, "qualification_run": 77, "qualification_attempt": 1, "manifest_sha256": "c"*64,
            "publisher_sha": "d"*40, "target": target, "package": archives.package_identity(package_bytes(target, version), target, version),
            "origin": {"run": 88, "attempt": 1, "job": "pilot" if pilot else "publish"}}
        return model.event_for(body, self.selected)

    def qualified(self):
        event = self.event()["intent"]
        return {"source": event["source"], "manifest": {"packages": {target: self.event(target)["intent"]["package"] for target in policy.TARGETS}}}
