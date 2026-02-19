from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CommentCreateSchema(BaseModel):
    description: str = Field(..., min_length=1, max_length=1000)



class CommentListItemResponseSchema(BaseModel):
    id: int
    description: str
    created_at: datetime
    user_id: int
    movie_id: int


    class Config:
        from_attributes = True


class CommentListResponseSchema(BaseModel):
    comments: List[CommentListItemResponseSchema]
    prev_page: Optional[str]
    next_page: Optional[str]
    total_pages: int
    total_items: int

    model_config = {
        "from_attributes": True
    }
