from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: Literal["local", "dev", "prod"] = "local"
    APP_NAME: str = "PharmaReg"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    DATABASE_URL: str = "mysql+pymysql://root:pharmareg@127.0.0.1:3306/pharmareg?charset=utf8mb4"
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    MILVUS_URI: str = "http://127.0.0.1:19530"

    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    TENANT_MODE: Literal["single", "multi"] = "single"

    LLM_PROVIDER: str = "local"
    LLM_BASE_URL: str = "http://127.0.0.1:8080/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "qwen2.5-14b"

    EMBEDDING_MODEL: str = "bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_BASE_URL: str = "http://127.0.0.1:8081"
    # 本地落地：规格推荐 bge-reranker-v2-m3，本地模型仓以 bge-reranker-large 同族替代（与 deploy/models_server.py 一致）
    RERANK_MODEL: str = "bge-reranker-large"
    RERANK_BASE_URL: str = "http://127.0.0.1:8081"

    FEEDBACK_EVAL_SAMPLE: int = 100

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
