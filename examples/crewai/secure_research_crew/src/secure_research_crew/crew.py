"""SecureResearchCrew -- @CrewBase class definition."""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from secure_research_crew.tools.query_database import query_database
from secure_research_crew.tools.validate_data import validate_data
from secure_research_crew.tools.write_report import write_report


@CrewBase
class SecureResearchCrew:
    """Multi-agent research crew with per-agent Agent Control policies."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["researcher"],  # type: ignore[index]
            tools=[query_database],
            verbose=True,
        )

    @agent
    def analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["analyst"],  # type: ignore[index]
            tools=[validate_data],
            verbose=True,
        )

    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config["writer"],  # type: ignore[index]
            tools=[write_report],
            verbose=True,
        )

    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config["research_task"],  # type: ignore[index]
            agent=self.researcher(),
        )

    @task
    def analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["analysis_task"],  # type: ignore[index]
            agent=self.analyst(),
        )

    @task
    def report_task(self) -> Task:
        return Task(
            config=self.tasks_config["report_task"],  # type: ignore[index]
            agent=self.writer(),
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,  # type: ignore[arg-type]
            tasks=self.tasks,  # type: ignore[arg-type]
            process=Process.sequential,
            verbose=True,
        )
