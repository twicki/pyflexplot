"""CLI for preset setup files."""
# Standard library
import sys
from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence

# Third-party
import click
from click import Context

# Local
from ..utils.exceptions import NoPresetFileFoundError
from ..utils.logging import log
from ..utils.typing import ClickParamType
from .click import click_error
from .click import click_exit
from .preset import cat_preset
from .preset import collect_preset_files
from .preset import collect_preset_files_flat


# pylint: disable=W0613  # unused-argument (param)
def click_cat_preset_and_exit(ctx: Context, param: ClickParamType, value: Any) -> None:
    """Print the content of a preset setup file and exit."""
    if not value:
        return
    verbosity = ctx.obj["verbosity"]
    try:
        content = cat_preset(value, include_source=(verbosity > 0))
    except NoPresetFileFoundError:
        click_error(ctx, f"preset '{value}' not found")
    else:
        click_exit(ctx, content)


# pylint: disable=R0912  # too-many-branches
# pylint: disable=W0613  # unused-argument (param)
def click_use_preset(ctx: Context, param: ClickParamType, value: Any) -> None:
    if not value:
        return

    if value == ("?",):
        log(vbs="Available presets ('?'):")
        _click_list_presets(ctx, collect_preset_files("*"))
        ctx.exit(0)

    patterns: Sequence[str] = value
    antipatterns: Sequence[str] = ctx.params.get("preset_skip", [])

    key = "preset_setup_file_paths"
    if key not in ctx.obj:
        ctx.obj[key] = []

    for pattern in patterns:
        try:
            files_by_preset_path = collect_preset_files([pattern], antipatterns)
        except NoPresetFileFoundError as e:
            msg = f"no preset setup file found for '{pattern}'"
            if ctx.obj["raise"]:
                raise Exception(msg) from e
            else:
                click.echo(f"Error: {msg}", file=sys.stderr)
                _click_propose_alternatives(pattern)
                ctx.exit(1)
        else:
            n = sum([len(files) for files in files_by_preset_path.values()])
            if n == 0:
                log(vbs="Collected no preset setup files")
            elif n == 1:
                log(vbs=f"Collected {n} preset setup file:")
            else:
                log(vbs=f"Collected {n} preset setup files:")
            _click_list_presets(ctx, files_by_preset_path, indent_all=True)
        for files in files_by_preset_path.values():
            for path in files.values():
                if path not in ctx.obj[key]:
                    ctx.obj[key].append(path)


def _click_list_presets(
    ctx: Context,
    files_by_preset_path: Mapping[Path, Mapping[str, Path]],
    indent_all: bool = False,
) -> None:
    for preset_path, files in files_by_preset_path.items():
        log(vbs=f"{preset_path}:")
        for name, path in files.items():
            log(
                inf=name,
                vbs=f"{'  ' if indent_all else ''} {name}",
                dbg=f"  {name:23}  {path}",
            )


def _click_propose_alternatives(name: str) -> None:
    try:
        alternatives = collect_preset_files_flat(f"*{name}*")
    except NoPresetFileFoundError:
        pass
    else:
        if alternatives:
            click.echo("Looking for any of these?", file=sys.stderr)
            click.echo(" " + "\n ".join(alternatives.keys()), file=sys.stderr)
