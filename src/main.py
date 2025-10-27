import typer
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint


console = Console()

def main():
    rprint("Hello from knack-slueth!")
    rprint(Panel("Hello, [red]World!", title="Welcome", subtitle="Thank you"))



if __name__ == "__main__":
    typer.run(main)
