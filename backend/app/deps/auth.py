from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AiRun, User


def get_current_user(
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    user = db.get(User, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    return user


def require_author(user: User = Depends(get_current_user)) -> User:
    if user.role != "author":
        raise HTTPException(status_code=403, detail={"error": "author_role_required"})
    return user


def require_canon_author(
    x_user_id: str | None = Header(default=None),
    x_ai_run_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Author-only Canon mutation guard with a Canon-specific AI error."""
    if x_ai_run_id:
        if db.get(AiRun, x_ai_run_id) is not None:
            raise HTTPException(status_code=403, detail={"error": "ai_role_cannot_modify_canon"})
        raise HTTPException(status_code=401, detail={"error": "invalid_ai_identity"})
    if not x_user_id:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    user = db.get(User, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    if user.role != "author":
        raise HTTPException(status_code=403, detail={"error": "author_role_required"})
    return user


def require_canon_reader(
    x_user_id: str | None = Header(default=None),
    x_ai_run_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple[str, User | None, AiRun | None]:
    if x_ai_run_id:
        run = db.get(AiRun, x_ai_run_id)
        if run is None:
            raise HTTPException(status_code=401, detail={"error": "invalid_ai_identity"})
        return "ai", None, run
    if x_user_id:
        user = db.get(User, x_user_id)
        if user is not None and user.role == "author":
            return "author", user, None
    raise HTTPException(status_code=401, detail={"error": "authentication_required"})


def require_ai_identity(
    x_ai_run_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AiRun:
    if x_user_id and not x_ai_run_id:
        raise HTTPException(status_code=403, detail={"error": "author_cannot_use_ai_agent"})
    if not x_ai_run_id:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    run = db.get(AiRun, x_ai_run_id)
    if run is None:
        raise HTTPException(status_code=401, detail={"error": "invalid_ai_identity"})
    return run


def validate_agent_role(agent_role: str):
    from app.config.ai_settings import AGENT_ROLES
    if agent_role not in AGENT_ROLES:
        raise HTTPException(status_code=422, detail={"error": "invalid_agent_role"})
    return agent_role


def check_agent_enabled(agent_role: str):
    from app.config.ai_settings import get_ai_settings
    if agent_role not in get_ai_settings().enabled_agents:
        raise HTTPException(status_code=403, detail={"error": "agent_role_not_enabled"})
    return agent_role


def require_author_write(
    x_user_id: str | None = Header(default=None),
    x_ai_run_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if x_ai_run_id:
        if db.get(AiRun, x_ai_run_id) is not None:
            raise HTTPException(status_code=403, detail={"error": "ai_role_cannot_modify_revision"})
        raise HTTPException(status_code=401, detail={"error": "invalid_ai_identity"})
    if not x_user_id:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    user = db.get(User, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "authentication_required"})
    if user.role != "author":
        raise HTTPException(status_code=403, detail={"error": "author_role_required"})
    return user


def require_revision_creator(
    x_user_id: str | None = Header(default=None),
    x_ai_run_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple[str, User | None, AiRun | None]:
    if x_ai_run_id:
        run = db.get(AiRun, x_ai_run_id)
        if run is None:
            raise HTTPException(status_code=401, detail={"error": "invalid_ai_identity"})
        return "ai", None, run
    if x_user_id:
        user = db.get(User, x_user_id)
        if user is not None and user.role == "author":
            return "author", user, None
    raise HTTPException(status_code=401, detail={"error": "authentication_required"})
