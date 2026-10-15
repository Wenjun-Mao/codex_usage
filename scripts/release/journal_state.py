"""Chronological admission shares one parent for approvals and possible uploads."""
from .latency_bindings import KIND, reference, require_source
from .journal_model import validate_event
from .policy import canonical, require


class JournalState:
    def __init__(self, config):
        self.config = config
        self.binding = None
        self.upload_sources = {}
        self.targets = set()

    def admit(self, event):
        validate_event(event, self.config)
        if event["kind"] == KIND:
            self._admit_binding(event["binding"])
        else:
            self._admit_intent(event["intent"])

    def _admit_binding(self, binding):
        slot = binding["slot"]
        require(not any(version == slot["release_version"] for version, _ in self.targets),
            "Possible publication permanently freezes D4 supersession")
        if self.binding is None:
            require(binding["revision"] == 1 and binding["supersedes"] is None,
                "Initial D4 binding must create the unique release slot")
            return
        previous = self.binding["event"]["binding"]
        require(canonical(previous["slot"]) == canonical(slot), "D4 release slot cannot change")
        require(binding["supersedes"] == self.binding["commit"]
            and binding["revision"] == previous["revision"]+1,
            "D4 replacement must supersede the current predecessor")
        require(previous["purpose"] != "release" or binding["purpose"] == "release",
            "D4 purpose cannot regress")
        require(canonical(binding["source"]) != canonical(previous["source"])
            or binding["purpose"] != previous["purpose"], "D4 replacement makes no authority change")

    def _admit_intent(self, intent):
        version, source = intent["source"]["version"], canonical(intent["source"])
        require(version not in self.upload_sources or self.upload_sources[version] == source,
            "Conflicting same-version journal sources")
        require((version, intent["target"]) not in self.targets,
            "Target already has a retained possible upload; do not record/re-upload")
        binding = self.binding["event"]["binding"] if self.binding is not None else None
        if binding is not None and binding["slot"]["release_version"] == version:
            require_source(binding, intent["source"], publication=True)
            require(canonical(intent.get("latency_binding")) == canonical(reference(self.binding, self.config)),
                "Publication intent must bind the current D4 candidate")
        else:
            require("latency_binding" not in intent, "Intent references an unknown D4 release slot")

    def apply(self, record):
        event = record["event"]
        self.admit(event)
        if event["kind"] == KIND:
            self.binding = record
        else:
            intent = event["intent"]
            version = intent["source"]["version"]
            self.upload_sources[version] = canonical(intent["source"])
            self.targets.add((version, intent["target"]))


def retained_state(records, config):
    result = JournalState(config)
    for record in records:
        result.apply(record)
    return result
