"""Central typed configuration for every SPECTRA service.

One ``Settings`` object is built from the environment (``.env``) and shared by the
API, worker, ingestion pipelines, agent and evaluation harness.  Nothing in the
codebase reads ``os.environ`` directly - that keeps deployment-mode differences
(laptop vs cluster) in exactly one place.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class DeploymentMode(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class RelationalBackend(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class VectorBackend(str, Enum):
    EMBEDDED = "embedded"
    QDRANT = "qdrant"


class LexicalBackend(str, Enum):
    EMBEDDED = "embedded"
    OPENSEARCH = "opensearch"


class GraphBackend(str, Enum):
    EMBEDDED = "embedded"
    NEO4J = "neo4j"


class ObjectBackend(str, Enum):
    FILESYSTEM = "filesystem"
    S3 = "s3"


class CacheBackend(str, Enum):
    MEMORY = "memory"
    REDIS = "redis"


class ModelProfile(str, Enum):
    RTX4090 = "rtx4090"
    CPU = "cpu"
    CLOUD = "cloud"


class ModelRuntime(str, Enum):
    AUTO = "auto"
    LLAMA_CPP = "llama_cpp"
    VLLM = "vllm"
    OLLAMA = "ollama"
    OPENAI = "openai"
    TRANSFORMERS = "transformers"
    DETERMINISTIC = "deterministic"


class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("SPECTRA_ENV_FILE", str(REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    # -- application ------------------------------------------------------
    app_env: str = "development"
    deployment_mode: DeploymentMode = DeploymentMode.DEVELOPMENT
    log_level: str = "INFO"
    log_format: str = "console"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    # -- storage backends -------------------------------------------------
    relational_backend: RelationalBackend = RelationalBackend.SQLITE
    vector_backend: VectorBackend = VectorBackend.EMBEDDED
    lexical_backend: LexicalBackend = LexicalBackend.EMBEDDED
    graph_backend: GraphBackend = GraphBackend.EMBEDDED
    object_backend: ObjectBackend = ObjectBackend.FILESYSTEM
    cache_backend: CacheBackend = CacheBackend.MEMORY

    postgres_url: str = "postgresql+psycopg://spectra:spectra@localhost:5432/spectra"
    sqlite_url: str = "sqlite+aiosqlite:///./data/runtime/spectra.db"
    qdrant_url: str = "http://localhost:6333"
    opensearch_url: str = "http://localhost:9200"
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "spectra-neo4j"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "spectra"
    minio_secret_key: str = "spectra-minio"
    minio_bucket: str = "spectra"
    minio_region: str = "us-east-1"

    data_dir: Path = REPO_ROOT / "data"
    model_dir: Path = REPO_ROOT / "models"

    # -- model runtime ----------------------------------------------------
    model_profile: ModelProfile = ModelProfile.RTX4090
    model_runtime: ModelRuntime = ModelRuntime.AUTO
    gpu_vram_budget_mb: int = 22000
    model_idle_evict_seconds: int = 300
    model_load_timeout_seconds: int = 300
    model_call_timeout_seconds: int = 120
    model_max_retries: int = 2

    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8001/v1"
    openai_base_url: str = ""
    openai_api_key: str = ""

    fast_brain_model: str = "Qwen3-8B-Q4_K_M"
    deep_brain_model: str = "Qwen3-30B-A3B-Instruct-2507-Q4_K_M"
    vision_model: str = "Qwen3-VL-8B-Instruct-Q4_K_M"
    embedding_model: str = "BAAI/bge-m3"
    mm_embedding_model: str = "Qwen3-VL-Embedding-2B"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    whisper_model: str = "large-v3"
    ocr_engine: str = "auto"

    # -- agent flags ------------------------------------------------------
    enable_document_agent: bool = True
    enable_image_agent: bool = True
    enable_video_agent: bool = True
    enable_audio_agent: bool = True
    enable_database_agent: bool = True
    enable_graph_agent: bool = True
    enable_entity_resolution: bool = True
    enable_claim_builder: bool = True
    enable_disproof_agent: bool = True
    enable_verifier: bool = True
    fast_mode_enabled: bool = True
    deep_mode_enabled: bool = True

    # -- budgets ----------------------------------------------------------
    fast_max_tool_calls: int = 5
    fast_max_latency_seconds: float = 3.0
    deep_max_tool_calls: int = 30
    deep_max_latency_seconds: float = 60.0
    deep_max_iterations: int = 8
    candidate_pool_size: int = 200
    rerank_top_k: int = 40
    evidence_top_k: int = 12
    sufficiency_threshold: float = 0.62

    # -- security ---------------------------------------------------------
    max_upload_bytes: int = 536_870_912
    sql_query_timeout_seconds: int = 10
    sql_max_rows: int = 500
    antivirus_hook: str = ""
    default_role: Role = Role.ANALYST
    application_base_url: str = "http://localhost:3001"

    @field_validator("data_dir", "model_dir", mode="before")
    @classmethod
    def _resolve_path(cls, value: object) -> Path:
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    # -- derived ----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        if self.relational_backend is RelationalBackend.POSTGRES:
            return self.postgres_url
        url = self.sqlite_url
        if url.startswith("sqlite") and "///" in url:
            prefix, _, rel = url.partition("///")
            if not rel.startswith("/"):
                resolved = (REPO_ROOT / rel).resolve()
                resolved.parent.mkdir(parents=True, exist_ok=True)
                url = f"{prefix}///{resolved}"
        return url

    @property
    def runtime_dir(self) -> Path:
        path = self.data_dir / "runtime"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def upload_dir(self) -> Path:
        path = self.data_dir / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def processed_dir(self) -> Path:
        path = self.data_dir / "processed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def object_root(self) -> Path:
        path = self.data_dir / "objects"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def agent_flags(self) -> dict[str, bool]:
        """Feature-flag view used by the Brain and the Agent Control Center."""
        return {
            "document": self.enable_document_agent,
            "image": self.enable_image_agent,
            "video": self.enable_video_agent,
            "audio": self.enable_audio_agent,
            "database": self.enable_database_agent,
            "graph": self.enable_graph_agent,
            "entity_resolution": self.enable_entity_resolution,
            "claim": self.enable_claim_builder,
            "disproof": self.enable_disproof_agent,
            "verifier": self.enable_verifier,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
