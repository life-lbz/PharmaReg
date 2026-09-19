from typing import Any

from pymilvus import DataType, MilvusClient

from app.core.config import settings
from app.core.logging import logger

_client: MilvusClient | None = None


def get_milvus() -> MilvusClient:
    global _client
    if _client is None:
        _client = MilvusClient(uri=settings.MILVUS_URI)
    return _client


def ensure_collection(client: MilvusClient, collection_name: str, dim: int = 1024):
    if client.has_collection(collection_name):
        ensure_index(client, collection_name)
        return
    schema = client.create_schema(auto_id=True, enable_dynamic_field=True)
    schema.add_field("id", DataType.INT64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("entity_id", DataType.INT64)
    schema.add_field("text", DataType.VARCHAR, max_length=4096)
    schema.add_field("doc_version", DataType.VARCHAR, max_length=64)
    schema.add_field("tenant_id", DataType.INT64)
    client.create_collection(collection_name, schema=schema)
    ensure_index(client, collection_name)


def ensure_index(client: MilvusClient, collection_name: str):
    """Milvus load/search 依赖向量索引：缺失时补建 AUTOINDEX(余弦)。"""
    try:
        indexes = client.list_indexes(collection_name)
        if indexes:
            return
    except Exception:
        pass
    try:
        idx_params = client.prepare_index_params()
        idx_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_index(collection_name, idx_params)
    except Exception as e:
        logger.warning("collection_index_failed", collection=collection_name, error=str(e))


def _is_loaded(client: MilvusClient, collection_name: str) -> bool:
    try:
        st = client.get_load_state(collection_name=collection_name)
        val = st
        if hasattr(st, "state"):
            val = st.state
        if isinstance(val, dict):
            val = val.get("state", "")
        return "loaded" in str(val).lower()
    except Exception:
        return False


def ensure_loaded(client: MilvusClient, collection_name: str, timeout: int = 30):
    """集合必须处于 loaded 状态才能 search；load 为异步，轮询等待。"""
    import time

    if _is_loaded(client, collection_name):
        return
    try:
        client.load_collection(collection_name)
    except Exception as e:
        logger.warning("collection_load_failed", collection=collection_name, error=str(e))
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_loaded(client, collection_name):
            return
        time.sleep(0.5)
    logger.warning("collection_load_timeout", collection=collection_name)


async def search_vectors(
    collection_name: str,
    query_vector: list[float],
    top_k: int = 40,
    tenant_id: int = 1,
) -> list[dict[str, Any]]:
    client = get_milvus()
    if not client.has_collection(collection_name):
        logger.warning("collection_not_found", collection=collection_name)
        return []

    ensure_index(client, collection_name)
    ensure_loaded(client, collection_name)
    results = client.search(
        collection_name=collection_name,
        data=[query_vector],
        limit=top_k,
        filter=f"tenant_id == {tenant_id}",
        output_fields=["entity_id", "text", "doc_version"],
    )

    hits = results[0] if results else []
    return [
        {
            "entity_id": hit.entity.get("entity_id"),
            "text": hit.entity.get("text", ""),
            "doc_version": hit.entity.get("doc_version", ""),
            "score": hit.distance,
        }
        for hit in hits
    ]


async def insert_vectors(
    collection_name: str,
    vectors: list[list[float]],
    metadata: list[dict[str, Any]],
):
    client = get_milvus()
    ensure_collection(client, collection_name, len(vectors[0]) if vectors else 1024)
    data = [
        {"vector": vec, **meta}
        for vec, meta in zip(vectors, metadata)
    ]
    client.insert(collection_name=collection_name, data=data)
    ensure_loaded(client, collection_name)
