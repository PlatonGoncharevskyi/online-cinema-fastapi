from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import security
from database.db import get_db
from database.models.accounts import UserModel, UserGroupEnum

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(
        token: Annotated[str, Depends(oauth2_scheme)],
        db: AsyncSession = Depends(get_db)
) -> UserModel:
    payload = security.SecurityUtils.decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(UserModel).options(joinedload(UserModel.group)).where(UserModel.id == int(user_id))
    result = await db.execute(stmt)
    user = result.scalars().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_admin(current_user: UserModel = Depends(get_current_user)) -> UserModel:
    if current_user.group.name != UserGroupEnum.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Not enough permissions. Admin access required.")

    return current_user


async def get_current_moderator(current_user: UserModel = Depends(get_current_user)) -> UserModel:
    allowed_groups = [UserGroupEnum.MODERATOR, UserGroupEnum.ADMIN]

    if current_user.group.name not in allowed_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions. Moderator access required."
        )

    return current_user

