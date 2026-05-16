import typer
import asyncio
from rich.console import Console
from rich.table import Table

from vigil.agents import VigilOrchestrator
from vigil.schemas import MonitoringInstruction
from vigil.settings import get_settings

app = typer.Typer(help="Vigil local development CLI.")
console = Console()


def show_doctor() -> None:
    settings = get_settings()
    table = Table(title="Vigil Configuration")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("APP_ENV", settings.app_env)
    table.add_row("Model", settings.vigil_model)
    table.add_row("Reasoning model", settings.vigil_reasoning_model)
    table.add_row("Source backend", settings.vigil_source_backend)
    table.add_row("Retrieval backend", settings.vigil_retrieval_backend)
    table.add_row("Memory backend", settings.vigil_memory_backend)
    table.add_row("Action backend", settings.vigil_action_backend)
    table.add_row("Use Vertex AI", str(settings.google_genai_use_vertexai))
    table.add_row("Google Cloud project", settings.google_cloud_project or "not set")
    table.add_row("Google Cloud location", settings.google_cloud_location)
    console.print(table)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        show_doctor()


@app.command()
def doctor() -> None:
    show_doctor()


@app.command()
def analyze(
    query: str = typer.Argument(..., help="Legal or compliance topic to investigate."),
    jurisdiction: str | None = typer.Option(None, help="Jurisdiction to focus on."),
    domain: str | None = typer.Option(None, help="Compliance domain to focus on."),
) -> None:
    decision = asyncio.run(
        VigilOrchestrator().analyze(
            MonitoringInstruction(query=query, jurisdiction=jurisdiction, domain=domain)
        )
    )
    print(decision.model_dump_json(indent=2))


@app.command()
def demo() -> None:
    decision = asyncio.run(
        VigilOrchestrator().analyze(
            MonitoringInstruction(
                query="EU AI Act high-risk AI deployer obligations",
                jurisdiction="European Union",
                domain="AI governance",
                sources=["https://artificialintelligenceact.eu/"],
            )
        )
    )
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
