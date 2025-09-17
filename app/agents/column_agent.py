from app.registry.agent_registry import registry
from app.agents.semantic_search import retrieve_columns
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

class ColumnPruneAgent:
    def run(self, context):
        query = context.cleaned_query
        logger.info("[ColumnPrune] Searching FAISS for columns…")
        all_columns = retrieve_columns(query, top_k=12)

        context.columns = {}
        for full_col in all_columns:
            if "." in full_col:
                table, col = full_col.split(".")
                context.columns.setdefault(table, []).append(col)

        logger.info("[ColumnPrune] Selected columns: %s", context.columns)
        return context

registry.register("column", ColumnPruneAgent())
