import click

from cmlutils.project_entrypoint import project_cmd, project_helpers_cmd


@click.group()
def cli():
    """
    Top level entry-point for CLI.
    """


cli.add_command(project_cmd)
cli.add_command(project_helpers_cmd)


def main():
    cli()
