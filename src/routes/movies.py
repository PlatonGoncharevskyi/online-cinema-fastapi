from decimal import Decimal
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, desc, asc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from database.db import get_db
from database.models.movies import MovieModel, CertificationModel, GenreModel, StarModel, DirectorModel
from schemas.movies import MovieListResponseSchema, MovieListItemSchema, MovieCreateSchema, MovieBaseSchema, \
    MovieDetailSchema, MovieUpdateSchema, StarSchema, GenreSchema, DirectorSchema, \
    StarGenreDirectorCreateSchema

router = APIRouter()

@router.get("/movies/", response_model=MovieListResponseSchema)
async def get_all_movies(
        #---Searching---
        name: Optional[str] = Query(None, description="Search by title movies"),
        description: Optional[str] = Query(None, description="Search by description movies"),
        star: Optional[str] = Query(None, description="Search by actor movies"),
        director: Optional[str] = Query(None, description="Search by director movies"),

        #---Filtering---
        year: Optional[int] = Query(None, description="Filter by year movies"),
        imdb: Optional[float] = Query(None, description="Filter by imdb movies"),

        #---Sorting---
        sort_by: Literal["year", "price", "imdb"] = Query(
            "year", description="Field to sort by"
        ),
        sort_order: Literal["asc", "desc"] = Query(
            "desc", description="Sort direction (asc/desc)"
        ),

        page: int = Query(1, ge=1, description="Page number (1-based index)"),
        per_page: int = Query(10, ge=1, le=20, description="Number of items per page"),
        db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    stmt = select(MovieModel)

    if name:
        stmt = stmt.where(MovieModel.name.ilike(f"%{name}%"))
    if description:
        stmt = stmt.where(MovieModel.description.ilike(f"%{description}%"))
    if star:
        stmt = stmt.join(MovieModel.stars).where(StarModel.name.ilike(f"%{star}%"))
    if director:
        stmt = stmt.join(MovieModel.directors).where(DirectorModel.name.ilike(f"%{director}%"))
    if year:
        stmt = stmt.where(MovieModel.year == year)
    if imdb:
        stmt = stmt.where(MovieModel.imdb >= imdb)

    stmt = stmt.distinct()

    offset = (page - 1) * per_page

    count_stmt = select(func.count()).select_from(stmt.subquery())
    result_count = await db.execute(count_stmt)
    total_items = result_count.scalar() or 0

    if not total_items:
        raise HTTPException(status_code=404, detail="No movies found.")

    sort_column = MovieModel.year  # Default

    if sort_by == "year":
        sort_column = MovieModel.year
    if sort_by == "price":
        sort_column = MovieModel.price
    if sort_by == "imdb":
        sort_column = MovieModel.imdb

    if sort_order == "desc":
        stmt = stmt.order_by(desc(sort_column))
    else:
        stmt = stmt.order_by(asc(sort_column))

    stmt = stmt.offset(offset).limit(per_page)

    result_movies = await db.execute(stmt)
    movies = result_movies.scalars().all()

    if not movies:
        raise HTTPException(status_code=404, detail="No movies found.")


    movie_list = [MovieListItemSchema.model_validate(movie) for movie in movies]

    total_pages = (total_items + per_page - 1) // per_page

    query_params = f"&per_page={per_page}"
    if name: query_params += f"&name={name}"
    if star: query_params += f"&actor={star}"
    if director: query_params += f"&director={director}"
    if year: query_params += f"&year={year}"
    if imdb: query_params += f"&imdb={imdb}"

    response = MovieListResponseSchema(
        movies=movie_list,
        prev_page=f"/theater/movies/?page={page - 1}{query_params}" if page > 1 else None,
        next_page=f"/theater/movies/?page={page + 1}{query_params}" if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )
    return response


@router.post("/movies/", response_model=MovieDetailSchema)
async def create_movie(
        movie_data: MovieCreateSchema,
        db: AsyncSession = Depends(get_db),
)-> MovieDetailSchema:
    existing_stmt = select(MovieModel).where(
        (MovieModel.name == movie_data.name),
        (MovieModel.year == movie_data.year)
    )
    existing_result = await db.execute(existing_stmt)
    existing_movie = existing_result.scalars().first()

    if existing_movie:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A movie with the name '{movie_data.name}' and release year"
                f"'{movie_data.year}' already exists."
            )
        )

    try:
        certification_stmt = select(CertificationModel).where(CertificationModel.name == movie_data.certification)
        certification_result = await db.execute(certification_stmt)
        certification = certification_result.scalars().first()
        if not certification:
            certification = CertificationModel(name=movie_data.certification)
            db.add(certification)
            await db.flush()

        genres = []
        for genre_name in movie_data.genres:
            genre_stmt = select(GenreModel).where(GenreModel.name == genre_name)
            genre_result = await db.execute(genre_stmt)
            genre = genre_result.scalars().first()

            if not genre:
                genre = GenreModel(name=genre_name)
                db.add(genre)
                await db.flush()
            genres.append(genre)

        stars = []
        for star_name in movie_data.stars:
            star_stmt = select(StarModel).where(StarModel.name == star_name)
            star_result = await db.execute(star_stmt)
            star = star_result.scalars().first()

            if not star:
                star = StarModel(name=star_name)
                db.add(star)
                await db.flush()
            stars.append(star)

        directors = []
        for director_name in movie_data.directors:
            director_stmt = select(DirectorModel).where(DirectorModel.name == director_name)
            director_result = await db.execute(director_stmt)
            director = director_result.scalars().first()

            if not director:
                director = DirectorModel(name=director_name)
                db.add(director)
                await db.flush()
            directors.append(director)

        movie = MovieModel(
            name=movie_data.name,
            year=movie_data.year,
            time=movie_data.time,
            imdb=movie_data.imdb,
            votes=movie_data.votes,
            meta_score=movie_data.meta_score,
            gross=movie_data.gross,
            description=movie_data.description,
            price=movie_data.price,
            genres=genres,
            stars=stars,
            directors=directors,
            certification=certification,
        )

        db.add(movie)
        await db.commit()
        await db.refresh(movie, ["genres", "stars", "directors"])

        return MovieDetailSchema.model_validate(movie)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")


@router.get("/movies/{movie_id}/", response_model=MovieDetailSchema)
async def get_movie_by_id(
        movie_id: int,
        db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(MovieModel)
        .options(
            joinedload(MovieModel.certification),
            joinedload(MovieModel.genres),
            joinedload(MovieModel.stars),
            joinedload(MovieModel.directors),
        )
        .where(MovieModel.id == movie_id)
    )
    existing_result = await db.execute(stmt)
    existing_movie = existing_result.scalars().first()

    if not existing_movie:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A movie with the name '{MovieModel.name}' didnt found"
            )
        )

    return MovieDetailSchema.model_validate(existing_movie)


@router.delete("/movies/{movie_id}/")
async def delete_movie(
        movie_id: int,
        db: AsyncSession = Depends(get_db),
):
    existing_stmt = select(MovieModel).where(MovieModel.id == movie_id)
    existing_result = await db.execute(existing_stmt)
    existing_movie = existing_result.scalars().first()

    if not existing_movie:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A movie with the name '{MovieModel.name}' didnt found"
            )
        )
    try:
        await db.delete(existing_movie)
        await db.commit()
        await db.refresh(existing_movie)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")

    return {"detail": "Movie deleted successfully."}

@router.patch("/movies/{movie_id}/")
async def update_movie(
        movie_id: int,
        movie_data: MovieUpdateSchema,
        db: AsyncSession = Depends(get_db),
):
    existing_stmt = select(MovieModel).where(MovieModel.id == movie_id)
    existing_result = await db.execute(existing_stmt)
    existing_movie = existing_result.scalars().first()

    if not existing_movie:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A movie with the name '{movie_data.name}' didnt found"
            )
        )

    for field, value in movie_data.model_dump(exclude_unset=True).items():
        setattr(existing_movie, field, value)

    try:
        await db.commit()
        await db.refresh(existing_movie)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")

    return {"detail": "Movie updated successfully."}


@router.get("/stars/", response_model=List[StarSchema])
async def get_stars(db: AsyncSession = Depends(get_db)):
    stmt = select(StarModel)
    result = await db.execute(stmt)
    stars = result.scalars().all()
    if not stars:
        raise HTTPException(status_code=404, detail="No stars found")
    return stars


@router.post("/stars/", response_model=StarSchema)
async def create_star(
        star_data: StarGenreDirectorCreateSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(StarModel).where(StarModel.name == star_data.name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Star '{star_data.name}' already exists")

    try:
        star = StarModel(name=star_data.name)
        db.add(star)
        await db.commit()
        await db.refresh(star)
        return star
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid data")


@router.put("/stars/{star_id}/", response_model=StarSchema)
async def update_star(
        star_id: int,
        star_data: StarSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(StarModel).where(StarModel.id == star_id)
    result = await db.execute(stmt)
    star = result.scalar_one_or_none()

    if not star:
        raise HTTPException(status_code=404, detail="Star not found")

    star.name = star_data.name
    try:
        await db.commit()
        await db.refresh(star)
        return star
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Name already taken")


@router.delete("/stars/{star_id}/")
async def delete_star(
        star_id: int,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(StarModel).where(StarModel.id == star_id)
    result = await db.execute(stmt)
    star = result.scalar_one_or_none()

    if not star:
        raise HTTPException(status_code=404, detail="Star not found")

    try:
        await db.delete(star)
        await db.commit()
        return {"detail": "Star deleted successfully"}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Error deleting star")



@router.get("/genres/", response_model=List[GenreSchema])
async def get_genres(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(GenreModel, func.count(MovieModel.id).label("movie_count"))
        .outerjoin(GenreModel.movies)
        .group_by(GenreModel.id)
    )
    result = await db.execute(stmt)
    data = result.all()

    if not data:
        raise HTTPException(status_code=404, detail="No genres found")

    response = []
    for genre, count in data:
        genre_dict = {
            "id": genre.id,
            "name": genre.name,
            "movie_count": count
        }
        response.append(genre_dict)

    return response



@router.post("/genres/", response_model=GenreSchema)
async def create_genre(
        genre_data: StarGenreDirectorCreateSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(GenreModel).where(GenreModel.name == genre_data.name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Genre '{genre_data.name}' already exists")

    try:
        genre = GenreModel(name=genre_data.name)
        db.add(genre)
        await db.commit()
        await db.refresh(genre)
        return genre
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid data")


@router.put("/genres/{genre_id}/", response_model=GenreSchema)
async def update_genre(
        genre_id: int,
        genre_data: StarGenreDirectorCreateSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(GenreModel).where(GenreModel.id == genre_id)
    result = await db.execute(stmt)
    genre = result.scalar_one_or_none()
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")

    genre.name = genre_data.name
    try:
        await db.commit()
        await db.refresh(genre)
        return genre
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Name taken")


@router.delete("/genres/{genre_id}/")
async def delete_genre(genre_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(GenreModel).where(GenreModel.id == genre_id)
    result = await db.execute(stmt)
    genre = result.scalar_one_or_none()
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")

    try:
        await db.delete(genre)
        await db.commit()
        return {"detail": f"Genre '{genre}' deleted successfully"}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Error deleting genre")



@router.get("/directors/", response_model=List[DirectorSchema])
async def get_directors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DirectorModel))
    directors = result.scalars().all()
    if not directors:
        raise HTTPException(status_code=404, detail="No directors found")
    return directors


@router.post("/directors/", response_model=DirectorSchema)
async def create_director(
        director_data: StarGenreDirectorCreateSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(DirectorModel).where(DirectorModel.name == director_data.name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Director '{director_data.name}' already exists")

    try:
        director = DirectorModel(name=director_data.name)
        db.add(director)
        await db.commit()
        await db.refresh(director)
        return director
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid data")


@router.put("/directors/{director_id}/", response_model=DirectorSchema)
async def update_director(
        director_id: int,
        director_data: DirectorSchema,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(DirectorModel).where(DirectorModel.id == director_id)
    result = await db.execute(stmt)
    director = result.scalar_one_or_none()
    if not director:
        raise HTTPException(status_code=404, detail="Director not found")

    director.name = director_data.name
    try:
        await db.commit()
        await db.refresh(director)
        return director
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Name taken")


@router.delete("/directors/{director_id}/")
async def delete_director(director_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(DirectorModel).where(DirectorModel.id == director_id)
    result = await db.execute(stmt)
    director = result.scalar_one_or_none()
    if not director:
        raise HTTPException(status_code=404, detail="Director not found")

    try:
        await db.delete(director)
        await db.commit()
        return {"detail": "Director deleted successfully"}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Error deleting director")