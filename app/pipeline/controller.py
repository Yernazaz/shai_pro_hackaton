from __future__ import annotations

from typing import Any, Dict

from app.config.settings import Settings, get_settings
from app.contracts.analysis import AnalysisOut
from app.contracts.envelope import ControllerEnvelope
from app.contracts.plan import PlanOut, Entities
from app.db.execute_sql_query import ExecMeta, execute_sql_query
from app.pipeline.analyzer import analyze_results
from app.pipeline.planner import plan_query
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_ROUNDS = 3


class IterativeController:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def run(self, raw_question: str, runtime_context: Dict[str, Any]) -> ControllerEnvelope:
        telemetry: Dict[str, Any] = {"rounds": []}
        question = raw_question
        plan: PlanOut | None = None
        analysis: AnalysisOut | None = None
        rows: list[Dict[str, Any]] = []
        iterations_used = 0

        prompt_context = {
            **self.settings.as_prompt_context(),
            **{k: v for k, v in runtime_context.items() if v is not None},
        }
        pending_state: Dict[str, Any] | None = runtime_context.get("pending_state")

        for round_index in range(1, MAX_ROUNDS + 1):
            logger.info("[Controller] Round %s started", round_index)
            telemetry_round: Dict[str, Any] = {"round": round_index, "question": question}
            try:
                plan = plan_query(question, prompt_context)
            except Exception as exc:
                logger.exception("[Controller] Plan generation failed: %s", exc)
                analysis = AnalysisOut(
                    final_answer="LLM недоступен или вернул ошибку при планировании.",
                    explanations=[str(exc)],
                    suggested_followup=[
                        "Попробуйте повторить запрос позже или переформулировать его."
                    ],
                    needs_iteration=False,
                )
                rows = []
                telemetry_round["error"] = str(exc)
                telemetry["rounds"].append(telemetry_round)
                plan = PlanOut(
                    normalized_question=question,
                    assumptions=[],
                    entities=Entities(),
                    dialect=prompt_context.get("dialect", "postgres"),
                    sql="",
                    confidence=0.0,
                    needs_user_clarification=False,
                )
                iterations_used = round_index
                break
            telemetry_round["plan_confidence"] = plan.confidence
            iterations_used = round_index

            if plan.needs_user_clarification:
                logger.info(
                    "[Controller] Plan flagged for clarification, proceeding without user prompt"
                )

            if not plan.sql.strip():
                logger.info("[Controller] Plan did not produce SQL, returning failure response")
                explanations = plan.assumptions or [
                    "Автоматически сформировать SQL по запросу не удалось."
                ]
                analysis = AnalysisOut(
                    final_answer="Не удалось автоматически сформировать SQL для запроса.",
                    explanations=explanations,
                    suggested_followup=[],
                    needs_iteration=False,
                )
                rows = []
                telemetry_round["plan_confidence"] = plan.confidence
                telemetry_round["sql"] = plan.sql
                telemetry_round["missing_sql"] = True
                telemetry["rounds"].append(telemetry_round)
                break

            try:
                exec_rows, exec_meta = execute_sql_query(plan.sql, runtime_context.get("org_id"))
                rows = exec_rows
                telemetry_round["exec_meta"] = exec_meta
            except Exception as exc:
                logger.exception("[Controller] SQL execution failed: %s", exc)
                analysis = AnalysisOut(
                    final_answer="Не удалось выполнить SQL-запрос.",
                    explanations=[str(exc)],
                    suggested_followup=["Попробуйте уточнить запрос или изменить формулировку."],
                    needs_iteration=False,
                )
                rows = []
                telemetry_round["error"] = str(exc)
                telemetry["rounds"].append(telemetry_round)
                pending_state = None
                break

            analysis = analyze_results(
                normalized_question=plan.normalized_question,
                sql=plan.sql,
                rows=rows,
                context={
                    "contextual_notes": "; ".join(plan.assumptions) if plan.assumptions else "",
                },
            )
            telemetry_round["needs_iteration"] = analysis.needs_iteration
            telemetry_round["row_count"] = len(rows)
            telemetry["rounds"].append(telemetry_round)

            if not analysis.needs_iteration:
                pending_state = None
                break
            if round_index >= MAX_ROUNDS:
                logger.info("[Controller] Reached max rounds, stopping")
                break
            if not analysis.next_query_hint:
                logger.info("[Controller] No hint for next iteration, stopping")
                break
            pending_state = {
                "next_query_hint": analysis.next_query_hint,
                "assumptions": plan.assumptions,
                "normalized_question": plan.normalized_question,
            }
            question = analysis.next_query_hint

        if plan is None or analysis is None:
            raise RuntimeError("Controller did not produce plan or analysis")

        if analysis.needs_iteration:
            analysis = AnalysisOut(
                final_answer=analysis.final_answer,
                explanations=list(analysis.explanations),
                suggested_followup=list(analysis.suggested_followup),
                needs_iteration=False,
                iteration_reason=None,
                next_query_hint=None,
            )

        telemetry["total_rounds"] = iterations_used

        envelope = ControllerEnvelope(
            normalized_question=plan.normalized_question,
            assumptions=plan.assumptions,
            sql=plan.sql,
            rows=rows,
            analysis_text=analysis.final_answer,
            suggested_followup=analysis.suggested_followup,
            iterations_used=iterations_used,
            confidence=plan.confidence,
            telemetry=telemetry,
            pending_state=pending_state,
        )
        return envelope


__all__ = ["IterativeController"]
