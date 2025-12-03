from google.adk.agents.llm_agent import Agent
from .tools import query_SysOption

root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description='A helpful assistant for user questions.',
    instruction='Answer user questions to the best of your knowledge',
    tools=[query_SysOption],
)
