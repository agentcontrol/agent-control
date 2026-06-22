"""CrewBase crew definition for the Rule Showcase."""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from rule_showcase.tools import create_sql_tool, create_analysis_tool


@CrewBase
class RuleShowcaseCrew:
    """Data analyst crew demonstrating all rule types."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def data_analyst(self) -> Agent:
        sql_tool = create_sql_tool()
        analysis_tool = create_analysis_tool()
        return Agent(
            config=self.agents_config["data_analyst"],
            tools=[sql_tool, analysis_tool],
            verbose=True,
        )

    @task
    def analysis_task(self) -> Task:
        return Task(config=self.tasks_config["analysis_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
