from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.dependencies import logger
from app.models.exceptions import ApiException, ApiExceptionType, InternalServerError
from app.routers import auth, files, users

app = FastAPI(
    title="Practice API",
    description=(
        "REST API with JWT auth, refresh-token rotation with reuse detection, "
        "OTP-based email verification / password reset, and file storage."
    ),
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(files.router)

@app.exception_handler(ApiException)
def api_exception_handler(request: Request, exception: ApiException):
    # 5xx is our bug and needs a traceback; 4xx are expected (wrong password,
    # 404, etc.), so log them briefly to avoid cluttering logs with stack traces.
    if exception.status_code >= 500:
        logger.exception(exception)
    else:
        logger.warning(str(exception))
    return JSONResponse(
        status_code=exception.status_code,
        content=exception.to_content(),
    )

@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exception: RequestValidationError):
    # Normalize FastAPI's default 422 ({"detail": [...]}) into our unified shape
    # {message, type, body}, so the client has ONE error format for every case.
    return JSONResponse(
        status_code=422,
        content={
            "message": "Validation error",
            "type": ApiExceptionType.VALIDATION_ERROR,
            "body": jsonable_encoder(exception.errors()),
        },
    )

@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exception: Exception):
    error = InternalServerError()
    logger.exception(exception)
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_content(),
    )

@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}

