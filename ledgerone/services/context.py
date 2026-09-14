from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccessContext:
    """Authorisation context shared by web, API and trusted local AI callers."""

    identity_type: str
    organisation_id: str | None
    user_id: str | None = None
    api_key_id: str | None = None
    full_access: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)

    def can(self, permission: str) -> bool:
        return self.full_access or "*" in self.permissions or permission in self.permissions

    @classmethod
    def system(cls, organisation_id: str | None = None):
        return cls(
            identity_type="system",
            organisation_id=organisation_id,
            full_access=True,
            permissions=frozenset({"*"}),
        )
