from suitelocal.domain.auth import Session


def require_owner(session: Session) -> None:
    if not session.is_owner:
        raise PermissionError("Solo el dueño puede realizar esta acción.")
