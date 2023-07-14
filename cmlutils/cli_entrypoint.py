import click

from cmlutils.project_entrypoint import project_cmd


@click.group()
def cli():
    """
    Top level entry-point for CLI.
    """


cli.add_command(project_cmd)


def main():
    cli()
