"""vrmforge CLI."""
from __future__ import annotations

import json as jsonlib
import sys
from pathlib import Path

import click

from vrmforge.glb import Glb, GlbError
from vrmforge.ops import ApplyError, build as build_avatar, inspect as inspect_glb
from vrmforge.spec import AvatarSpec


@click.group()
@click.version_option(package_name="vrmforge")
def main() -> None:
    """Build VRM 1.0 avatars from a YAML spec."""


@main.command()
@click.argument("spec_path", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--out", required=True, type=click.Path(dir_okay=False))
@click.option("--dry-run", is_flag=True, help="report changes without writing")
def build(spec_path: str, out: str, dry_run: bool) -> None:
    """Apply SPEC_PATH to its base VRM and write the result."""
    try:
        spec = AvatarSpec.load(spec_path)
        glb, changes = build_avatar(spec)
    except (ApplyError, GlbError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    click.echo(f"base: {spec.base}")
    if not changes:
        click.echo("no changes declared in spec")
    for line in changes:
        click.echo(f"  {line}")

    if dry_run:
        click.echo("\ndry run — nothing written")
        return

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    written = glb.save(out)
    click.echo(f"\nwrote {out} ({written:,} bytes, {len(changes)} change(s) applied)")


@main.command()
@click.argument("vrm_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def inspect(vrm_path: str, as_json: bool) -> None:
    """Report what is actually inside a VRM."""
    try:
        report = inspect_glb(Glb.load(vrm_path))
    except GlbError as exc:
        raise SystemExit(f"error: {exc}") from exc

    if as_json:
        click.echo(jsonlib.dumps(report, indent=2, ensure_ascii=False))
        return

    click.echo(f"{Path(vrm_path).name}")
    click.echo(f"  VRM spec      : {report['spec_version']}")
    meta = report["meta"]
    click.echo(f"  name / authors: {meta.get('name')} / {meta.get('authors')}")
    click.echo(f"  licence       : {meta.get('licenseUrl') or '(unset)'}")
    click.echo(
        f"  permissions   : avatar={meta.get('avatarPermission')} "
        f"commercial={meta.get('commercialUsage')} "
        f"mod={meta.get('modification')} redistrib={meta.get('allowRedistribution')}"
    )
    click.echo(f"  humanoid bones: {report['humanoid_bones']}")
    click.echo(f"  spring bones  : {report['spring_bones']} spring(s)")
    click.echo(f"  extensions    : {', '.join(report['extensions'])}")
    click.echo(f"  expressions   : {', '.join(report['expressions']) or '(none)'}")
    if report["custom_expressions"]:
        click.echo(f"  custom expr   : {', '.join(report['custom_expressions'])}")
    click.echo("  meshes:")
    for m in report["meshes"]:
        click.echo(
            f"    {m['name']:<24} primitives={m['primitives']:<3} "
            f"morph_targets={m['morph_targets']}"
        )
    click.echo(f"  materials ({len(report['materials'])}):")
    for name in report["materials"]:
        click.echo(f"    {name}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
