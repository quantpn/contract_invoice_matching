"""RAG Source and Embedding service refactored directly from:
- et-addons/ai/models/ai_embedding.py
- et-addons/ai/models/ai_agent_source.py
"""
from collections import defaultdict
import logging
from requests.exceptions import RequestException
from sqlalchemy.orm import Session

from ..core.attachment_processor import chunk_text
from ..core.exceptions import UserError
from ..core.llm_api_service import LLMApiService
from ..core.llm_providers import (
    get_embedding_config,
    get_embedding_model,
    get_provider,
    get_provider_for_embedding_model,
)
from ..domain.field_vector import cosine_similarity
from ..domain.models import AIAgent, AIAgentSource, AIEmbedding

_logger = logging.getLogger(__name__)


class EmbeddingService:
    """Implements AIEmbedding & AIAgentSource RAG pipeline identical to Odoo-ET."""

    DIMENSIONS = 1536

    @classmethod
    def get_dimensions(cls) -> int:
        """Refactored from AIEmbedding._get_dimensions."""
        return cls.DIMENSIONS

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Refactored from AIEmbedding._estimate_tokens."""
        return len(text) // 4 if text else 0

    @classmethod
    def create_batches(cls, embeddings: list[AIEmbedding], provider: str) -> list[list[AIEmbedding]]:
        """Group embeddings into batches respecting provider limits (AIEmbedding._create_batches)."""
        config = get_embedding_config(provider)
        max_batch_size = config["max_batch_size"]
        max_tokens = config["max_tokens_per_request"]

        batches: list[list[AIEmbedding]] = []
        current_batch: list[AIEmbedding] = []
        current_batch_tokens = 0

        for embedding in embeddings:
            content_tokens = cls.estimate_tokens(embedding.content)
            if (len(current_batch) >= max_batch_size) or (
                current_batch_tokens + content_tokens > max_tokens
            ):
                if current_batch:
                    batches.append(current_batch)
                current_batch = []
                current_batch_tokens = 0

            current_batch.append(embedding)
            current_batch_tokens += content_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    @classmethod
    def get_source_embeddings_status(
        cls, db: Session, source: AIAgentSource, embedding_model: str
    ) -> dict:
        """Refactored from AIAgentSource._get_source_embeddings_status."""
        embedding_chunks = (
            db.query(AIEmbedding)
            .filter(
                AIEmbedding.checksum == source.checksum,
                AIEmbedding.embedding_model == embedding_model,
            )
            .all()
        )
        if not embedding_chunks:
            return {"has_chunks": False}

        has_failed = any(e.has_embedding_generation_failed for e in embedding_chunks)
        has_missing = any(not e.embedding_vector for e in embedding_chunks)
        return {
            "has_chunks": True,
            "has_failed": has_failed,
            "has_missing": has_missing,
        }

    @classmethod
    def update_source_status(
        cls, db: Session, source: AIAgentSource, embedding_model: str
    ) -> bool:
        """Refactored from AIAgentSource._update_source_status."""
        embedding_info = cls.get_source_embeddings_status(db, source, embedding_model)
        if not embedding_info["has_chunks"]:
            return False
        if embedding_info.get("has_failed"):
            source.status = "failed"
            source.is_active = False
            source.error_details = "Embedding generation failed using the current LLM model selected."
        elif embedding_info.get("has_missing"):
            source.status = "processing"
            source.is_active = False
            source.error_details = None
        else:
            source.status = "indexed"
            source.is_active = True
            source.error_details = None
        db.flush()
        return True

    @classmethod
    def create_embedding_chunks(cls, db: Session) -> None:
        """Refactored from AIEmbedding._create_embedding_chunks."""
        sources_to_process = (
            db.query(AIAgentSource)
            .filter(AIAgentSource.status == "processing")
            .all()
        )
        if not sources_to_process:
            return

        existing_pairs = {
            (row.checksum, row.embedding_model)
            for row in db.query(AIEmbedding.checksum, AIEmbedding.embedding_model).distinct().all()
        }

        for source in sources_to_process:
            provider = get_provider(source.agent.llm_model)
            embedding_model = get_embedding_model(provider)
            if (source.checksum, embedding_model) not in existing_pairs:
                content = source.extracted_content
                if not content:
                    source.status = "failed"
                    source.error_details = "Invalid attachment. Failed to extract content."
                    continue
                # Identical to IrAttachment._setup_attachment_chunks
                chunks = chunk_text(content)
                for seq, chunk in enumerate(chunks, start=1):
                    formatted_chunk = f"Attachment Name: {source.name}\n{chunk}"
                    emb = AIEmbedding(
                        source_id=source.id,
                        checksum=source.checksum,
                        sequence=seq * 10,
                        content=formatted_chunk,
                        embedding_model=embedding_model,
                    )
                    db.add(emb)
                existing_pairs.add((source.checksum, embedding_model))
        db.flush()

    @classmethod
    def cron_generate_embedding(cls, db: Session, batch_size: int = 100) -> bool:
        """Refactored from AIEmbedding._cron_generate_embedding."""
        cls.create_embedding_chunks(db)

        missing_embeddings = (
            db.query(AIEmbedding)
            .filter(
                AIEmbedding.embedding_vector.is_(None),
                AIEmbedding.has_embedding_generation_failed.is_(False),
            )
            .all()
        )
        if not missing_embeddings:
            return False

        missing_embeddings_batch = missing_embeddings[:batch_size]
        embeddings_by_model: dict[str, list[AIEmbedding]] = defaultdict(list)
        for emb in missing_embeddings_batch:
            embeddings_by_model[emb.embedding_model].append(emb)

        target_checksums = list({e.checksum for e in missing_embeddings_batch})
        staged_sources = (
            db.query(AIAgentSource)
            .filter(AIAgentSource.checksum.in_(target_checksums))
            .all()
        )

        failed_embeddings: list[AIEmbedding] = []

        for model, embeddings in embeddings_by_model.items():
            provider = get_provider_for_embedding_model(model)
            batches = cls.create_batches(embeddings, provider)

            for batch_idx, batch in enumerate(batches):
                try:
                    llm_service = LLMApiService(provider=provider)
                    source_name_map = {s.id: s.name for s in staged_sources}
                    batch_content = [
                        llm_service._format_for_embedding(
                            content=emb.content,
                            mode="document",
                            title=source_name_map.get(emb.source_id, f"Source #{emb.source_id}"),
                        )
                        for emb in batch
                    ]
                    response = llm_service.get_embedding(
                        input=batch_content,
                        dimensions=cls.get_dimensions(),
                        model=get_embedding_model(provider),
                    )
                    for idx, embedding in enumerate(batch):
                        try:
                            embedding.embedding_vector = response["data"][idx]["embedding"]
                        except KeyError as e:
                            _logger.error("Failed to extract embedding for record %s: %s", embedding.id, e)
                            failed_embeddings.append(embedding)
                except (RequestException, UserError, AttributeError) as e:
                    _logger.error(
                        "Failed to process batch %s/%s for model %s: %s",
                        batch_idx + 1,
                        len(batches),
                        model,
                        e,
                    )
                    failed_embeddings.extend(batch)
                    continue

        for failed_emb in failed_embeddings:
            failed_emb.has_embedding_generation_failed = True

        db.flush()

        for source in staged_sources:
            provider = get_provider(source.agent.llm_model)
            emb_model = get_embedding_model(provider)
            cls.update_source_status(db, source, emb_model)

        db.commit()
        return len(missing_embeddings) > batch_size

    @classmethod
    def create_source_with_chunks(
        cls,
        db: Session,
        agent: AIAgent,
        name: str,
        checksum: str,
        content: str,
        file_path: str = "",
        mimetype: str = "application/pdf",
        file_size: int = 0,
    ) -> AIAgentSource:
        """Refactored from AIAgentSource.create_from_attachments + create."""
        provider = get_provider(agent.llm_model)
        embedding_model = get_embedding_model(provider)

        existing_chunks = (
            db.query(AIEmbedding)
            .filter(
                AIEmbedding.checksum == checksum,
                AIEmbedding.embedding_model == embedding_model,
                AIEmbedding.embedding_vector.is_not(None),
            )
            .all()
        )

        source = AIAgentSource(
            name=name,
            agent_id=agent.id,
            type="binary",
            status="indexed" if existing_chunks else "processing",
            is_active=bool(existing_chunks),
            checksum=checksum,
            mimetype=mimetype,
            file_size=file_size,
            file_path=file_path,
            extracted_content=content,
        )
        db.add(source)
        db.flush()

        if source.type == "binary" and source.status == "processing":
            cls.cron_generate_embedding(db)

        db.commit()
        db.refresh(source)
        if source.status == "failed":
            raise UserError(source.error_details or "Không thể tạo Vector Embedding cho tài liệu.")
        return source

    @classmethod
    def sync_new_agent_provider(cls, db: Session, agent: AIAgent) -> None:
        """Refactored from AIAgentSource._sync_new_agent_provider when agent switches LLM provider."""
        provider = get_provider(agent.llm_model)
        embedding_model = get_embedding_model(provider)
        needs_cron = False
        for source in agent.sources:
            can_update = cls.update_source_status(db, source, embedding_model)
            if not can_update or source.status == "processing":
                source.status = "processing"
                source.is_active = False
                source.error_details = None
                needs_cron = True
        db.flush()
        if needs_cron:
            cls.cron_generate_embedding(db)

    @classmethod
    def get_similar_chunks(
        cls,
        db: Session,
        query_embedding: list[float],
        sources: list[AIAgentSource],
        embedding_model: str,
        top_n: int = 5,
    ) -> list[AIEmbedding]:
        """Refactored directly from AIEmbedding._get_similar_chunks in et-addons/ai/models/ai_embedding.py:
        SELECT ai_embedding.id, 1 - (embedding_vector <=> query_embedding) AS similarity
        WHERE checksum = ANY(target_checksums) AND embedding_model = embedding_model
        ORDER BY similarity DESC LIMIT top_n
        """
        active_sources = [s for s in sources if s.is_active]
        if not active_sources:
            return []

        target_checksums = list({s.checksum for s in active_sources})
        candidate_chunks = (
            db.query(AIEmbedding)
            .filter(
                AIEmbedding.checksum.in_(target_checksums),
                AIEmbedding.embedding_model == embedding_model,
            )
            .all()
        )
        if not candidate_chunks:
            return []

        scored = [
            (cosine_similarity(query_embedding, c.embedding_vector), c)
            for c in candidate_chunks
            if c.embedding_vector
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [c for _, c in scored[:top_n]]
