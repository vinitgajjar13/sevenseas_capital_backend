import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User
from app.schemas.auth import LoginRequest, ResetPasswordRequest, LoginResponse, UserOut
from app.core.security import verify_password, get_password_hash, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory brute force protection tracking
# { "ip_or_user": {"attempts": int, "locked_until": float} }
FAILED_ATTEMPTS: dict[str, dict] = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60

# Master recovery codes accepted for terminal admin password recovery
VALID_RECOVERY_CODES = {"7777", "SEVENSEAS2026", "SEVENSEAS", "ADMIN77"}

async def ensure_default_user(db: AsyncSession) -> User:
    """Ensure the default Sevenseas trader user exists with initial password."""
    stmt = select(User).where(User.username.ilike("Sevenseas"))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        user = User(
            username="Sevenseas",
            password_hash=get_password_hash("Sevenseas@1211"),
            role="Senior Pro Trader (Terminal Admin)",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user

@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    username_key = req.username.strip().lower()
    now = time.time()

    # Rate limiting check
    if username_key in FAILED_ATTEMPTS:
        state = FAILED_ATTEMPTS[username_key]
        if now < state.get("locked_until", 0):
            wait_sec = int(state["locked_until"] - now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Security lockout: Too many failed attempts. Try again in {wait_sec} seconds.",
            )

    # Make sure default user exists
    await ensure_default_user(db)

    # Find user
    stmt = select(User).where(User.username.ilike(req.username.strip()))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        # Record failed attempt
        state = FAILED_ATTEMPTS.get(username_key, {"attempts": 0, "locked_until": 0})
        state["attempts"] += 1
        if state["attempts"] >= MAX_ATTEMPTS:
            state["locked_until"] = now + LOCKOUT_SECONDS
            FAILED_ATTEMPTS[username_key] = state
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Security lockout activated after {MAX_ATTEMPTS} failed attempts. Locked for {LOCKOUT_SECONDS}s.",
            )
        FAILED_ATTEMPTS[username_key] = state
        remaining = MAX_ATTEMPTS - state["attempts"]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid username or password. ({remaining} attempts remaining before lockout)",
        )

    # Success: clear failed attempts
    FAILED_ATTEMPTS.pop(username_key, None)

    token = create_access_token(user.username)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserOut(
            id=user.id,
            username=user.username,
            role=user.role,
        ),
        message="Authentication successful",
    )

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    clean_username = req.username.strip()
    clean_code = req.recovery_code.strip()

    if clean_code not in VALID_RECOVERY_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Security Recovery Code. Contact administrator or use master PIN (e.g. 7777).",
        )

    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters long.",
        )

    # Ensure user exists
    user = await ensure_default_user(db)
    if clean_username.lower() != "sevenseas":
        stmt = select(User).where(User.username.ilike(clean_username))
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{clean_username}' not found.",
        )

    # Update password
    user.password_hash = get_password_hash(req.new_password)
    await db.commit()
    await db.refresh(user)

    # Clear any lockout
    FAILED_ATTEMPTS.pop(user.username.lower(), None)

    return {
        "status": "success",
        "message": f"Password for {user.username} has been updated successfully in database. You can now login.",
        "username": user.username,
    }

