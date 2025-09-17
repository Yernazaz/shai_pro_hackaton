import os, re, logging

try:
    # OpenAI >= 1.x
    from openai import AuthenticationError, APIError, RateLimitError
except Exception:  # pragma: no cover - support legacy SDK
    try:
        # OpenAI 0.28.x
        from openai.error import AuthenticationError, APIError, RateLimitError  # type: ignore
    except Exception:
        class AuthenticationError(Exception):
            pass

        class APIError(Exception):
            pass

        class RateLimitError(Exception):
            pass
from app.registry.agent_registry import registry
from app.agents.intent_embedder import model, compute_intent_embeddings, build_fallback_prompt
from app.agents.intent_corpus import intent_definitions
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from scripts.employee_names import load_employee_names

THRESHOLD = float(os.getenv("INTENT_THRESHOLD", "0.60"))  # slightly lower; see §3
DISABLE_OPENAI = os.getenv("DISABLE_OPENAI", "0").lower() in ("1","true","yes")
intent_embeddings, intent_meta = compute_intent_embeddings(intent_definitions)

_EMPLOYEE_NAMES_LOWER: list[str] | None = None


def _load_employee_names_lower() -> list[str]:
    global _EMPLOYEE_NAMES_LOWER
    if _EMPLOYEE_NAMES_LOWER is None:
        try:
            _EMPLOYEE_NAMES_LOWER = [name.lower() for name in load_employee_names()]
        except Exception:
            _EMPLOYEE_NAMES_LOWER = []
    return _EMPLOYEE_NAMES_LOWER


def _contains_employee_name(text: str) -> bool:
    for name in _load_employee_names_lower():
        if name and name in text:
            return True
    return False

# --- simple keyword safety net for common asks
KEYWORD_RULES = [
    (r"\bтаблиц", "list_tables"),
    (r"\btables?\b", "list_tables"),
    (r"\bсписок\s+клиент\w*\b", "list_clients"),
    (r"какие\s+у\s+нас\b.*клиент\w*", "list_clients"),
    (r"\bкакие\b.*\bклиент\w*", "list_clients"),
    (r"сколько\s+клиент\w*\b", "client_count"),
    (r"\b(список|какие)\b.*\b(услуг\w*|процедур\w*)\b", "list_services"),
    (r"\b(список|какие|кто)\b.*\b(сотрудник\w*|мастер\w*)\b", "list_employees"),
    (r"сколько\s+сотрудник\w*\b", "employee_count"),
    # manage employees
    (r"(добав(ь|ьте)|создай(те)?)\s+[А-ЯA-ZЁ][а-яa-zё\-]+\s+[А-ЯA-ZЁ][а-яa-zё\-]+", "create_employee"),
    (r"(добав(ь|ьте)|создай(те)?).*(сотрудник|работник|мастер)\w*", "create_employee"),
    (r"(удал(и|ите)|убер(и|ите)|удалить)\s+[А-ЯA-ZЁ][а-яa-zё\-]+\s+[А-ЯA-ZЁ][а-яa-zё\-]+", "delete_employee"),
    (r"(удал(и|ите)|убер(и|ите)|удалить).*(сотрудник|работник|мастер)\w*", "delete_employee"),
    # list appointments (robust to typos like "перечесли")
    (r"(переч[еие]сл\w*|список|покажи|выведи).*запис\w*", "list_appointments"),
    (r"(удал(и|ите)|убер(и|ите)|удалить).*(запис\w*)", "delete_appointments"),
    (r"\b(ближайш\w*|предстоящ\w*|завтра|на\s+этой\s+неделе)\b", "upcoming_appointments"),
    (r"\bотмененн?\w*\b", "cancelled_appointments"),
    (r"(в\s+какое\s+время|популярн\w+\s+час\w*)", "popular_time_slots"),
    (r"по\s*2\s*запис", "frequent_clients"),
    # booking intent (not yet implemented for write operations)
    (r"(запиш(и|те)|забронируй|назнач(ь|ьте)|записать|забронировать)", "create_appointment"),
]

from app.utils.llm_client import chat_completion

class IntentAgent:
    def __init__(self):
        self.model = model

    def run(self, context):
        user_vec = self.model.encode([context.cleaned_query], convert_to_numpy=True)[0]
        sims = cosine_similarity(intent_embeddings, [user_vec]).flatten()

        # Rank, then de-duplicate by intent name so we don't show repeats
        ranked = sorted(zip(intent_meta, sims.tolist()), key=lambda x: x[1], reverse=True)
        seen, top_scores = set(), []
        for meta, s in ranked:
            name = meta["name"] if isinstance(meta, dict) and "name" in meta else str(meta)
            if name not in seen:
                top_scores.append((name, float(s)))
                seen.add(name)
            if len(top_scores) == 3:
                break

        best_intent, score = top_scores[0]

        logging.info("[IntentAgent] Top intent candidates:")
        for name, s in top_scores:
            logging.info(" - %s: %.4f", name, s)

        text = context.cleaned_query
        employee_in_query = _contains_employee_name(text)

        if employee_in_query and any(token in text for token in ("услуг", "процедур")):
            context.intent = "services_by_employee"
            context.intent_confidence = max(score, THRESHOLD)
            return context

        # Strong keyword overrides (apply even for high-confidence embeds)
        for pattern, intent_label in KEYWORD_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                if intent_label == "list_services" and employee_in_query:
                    continue
                context.intent = intent_label
                context.intent_confidence = max(score, THRESHOLD)
                return context

        # High-confidence case via embeddings
        if score >= THRESHOLD:
            context.intent = best_intent
            context.intent_confidence = score
            return context

        # LLM fallback
        # Allow LLM fallback when a keyless HTTP backend is configured
        if DISABLE_OPENAI or (not os.getenv("OPENAI_API_KEY") and not os.getenv("LLM_BASE_URL")):
            logging.warning("[IntentAgent] OpenAI disabled or key missing. Using best embed intent.")
            context.intent = best_intent
            context.intent_confidence = score
            return context

        prompt = build_fallback_prompt(context.cleaned_query, intent_definitions)
        try:
            resp = chat_completion(
                model=os.getenv("OPENAI_CHAT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
                messages=[
                    {"role": "system", "content": "You are an intent classifier. Return only the intent label."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )
            msg = resp["choices"][0]["message"] if isinstance(resp, dict) else resp.choices[0].message
            content = msg.get("content") if isinstance(msg, dict) else msg.content
            context.intent = (content or "").strip()
            context.intent_confidence = score
        except AuthenticationError:
            logging.exception("[IntentAgent] GPT fallback failed: AuthenticationError; using best embed intent.")
            context.intent = best_intent
            context.intent_confidence = score
        except (RateLimitError, APIError, Exception) as e:
            logging.exception("[IntentAgent] GPT fallback failed: %s; using best embed intent.", e.__class__.__name__)
            context.intent = best_intent
            context.intent_confidence = score

        return context

registry.register("intent", IntentAgent())
