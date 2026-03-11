"""CrewBase class for the financial operations crew."""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from steering_financial_agent.tools.process_transfer import create_transfer_tool


@CrewBase
class SteeringFinancialCrew:
    """Financial operations crew with Agent Control steering."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def financial_operations_agent(self) -> Agent:
        transfer_tool = create_transfer_tool()
        return Agent(
            config=self.agents_config["financial_operations_agent"],
            tools=[transfer_tool],
            verbose=True,
        )

    @task
    def transfer_task(self) -> Task:
        return Task(
            config=self.tasks_config["transfer_task"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
