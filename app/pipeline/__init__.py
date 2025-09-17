class PipelineContext:
    def __init__(self, user_query: str):
        self.original_query = user_query  # <== THIS LINE MUST EXIST
        self.cleaned_query = ""
        self.intent = ""
        self.intent_confidence = 0.0
        self.entities = {}
        self.tables = []
        self.columns = {}
        self.sql = ""
        self.result = None
