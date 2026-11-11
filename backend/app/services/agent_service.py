"""AI Agent orchestration service refactored directly from et-addons/ai/models/ai_agent.py."""
from datetime import datetime, timezone
from textwrap import dedent
from sqlalchemy.orm import Session

from ..core.ai_citation import apply_numeric_citations, get_attachment_ids_from_text
from ..core.exceptions import UserError
from ..core.llm_api_service import LLMApiService
from ..core.llm_providers import (
    TEMPERATURE_MAP,
    get_embedding_model,
    get_provider,
)
from ..domain.models import AIAgent, AIAgentSource, AITopic
from .embedding_service import EmbeddingService

# Pre-prompts refactored from et-addons/ai/models/ai_agent.py
PREPROMPTS = {
    "default_system_prompt": (
        "Bạn là Chuyên gia Kiểm toán & Đối soát Hóa đơn - Hợp đồng (AI Compliance & Audit RAG Assistant). "
        "Nhiệm vụ của bạn là tự động truy xuất điều khoản Hợp đồng liên quan từ RAG context và đối chiếu với dữ liệu Hóa đơn "
        "(sau khi người dùng đã kiểm tra) cùng các quy định pháp luật về Hóa đơn chứng từ."
    ),
    "tools": dedent(
        """
        You have access to tools that can perform actions. Only use these tools when:
        1. The user explicitly requests the action.
        2. The action is clearly the most appropriate response to their query.

        If the user asks you to perform an action, retrieve the required information from his prompt and the conversation history, then use the tool.

        If date is needed, Use today's date to make a relative date if the user didn't provide a clear one (e.g. tomorrow, in one week, etc.).
        Rarely suggest the actions in your response.
    """
    ).strip(),
    "restrict_to_sources": dedent(
        """
        ## INSTRUCTIONS FOR ANSWERING QUERIES

        1. For greetings (hello, hi, how are you), reply with a greeting.

        2. For all other questions, you MUST ONLY use information from the provided context and conversation history.

        3. If the RAG context and history don't contain information to answer the query or it is not provided at all:
           - use the assistant/user messages as context or ask the user to provide more information.
           - DO NOT make up information or use your general knowledge.

        4. When answering based on the context:
           - Synthesize information from multiple sources when appropriate
           - Consider the conversation history for follow-up questions

        5. If a user asks a follow-up question like 'what is this?' or 'tell me more', refer to the conversation history to understand the context and answer accordingly.

        6. If no context is provided at all, respond with: 'No source information has been provided for me to reference.'

        7. Avoid using HTML elements in your response.
    """
    ).strip(),
    "context": dedent(
        """
        - Use the RAG context to answer the question.
        - Every claim or piece of information provided in the answer **MUST** be immediately followed by an inline citation in the format **[SOURCE:Attachment ID]** to indicate its source from the RAG context (e.g., "The capital of France is Paris [SOURCE:210].").
        - If a claim draws on multiple sources, cite all of them (e.g., "The process requires heat and pressure [SOURCE:210, 211].").
        - If **NO** source chunks were used to answer the question, do not include any citations.

        - Example of the required format for the response with the attachment IDs [SOURCE:210, 211] in its answer:
        - The primary goal of the project is to enhance data security protocols [SOURCE:210]. This enhancement includes a mandatory two-factor authentication system [SOURCE:211].
    """
    ).strip(),
}


class AgentService:
    """Refactored from AIAgent in et-addons/ai/models/ai_agent.py."""

    @classmethod
    def build_system_context(
        cls,
        agent: AIAgent,
        topics: list[AITopic] | None = None,
        extra_system_context: str | list[str] = "",
        has_tools: bool = False,
    ) -> list[str]:
        """Refactored from AIAgent._build_system_context in et-addons/ai/models/ai_agent.py."""
        system_content = agent.system_prompt or PREPROMPTS["default_system_prompt"]
        system_content += f"\n\nToday's date to be used: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} (UTC)"

        if has_tools or topics:
            system_content += "\n\n" + PREPROMPTS["tools"]

        messages = [system_content]

        if topics:
            topic_instructions = "\n\n".join(
                [t.instructions for t in topics if t.instructions]
            )
            if topic_instructions:
                messages.append(f"Additional topic instructions:\n{topic_instructions}.")

        if agent.restrict_to_sources:
            messages.append(PREPROMPTS["restrict_to_sources"])

        if isinstance(extra_system_context, str) and extra_system_context:
            messages.append(extra_system_context)
        elif isinstance(extra_system_context, list):
            messages += extra_system_context

        return messages

    @classmethod
    def build_rag_context_with_matched_sources(
        cls,
        db: Session,
        agent: AIAgent,
        prompt: str,
        sources: list[AIAgentSource] | None = None,
        top_n: int = 5,
    ) -> tuple[list[str], list[AIAgentSource]]:
        """Refactored directly from AIAgent._build_rag_context in et-addons/ai/models/ai_agent.py (lines 638-681).
        Searches across ALL active sources in `agent.sources` (unless a specific subset is given) using vector similarity.
        Returns (rag_messages, matched_agent_sources).
        """
        messages: list[str] = []
        matched_sources: list[AIAgentSource] = []
        context = ""

        target_sources = sources if sources is not None else list(agent.sources)
        active_sources = [s for s in target_sources if s.is_active]
        if not active_sources:
            return messages, matched_sources

        provider = get_provider(agent.llm_model)
        embedding_model = get_embedding_model(provider)
        llm_service = LLMApiService(provider=provider)
        response = llm_service.get_embedding(
            input=llm_service._format_for_embedding(content=prompt, mode="query"),
            dimensions=EmbeddingService.get_dimensions(),
            model=embedding_model,
        )
        if not response or "data" not in response:
            raise UserError("Failed to get embeddings for the prompt.")

        prompt_embedding = response["data"][0]["embedding"]
        similar_embeddings = EmbeddingService.get_similar_chunks(
            db=db,
            query_embedding=prompt_embedding,
            sources=active_sources,
            embedding_model=embedding_model,
            top_n=top_n,
        )
        if similar_embeddings:
            embeddings_checksums = list({e.checksum for e in similar_embeddings})
            agent_sources = (
                db.query(AIAgentSource)
                .filter(
                    AIAgentSource.checksum.in_(embeddings_checksums),
                    AIAgentSource.agent_id == agent.id,
                )
                .all()
            )
            source_map = {source.checksum: source for source in agent_sources}
            seen_source_ids = set()
            for embedding in similar_embeddings:
                agent_source = source_map.get(embedding.checksum)
                if not agent_source:
                    continue
                if agent_source.id not in seen_source_ids:
                    matched_sources.append(agent_source)
                    seen_source_ids.add(agent_source.id)
                context += (
                    f"(Source Chunk {agent_source.name})\n"
                    f" (attachment_id: {agent_source.id})\n"
                    f"{embedding.content}\n\n"
                )

            if context:
                final_context_message = f"##RAG context information:\n\n{context}"
                messages.append(final_context_message)
                messages.append(PREPROMPTS["context"])

        return messages, matched_sources

    @classmethod
    def build_rag_context(
        cls,
        db: Session,
        agent: AIAgent,
        prompt: str,
        sources: list[AIAgentSource] | None = None,
    ) -> list[str]:
        """Refactored from AIAgent._build_rag_context in et-addons/ai/models/ai_agent.py."""
        messages, _ = cls.build_rag_context_with_matched_sources(
            db=db, agent=agent, prompt=prompt, sources=sources
        )
        return messages

    @classmethod
    def get_llm_response_with_sources(
        cls,
        db: Session,
        agent: AIAgent,
        llm_response: list[str],
    ) -> list[str]:
        """Refactored directly from AIAgent._get_llm_response_with_sources in et-addons/ai/models/ai_agent.py (lines 558-593)."""
        llm_response_with_sources: list[str] = []
        link_attrs = 'target="_blank" rel="noreferrer noopener"'

        for message_content in llm_response:
            unique_attachment_ids = get_attachment_ids_from_text(message_content)
            attachment_data: dict[int, dict[str, str]] = {}
            if unique_attachment_ids:
                sources = (
                    db.query(AIAgentSource)
                    .filter(
                        AIAgentSource.id.in_(unique_attachment_ids),
                        AIAgentSource.agent_id == agent.id,
                    )
                    .all()
                )
                for src in sources:
                    attachment_data[src.id] = {
                        "source_name": src.name,
                        "url": src.url or f"#contract-source-{src.id}",
                    }

            new_content = apply_numeric_citations(
                message_content, attachment_data, link_attrs=link_attrs
            )
            llm_response_with_sources.append(new_content)

        return llm_response_with_sources

    @classmethod
    def generate_response(
        cls,
        db: Session,
        agent: AIAgent,
        prompt: str,
        chat_history: list[dict] | None = None,
        extra_system_context: str | list[str] = "",
        tools: dict | None = None,
        sources: list[AIAgentSource] | None = None,
    ) -> list[str]:
        """Refactored directly from AIAgent._generate_response in et-addons/ai/models/ai_agent.py (lines 524-556)."""
        system_messages = cls.build_system_context(
            agent=agent,
            extra_system_context=extra_system_context,
            has_tools=bool(tools),
        )
        rag_context = cls.build_rag_context(db, agent, prompt, sources=sources)
        if rag_context:
            system_messages.extend(rag_context)

        provider = get_provider(agent.llm_model)
        llm_response = LLMApiService(provider=provider).request_llm(
            llm_model=agent.llm_model,
            system_prompts=system_messages,
            user_prompts=[],
            inputs=(chat_history or []) + [{"role": "user", "content": prompt}],
            tools=tools,
            temperature=TEMPERATURE_MAP[agent.response_style],
        )
        if rag_context:
            llm_response = cls.get_llm_response_with_sources(db, agent, llm_response)

        return llm_response
