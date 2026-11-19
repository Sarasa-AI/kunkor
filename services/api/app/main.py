from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.authz import authorization_lifespan
from app.core.config import settings
from app.core.http_security import ContainHTTPFailures, install_private_access_logging
from app.modules.consultation.router import router as consultation_router
from app.modules.content.admin_router import router as content_admin_router
from app.modules.content.router import router as content_router
from app.modules.identity.router import router as identity_router
from app.modules.operations.router import router as operations_router

app = FastAPI(
    title="Kunkor Educational Platform API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=authorization_lifespan,
)

app.include_router(consultation_router)
app.include_router(content_router)
app.include_router(content_admin_router)
app.include_router(identity_router)
app.include_router(operations_router)

install_private_access_logging()
app.add_middleware(ContainHTTPFailures)


# SEC-01: Explicit origin whitelist; wildcard prohibited with credentials.
origins = settings.CORS_ALLOWED_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=bool(origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
        "Idempotency-Key",
        "X-Student-Id",
        "X-Admin-Api-Key",
        "X-Telegram-Bot-Api-Secret-Token",
    ],
)


@app.get("/healthz", tags=["System"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Invalid request"})
