class PipelineContext:
    def __init__(self, user_query: str):
        self.original_query = user_query  
        self.cleaned_query = ""
        self.intent = ""
        self.intent_confidence = 0.0
        self.entities = {}
        self.tables = []
        self.columns = {}
        self.sql = ""
        self.generated_response = {}
        self.result = None
        self.query_result = None
        self.followup_questions = []
        # Optional conversational context (list of {role, content})
        self.chat_context = []
