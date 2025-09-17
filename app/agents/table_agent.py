from app.registry.agent_registry import registry
from app.agents.semantic_search import retrieve_tables
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

class TableSelectionAgent:
    def run(self, context):
        query = context.cleaned_query
        logger.info("[TableSelection] Searching FAISS for tables…")
        selected = retrieve_tables(query, top_k=3)
        context.tables = selected
        logger.info("[TableSelection] Selected tables: %s", selected)
        return context

registry.register("table", TableSelectionAgent())
