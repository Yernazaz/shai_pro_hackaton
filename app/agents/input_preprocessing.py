from app.registry.agent_registry import registry
from app.utils.logging_config import get_logger
from app.utils.query_rewrite import rewrite_query_with_context

logger = get_logger(__name__)

class InputPreprocessingAgent:
    def run(self, context):
        logger.info("[InputPreprocessing] Received: %s", context.original_query)
        rewritten = rewrite_query_with_context(context.original_query, context.chat_context)
        context.cleaned_query = rewritten.strip().lower()
        logger.info("[InputPreprocessing] Rewritten: %s", rewritten)
        logger.info("[InputPreprocessing] Cleaned: %s", context.cleaned_query)
        return context

registry.register("input_preprocessing", InputPreprocessingAgent())
