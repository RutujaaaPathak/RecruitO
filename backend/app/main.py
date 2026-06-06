# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app import models
from app.routes import auth_routes

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Enable CORS (VERY IMPORTANT for frontend connection)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # React Vite default
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(auth_routes.router)

@app.get("/")
def read_root():
    return {"message": "RecruitO backend running"}