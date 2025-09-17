from app.pipeline.context import PipelineContext
from app.registry.agent_registry import registry
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

class Orchestrator:
    def __init__(self, steps):
        self.steps = steps

    def run(self, query: str, chat_context=None):
        context = PipelineContext(query)
        if chat_context:
            context.chat_context = list(chat_context)
        logger.info("Starting pipeline for query: %s", query)
        for step in self.steps:
            agent = registry.get(step)
            if agent:
                logger.info("Running step: %s", step)
                context = agent.run(context)
        logger.info("Final context state: %s", context.__dict__)
        return {
            "original_query": context.original_query,
            "cleaned_query": context.cleaned_query,
            "intent": context.intent,
            "confidence": context.intent_confidence,
            "entities": context.entities,
            "tables": context.tables,
            "columns": context.columns,
            "sql": context.sql,
            "query_result": context.query_result,
            "generated_response": context.generated_response,
            "followup_questions": context.followup_questions,
        }
