from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.models.exceptions import ApiException, InternalServerError
from app.routers import auth, users
from app.dependencies import logger

app = FastAPI()

app.include_router(auth.router)
app.include_router(users.router)

@app.exception_handler(ApiException)
def api_exception_handler(request: Request, exception: ApiException):
    logger.exception(exception)
    return JSONResponse(
        status_code = exception.status_code,
        content = exception.to_content()
    )

@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exception: Exception):
    error = InternalServerError()
    logger.exception(error)
    return JSONResponse(
        status_code = error.status_code,
        content = error.to_content()
    )

@app.get("/")
async def root():
    return {"message": "Hello Bigger Applications!"}

