"""Lazy identity reuse confined to one parse chunk, with fresh exit validation."""
from codex_usage.models import SessionMetadata
from codex_usage.project_identity import ProjectIdentity, resolve_project_identity

type IdentityKey = tuple[str, str, str, str]


class ParseProjectIdentity:
    def __init__(self):
        self._key: IdentityKey | None = None
        self._identity: ProjectIdentity | None = None
        self._witnesses: dict[IdentityKey, tuple[SessionMetadata, ProjectIdentity]] = {}

    def resolve(self, metadata: SessionMetadata) -> ProjectIdentity:
        key = (metadata.cwd, metadata.git_repository_url,
               metadata.git_commit_hash, metadata.session_id)
        if key != self._key:
            identity = resolve_project_identity(metadata)
            prior = self._witnesses.get(key)
            if prior is not None and prior[1] != identity:
                raise OSError("project identity changed during parsing")
            self._witnesses.setdefault(key, (metadata, identity))
            self._key, self._identity = key, identity
        assert self._identity is not None
        return self._identity

    def validate(self) -> None:
        # Recheck earlier scopes too; final/root metadata cannot attest for them.
        for metadata, expected in self._witnesses.values():
            if resolve_project_identity(metadata) != expected:
                raise OSError("project identity changed during parsing")
