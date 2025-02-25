"""
Manage LangChain apps
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import typer
from typing_extensions import Annotated

from langchain_cli.utils.events import create_events
from langchain_cli.utils.git import (
    DependencySource,
    copy_repo,
    parse_dependencies,
    update_repo,
)
from langchain_cli.utils.packages import (
    LangServeExport,
    get_langserve_export,
    get_package_root,
)
from langchain_cli.utils.pyproject import (
    add_dependencies_to_pyproject_toml,
    remove_dependencies_from_pyproject_toml,
)

REPO_DIR = Path(typer.get_app_dir("langchain")) / "git_repos"

app_cli = typer.Typer(no_args_is_help=True, add_completion=False)


@app_cli.command()
def new(
    name: Annotated[
        str,
        typer.Option(
            help="The name of the folder to create",
            prompt="What folder would you like to create?",
        ),
    ],
    *,
    package: Annotated[
        Optional[List[str]],
        typer.Option(help="Packages to seed the project with"),
    ] = None,
    pip: Annotated[
        Optional[bool],
        typer.Option(
            "--pip/--no-pip",
            help="Pip install the template(s) as editable dependencies",
            is_flag=True,
        ),
    ] = None,
):
    """
    Create a new LangServe application.
    """
    has_packages = package is not None and len(package) > 0
    pip_bool = False
    if pip is None and has_packages:
        pip_bool = typer.confirm(
            "Would you like to `pip install -e` the template(s)?",
            default=False,
        )
    # copy over template from ../project_template
    project_template_dir = Path(__file__).parents[1] / "project_template"
    destination_dir = Path.cwd() / name if name != "." else Path.cwd()
    app_name = name if name != "." else Path.cwd().name
    shutil.copytree(project_template_dir, destination_dir, dirs_exist_ok=name == ".")

    readme = destination_dir / "README.md"
    readme_contents = readme.read_text()
    readme.write_text(readme_contents.replace("__app_name__", app_name))

    # add packages if specified
    if has_packages:
        add(package, project_dir=destination_dir, pip=pip_bool)


@app_cli.command()
def add(
    dependencies: Annotated[
        Optional[List[str]], typer.Argument(help="The dependency to add")
    ] = None,
    *,
    api_path: Annotated[List[str], typer.Option(help="API paths to add")] = [],
    project_dir: Annotated[
        Optional[Path], typer.Option(help="The project directory")
    ] = None,
    repo: Annotated[
        List[str],
        typer.Option(help="Install templates from a specific github repo instead"),
    ] = [],
    branch: Annotated[
        List[str], typer.Option(help="Install templates from a specific branch")
    ] = [],
    pip: Annotated[
        bool,
        typer.Option(
            "--pip/--no-pip",
            help="Pip install the template(s) as editable dependencies",
            is_flag=True,
            prompt="Would you like to `pip install -e` the template(s)?",
        ),
    ],
):
    """
    Adds the specified template to the current LangServe app.

    e.g.:
    langchain app add extraction-openai-functions
    langchain app add git+ssh://git@github.com/efriis/simple-pirate.git
    """

    parsed_deps = parse_dependencies(dependencies, repo, branch, api_path)

    project_root = get_package_root(project_dir)

    package_dir = project_root / "packages"

    create_events(
        [{"event": "serve add", "properties": dict(parsed_dep=d)} for d in parsed_deps]
    )

    # group by repo/ref
    grouped: Dict[Tuple[str, Optional[str]], List[DependencySource]] = {}
    for dep in parsed_deps:
        key_tup = (dep["git"], dep["ref"])
        lst = grouped.get(key_tup, [])
        lst.append(dep)
        grouped[key_tup] = lst

    installed_destination_paths: List[Path] = []
    installed_destination_names: List[str] = []
    installed_exports: List[LangServeExport] = []

    for (git, ref), group_deps in grouped.items():
        if len(group_deps) == 1:
            typer.echo(f"Adding {git}@{ref}...")
        else:
            typer.echo(f"Adding {len(group_deps)} templates from {git}@{ref}")
        source_repo_path = update_repo(git, ref, REPO_DIR)

        for dep in group_deps:
            source_path = (
                source_repo_path / dep["subdirectory"]
                if dep["subdirectory"]
                else source_repo_path
            )
            pyproject_path = source_path / "pyproject.toml"
            if not pyproject_path.exists():
                typer.echo(f"Could not find {pyproject_path}")
                continue
            langserve_export = get_langserve_export(pyproject_path)

            # default path to package_name
            inner_api_path = dep["api_path"] or langserve_export["package_name"]

            destination_path = package_dir / inner_api_path
            if destination_path.exists():
                typer.echo(
                    f"Folder {str(inner_api_path)} already exists. " "Skipping...",
                )
                continue
            copy_repo(source_path, destination_path)
            typer.echo(f" - Downloaded {dep['subdirectory']} to {inner_api_path}")
            installed_destination_paths.append(destination_path)
            installed_destination_names.append(inner_api_path)
            installed_exports.append(langserve_export)

    if len(installed_destination_paths) == 0:
        typer.echo("No packages installed. Exiting.")
        return

    try:
        add_dependencies_to_pyproject_toml(
            project_root / "pyproject.toml",
            zip(installed_destination_names, installed_destination_paths),
        )
    except Exception:
        # Can fail if user modified/removed pyproject.toml
        typer.echo("Failed to add dependencies to pyproject.toml, continuing...")

    try:
        cwd = Path.cwd()
        installed_destination_strs = [
            str(p.relative_to(cwd)) for p in installed_destination_paths
        ]
    except ValueError:
        # Can fail if the cwd is not a parent of the package
        typer.echo("Failed to print install command, continuing...")
    else:
        if pip:
            cmd = ["pip", "install", "-e"] + installed_destination_strs
            cmd_str = " \\\n  ".join(installed_destination_strs)
            typer.echo(f"Running: pip install -e \\\n  {cmd_str}")
            subprocess.run(cmd, cwd=cwd)

    chain_names = []
    for e in installed_exports:
        original_candidate = f'{e["package_name"].replace("-", "_")}_chain'
        candidate = original_candidate
        i = 2
        while candidate in chain_names:
            candidate = original_candidate + "_" + str(i)
            i += 1
        chain_names.append(candidate)

    api_paths = [
        str(Path("/") / path.relative_to(package_dir))
        for path in installed_destination_paths
    ]

    imports = [
        f"from {e['module']} import {e['attr']} as {name}"
        for e, name in zip(installed_exports, chain_names)
    ]
    routes = [
        f'add_routes(app, {name}, path="{path}")'
        for name, path in zip(chain_names, api_paths)
    ]

    t = (
        "this template"
        if len(chain_names) == 1
        else f"these {len(chain_names)} templates"
    )
    lines = (
        ["", f"To use {t}, add the following to your app:\n\n```", ""]
        + imports
        + [""]
        + routes
        + ["```"]
    )
    typer.echo("\n".join(lines))


@app_cli.command()
def remove(
    api_paths: Annotated[List[str], typer.Argument(help="The API paths to remove")],
    *,
    project_dir: Annotated[
        Optional[Path], typer.Option(help="The project directory")
    ] = None,
):
    """
    Removes the specified package from the current LangServe app.
    """

    project_root = get_package_root(project_dir)

    project_pyproject = project_root / "pyproject.toml"

    package_root = project_root / "packages"

    remove_deps: List[str] = []

    for api_path in api_paths:
        package_dir = package_root / api_path
        if not package_dir.exists():
            typer.echo(f"Package {api_path} does not exist. Skipping...")
            continue
        try:
            pyproject = package_dir / "pyproject.toml"
            langserve_export = get_langserve_export(pyproject)
            typer.echo(f"Removing {langserve_export['package_name']}...")

            shutil.rmtree(package_dir)
            remove_deps.append(api_path)
        except Exception:
            pass

    try:
        remove_dependencies_from_pyproject_toml(project_pyproject, remove_deps)
    except Exception:
        # Can fail if user modified/removed pyproject.toml
        typer.echo("Failed to remove dependencies from pyproject.toml.")


@app_cli.command()
def serve(
    *,
    port: Annotated[
        Optional[int], typer.Option(help="The port to run the server on")
    ] = None,
    host: Annotated[
        Optional[str], typer.Option(help="The host to run the server on")
    ] = None,
    app: Annotated[
        Optional[str], typer.Option(help="The app to run, e.g. `app.server:app`")
    ] = None,
) -> None:
    """
    Starts the LangServe app.
    """

    # add current dir as first entry of path
    sys.path.append(str(Path.cwd()))

    app_str = app if app is not None else "app.server:app"
    host_str = host if host is not None else "127.0.0.1"

    import uvicorn

    uvicorn.run(
        app_str, host=host_str, port=port if port is not None else 8000, reload=True
    )
