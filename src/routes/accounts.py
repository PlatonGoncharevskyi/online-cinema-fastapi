import secrets
import bcrypt
from datetime import datetime, timezone, timedelta
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import security
from config.dependencies import get_current_user
from database.db import get_db
from database.models.accounts import UserModel, UserGroupModel, UserGroupEnum, ActivationTokenModel, \
    PasswordResetTokenModel, RefreshTokenModel
from schemas.accounts import UserRegistrationResponseSchema, UserRegistrationRequestSchema, TokenRefreshResponseSchema, \
    MessageResponseSchema, UserActivationRequestSchema, PasswordResetRequestSchema, PasswordResetCompleteRequestSchema, \
    UserLoginResponseSchema, UserLoginRequestSchema, TokenRefreshRequestSchema, UserChangePassword, \
    UserLogoutRequestSchema, UserActivationResendRequestSchema

router = APIRouter()


@router.post("/register/", response_model=UserRegistrationResponseSchema)
async def register_user(
        user_data: UserRegistrationRequestSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(UserModel).where(UserModel.email == user_data.email)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {user_data.email} already exists."
        )

    stmt = select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    result = await db.execute(stmt)
    user_group = result.scalars().first()

    if not user_group:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group not found."
        )

    hashed_password = security.security.get_password_hash(user_data.password)

    try:
        new_user = UserModel(
            email=user_data.email,
            _hashed_password=hashed_password,
            group_id=user_group.id,
        )
        db.add(new_user)
        await db.flush()
        token_str = secrets.token_urlsafe(32)
        activation_token = ActivationTokenModel(user_id=new_user.id, token=token_str)
        db.add(activation_token)

        await db.commit()
        await db.refresh(new_user)

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation."
        )

    #That instead of email sending
    print(f"DEBUG: Activation link: http://127.0.0.1:8000/accounts/activate/{token_str}")

    return UserRegistrationResponseSchema(id=new_user.id, email=new_user.email)


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account",
    status_code=status.HTTP_200_OK,
)
async def activate_account(
        activation_data: UserActivationRequestSchema,
        db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    stmt = (
        select(ActivationTokenModel)
        .options(joinedload(ActivationTokenModel.user))
        .join(UserModel)
        .where(
            UserModel.email == activation_data.email,
            ActivationTokenModel.token == activation_data.token
        )
    )
    result = await db.execute(stmt)
    token_record = result.scalars().first()

    now_utc = datetime.now(timezone.utc)
    if not token_record or cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc) < now_utc:
        if token_record:
            await db.delete(token_record)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token."
        )

    user = token_record.user
    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active."
        )

    user.is_active = True
    await db.delete(token_record)
    await db.commit()

    return MessageResponseSchema(message="User account activated successfully.")


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request Password Reset Token",
    status_code=status.HTTP_200_OK,
)
async def request_password_reset_token(
        data: PasswordResetRequestSchema,
        db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.is_active:
        return MessageResponseSchema(
            message="If you are registered, you will receive an email with instructions."
        )

    await db.execute(delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id))

    reset_token = PasswordResetTokenModel(user_id=cast(int, user.id))
    db.add(reset_token)
    await db.commit()

    return MessageResponseSchema(
        message="If you are registered, you will receive an email with instructions."
    )


@router.post(
    "/reset-password/complete/",
    response_model=MessageResponseSchema,
    summary="Reset User Password",
    status_code=status.HTTP_200_OK,
)
async def reset_password(
        data: PasswordResetCompleteRequestSchema,
        db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or token."
        )

    stmt = select(PasswordResetTokenModel).filter_by(user_id=user.id)
    result = await db.execute(stmt)
    token_record = result.scalars().first()

    if not token_record or token_record.token != data.token:
        if token_record:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or token."
        )

    expires_at = cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or token."
        )

    try:
        new_hashed_password = security.security.get_password_hash(data.password)
        user._hashed_password = new_hashed_password

        await db.delete(token_record)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password."
        )

    return MessageResponseSchema(message="Password reset successfully.")


@router.post(
    "/login/",
    response_model=UserLoginResponseSchema,
    summary="User Login",
    status_code=status.HTTP_201_CREATED,
)
async def login_user(
        login_data: UserLoginRequestSchema,
        db: AsyncSession = Depends(get_db),
) -> UserLoginResponseSchema:
    stmt = select(UserModel).filter_by(email=login_data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not security.security.verify_password(login_data.password, user._hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )

    refresh_token_expires = timedelta(days=security.REFRESH_TOKEN_EXPIRE_DAYS)

    jwt_refresh_token = security.security.create_token(
        data={"sub": str(user.id), "type": "refresh"},
        expires_delta=refresh_token_expires
    )

    try:
        refresh_token_record = RefreshTokenModel(
            user_id=user.id,
            token=jwt_refresh_token,
            expires_at=datetime.now(timezone.utc) + refresh_token_expires
        )
        db.add(refresh_token_record)
        await db.flush()
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    jwt_access_token = security.security.create_token(
        data={"sub": str(user.id), "type": "access"},
        expires_delta=access_token_expires
    )

    return UserLoginResponseSchema(
        access_token=jwt_access_token,
        refresh_token=jwt_refresh_token,
    )


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="Logout user",
    status_code=status.HTTP_200_OK
)
async def logout_user(
        logout_data: UserLogoutRequestSchema,
        db: AsyncSession = Depends(get_db),
):
    stmt = delete(RefreshTokenModel).where(RefreshTokenModel.token == logout_data.refresh_token)
    await db.execute(stmt)
    await db.commit()
    return MessageResponseSchema(message="Logged out successfully.")



@router.post(
    "/refresh/",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh Access Token",
    status_code=status.HTTP_200_OK,
)
async def refresh_access_token(
        token_data: TokenRefreshRequestSchema,
        db: AsyncSession = Depends(get_db),
) -> TokenRefreshResponseSchema:
    payload = security.security.decode_token(token_data.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    stmt = select(RefreshTokenModel).filter_by(token=token_data.refresh_token)
    result = await db.execute(stmt)
    refresh_token_record = result.scalars().first()

    if not refresh_token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found or revoked.",
        )

    stmt = select(UserModel).filter_by(id=int(user_id))
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = security.security.create_token(
        data={"sub": str(user.id), "type": "access"},
        expires_delta=access_token_expires
    )

    return TokenRefreshResponseSchema(access_token=new_access_token)


@router.post("/change_password/",
             response_model=MessageResponseSchema,
             summary="Change password",
             status_code=status.HTTP_200_OK,
             )
async def user_change_password(
        user_data: UserChangePassword,
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user)
) -> MessageResponseSchema:
    if not security.security.verify_password(user_data.old_password, current_user._hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Incorrect old password")

    new_hash_pass = security.security.get_password_hash(user_data.new_password)
    current_user._hashed_password = new_hash_pass

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return MessageResponseSchema(
        message="Password changed successfully"
    )

@router.post(
    "/activate/resend/",
    response_model=MessageResponseSchema,
    summary="Resend Activation Token",
    status_code=status.HTTP_200_OK,
)
async def resend_activation_token(
        data: UserActivationResendRequestSchema,
        db: AsyncSession = Depends(get_db),
):
    stmt = select(UserModel).where(UserModel.email == data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or user.is_active:
         return MessageResponseSchema(message="If the user exists and is not active, a new token has been sent.")

    await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id))

    token_str = secrets.token_urlsafe(32)
    new_token = ActivationTokenModel(user_id=user.id, token=token_str)
    db.add(new_token)
    await db.commit()

    print(f"DEBUG: New link: http://127.0.0.1/accounts/activate/{token_str}")

    return MessageResponseSchema(message="If the user exists and is not active, a new token has been sent.")