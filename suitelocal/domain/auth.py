from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    id: int
    business_id: int
    username: str
    role: str
    active: bool


@dataclass(frozen=True, slots=True)
class Session:
    user: User

    @property
    def is_owner(self) -> bool:
        return self.user.role == "owner"
