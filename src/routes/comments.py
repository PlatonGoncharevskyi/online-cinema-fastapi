from itertools import count
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config.dependencies import get_current_user
from database.db import get_db
from database.models.accounts import UserModel
from database.models.comments import CommentModel
from database.models.movies import MovieModel
from schemas.comments import CommentListResponseSchema, CommentListItemResponseSchema, CommentCreateSchema

router = APIRouter()

@router.get("/comments/{movie_id}/", response_model=CommentListResponseSchema)
async def get_comments_by_movie_id(
        movie_id: int,
        page: int = Query(1, ge=1, description="Page number (1-based index)"),
        per_page: int = Query(10, ge=1, le=20, description="Number of items per page"),
        db: AsyncSession = Depends(get_db),
):
    count_stmt = select(func.count()).select_from(CommentModel).where(CommentModel.movie_id == movie_id)
    total_items = await db.scalar(count_stmt) or 0

    if total_items == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comments not found")

    offset = (page - 1) * per_page
    total_pages = (total_items + per_page - 1) // per_page

    stmt = (
        select(CommentModel)
        .options(joinedload(CommentModel.user))
        .where(CommentModel.movie_id == movie_id)
        .order_by(desc(CommentModel.created_at))
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(stmt)
    comments = result.scalars().all()

    comment_list = [CommentListItemResponseSchema.model_validate(comment) for comment in comments]

    query_params = f"&per_page={per_page}"
    prev_page_link = f"/theater/comments/{movie_id}/?page={page - 1}{query_params}" if page > 1 else None
    next_page_link = f"/theater/comments/{movie_id}/?page={page + 1}{query_params}" if page < total_pages else None

    return CommentListResponseSchema(
        comments=comment_list,
        prev_page=prev_page_link,
        next_page=next_page_link,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post("/write_comment/{movie_id}/", status_code=status.HTTP_201_CREATED)
async def write_comment(
        movie_id: int,
        comment_data: CommentCreateSchema,
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user)
):
    movie = await db.get(MovieModel, movie_id)

    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movie with id {movie_id} not found"
        )

    try:
        comment = CommentModel(
            movie_id=movie_id,
            user_id=current_user.id,
            description=comment_data.description
        )
        db.add(comment)
        await db.commit()
        await db.refresh(comment)
        return {"detail": "Comment successfully sended"}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid data")







