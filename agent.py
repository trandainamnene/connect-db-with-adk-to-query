from google.adk.agents.llm_agent import Agent
from .tools import query_DeviceInfo

root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description='A helpful assistant for user questions.',
    instruction='If the user asks about locating device info, use the query_DeviceInfo tool to get the device info.',
    tools=[query_DeviceInfo],
)
