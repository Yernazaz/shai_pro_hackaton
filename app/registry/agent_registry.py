class AgentRegistry:
    def __init__(self):
        self.agents = {}

    def register(self, name: str, agent):
        self.agents[name] = agent

    def get(self, name: str):
        return self.agents.get(name)

registry = AgentRegistry()
