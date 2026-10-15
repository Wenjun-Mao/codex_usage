"""Linear Git receipt history with immutable origin and non-forced atomic updates."""
import base64
from hashlib import sha1
import json
from uuid import UUID, uuid4

from .journal_model import FILE, MAX_BLOB, MAX_RECORDS, configuration, git_sha, origin, validate_event
from .policy import SCHEMA, canonical, fingerprint, require
from .journal_state import retained_state
from .latency_bindings import KIND, reference, require_current


def blob_sha(data):
    return sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


class Journal:
    def __init__(self, api, domain="production", config=None):
        self.api = api
        self.config = configuration(domain, config)

    def head(self):
        # A ref is mutable; never use the immutable-object response cache here.
        row = json.loads(self.api.raw(f"{self.api.prefix}/git/ref/{self.config['ref'].removeprefix('refs/')}"))
        require(row["ref"] == self.config["ref"] and row["object"]["type"] == "commit", "Foreign journal ref")
        return git_sha(row["object"]["sha"])

    def record(self, commit_sha):
        commit = self.api.json(f"{self.api.prefix}/git/commits/{git_sha(commit_sha)}")
        require(commit["sha"] == commit_sha, "Commit identity differs")
        tree = self.api.json(f"{self.api.prefix}/git/trees/{git_sha(commit['tree']['sha'])}")
        require(tree.get("truncated") is False and len(tree["tree"]) == 1, "Foreign or incomplete journal tree")
        entry = tree["tree"][0]
        require(entry["path"] == FILE and entry["type"] == "blob" and entry["mode"] == "100644", "Foreign journal blob")
        blob = self.api.json(f"{self.api.prefix}/git/blobs/{git_sha(entry['sha'])}")
        require(blob["encoding"] == "base64", "Foreign blob encoding")
        data = base64.b64decode(blob["content"])
        require(len(data) <= MAX_BLOB and len(data) == blob["size"] and blob_sha(data) == entry["sha"], "Journal blob integrity differs")
        parsed = json.loads(data)
        require(canonical(parsed) == data, "Noncanonical journal record")
        return commit, parsed

    def read(self, head=None):
        head = cursor = self.head() if head is None else git_sha(head)
        records, seen = [], set()
        while cursor != self.config["genesis"]:
            require(cursor not in seen and len(records) < MAX_RECORDS, "Cyclic or excessive journal history")
            seen.add(cursor)
            commit, record = self.record(cursor)
            require(len(commit["parents"]) == 1, "Journal history is not linear")
            previous = git_sha(commit["parents"][0]["sha"])
            require(set(record) == {"schema", "kind", "genesis", "previous", "sequence", "invocation", "event"}
                and type(record["schema"]) is int and record["schema"] == SCHEMA and record["kind"] == "journal-entry"
                and record["genesis"] == self.config["genesis"] and record["previous"] == previous
                and type(record["sequence"]) is int, "Journal continuity differs")
            require(isinstance(record["invocation"], str) and UUID(record["invocation"]).version == 4
                and str(UUID(record["invocation"])) == record["invocation"], "Invalid journal invocation")
            records.append({**record, "commit": cursor})
            cursor = previous
        commit, root = self.record(cursor)
        require(commit["parents"] == [] and canonical(root) == canonical(origin(self.config)), "Pinned journal origin differs")
        records.reverse()
        for index, record in enumerate(records, 1):
            require(record["sequence"] == index, "Journal sequence differs")
        retained_state(records, self.config)
        require(len({record["invocation"] for record in records}) == len(records), "Repeated journal invocation")
        return {"head": head, "records": records}

    def candidate(self, event, snapshot=None):
        event = validate_event(event, self.config)
        snapshot = self.read() if snapshot is None else snapshot
        require(canonical(snapshot) == canonical(self.read(snapshot["head"])), "Candidate snapshot is not verified Git history")
        require(len(snapshot["records"]) < MAX_RECORDS, "Journal record limit reached")
        retained_state(snapshot["records"], self.config).admit(event)
        record = {"schema": SCHEMA, "kind": "journal-entry", "genesis": self.config["genesis"],
            "previous": snapshot["head"], "sequence": len(snapshot["records"]) + 1, "invocation": str(uuid4()), "event": event}
        data = canonical(record)
        require(len(data) <= MAX_BLOB, "Serialized journal record exceeds bounds")
        blob = self.api.write("POST", "git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        require(blob["sha"] == blob_sha(data), "Created blob identity differs")
        tree = self.api.write("POST", "git/trees", {"tree": [{"path": FILE, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        commit = self.api.write("POST", "git/commits", {"message": f"Record {self.config['domain']} possible publication {record['sequence']}",
            "tree": git_sha(tree["sha"]), "parents": [snapshot["head"]]})
        return {"commit": git_sha(commit["sha"]), "record": record}

    def anchor(self, candidate):
        require(self.head() == candidate["record"]["previous"], "Journal head advanced; candidate cannot be replayed")
        self.api.write("PATCH", "git/refs/" + self.config["ref"].removeprefix("refs/"),
            {"sha": candidate["commit"], "force": False})
        # Unknown write results never grant authority; read back anchored ancestry.
        event = candidate["record"]["event"]
        if event["kind"] == KIND:
            return self.binding_witness(candidate["commit"], event["binding"])
        return self.witness(candidate["commit"], event["intent"])

    def witness(self, commit, intent):
        snapshot = self.read()
        matches = [record for record in snapshot["records"] if record["commit"] == git_sha(commit)
                   and record["event"]["kind"] != KIND]
        require(len(matches) == 1 and canonical(matches[0]["event"]["intent"]) == canonical(intent), "Intent is not anchored in retained history")
        return {"schema": SCHEMA, "domain": self.config["domain"], "ref": self.config["ref"],
            "genesis": self.config["genesis"], "commit": commit, "sequence": matches[0]["sequence"],
            "invocation": matches[0]["invocation"], "intent_sha256": fingerprint(intent)}

    def binding_witness(self, commit, binding):
        snapshot = self.read()
        current = retained_state(snapshot["records"], self.config).binding
        require(current is not None and current["commit"] == git_sha(commit)
            and canonical(current["event"]["binding"]) == canonical(binding),
            "D4 binding is not the current anchored candidate")
        return reference(current, self.config)

    def current_binding(self, source, *, publication=False):
        snapshot = self.read()
        current = require_current(retained_state(snapshot["records"], self.config).binding,
                                  source, publication=publication)
        return {"reference": reference(current, self.config), "binding": current["event"]["binding"]}
