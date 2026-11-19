"""Authenticated owner catalog editor. Each successful mutation commits atomically."""

from typing import Any, Callable, TypeVar
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.modules.content.management import (
    Action,
    BookFields,
    ContentConflict,
    ContentNotFound,
    OwnerContentRepository,
    UnitCreate,
    UnitFields,
)
from app.modules.content.router import content_connection
from app.modules.operations.auth import require_admin_auth

router = APIRouter(
    prefix="/admin/content",
    tags=["Owner Content Management"],
    dependencies=[Depends(require_admin_auth)],
)
repo = OwnerContentRepository()


T = TypeVar("T")


def _call(method: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return method(*args, **kwargs)
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ContentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except psycopg.IntegrityError:
        raise HTTPException(
            status_code=409, detail="Content conflicts with existing numbering or ranges"
        ) from None


@router.get("/books")
def list_books(conn: psycopg.Connection[Any] = Depends(content_connection)) -> list[dict[str, Any]]:
    return repo.list_books(conn)


@router.post("/books", status_code=201)
def create_book(
    fields: BookFields, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.create_book, conn, fields)


@router.get("/books/{book_id}")
def get_book(
    book_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.get_book, conn, book_id)


@router.patch("/books/{book_id}")
def edit_book(
    book_id: UUID, fields: BookFields, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.edit, conn, book_id, fields, book=True)


@router.get("/books/{book_id}/units")
def list_units(
    book_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> list[dict[str, Any]]:
    return _call(repo.list_units, conn, book_id)


@router.get("/books/{book_id}/audit")
def book_audit(
    book_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> list[dict[str, Any]]:
    _call(repo.get_book, conn, book_id)
    return repo.audit(conn, book_id)


@router.post("/books/{book_id}/{action}")
def book_action(
    book_id: UUID, action: Action, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.transition, conn, book_id, action, book=True)


@router.post("/units", status_code=201)
def create_unit(
    fields: UnitCreate, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.create_unit, conn, fields)


@router.get("/units/{unit_id}")
def get_unit(
    unit_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.get_unit, conn, unit_id)


@router.patch("/units/{unit_id}")
def edit_unit(
    unit_id: UUID, fields: UnitFields, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.edit, conn, unit_id, fields, book=False)


@router.get("/units/{unit_id}/audit")
def unit_audit(
    unit_id: UUID, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> list[dict[str, Any]]:
    _call(repo.get_unit, conn, unit_id)
    return repo.audit(conn, unit_id)


@router.post("/units/{unit_id}/{action}")
def unit_action(
    unit_id: UUID, action: Action, conn: psycopg.Connection[Any] = Depends(content_connection)
) -> dict[str, Any]:
    return _call(repo.transition, conn, unit_id, action, book=False)
