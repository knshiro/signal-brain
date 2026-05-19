"""signal-brain CLI."""
from __future__ import annotations
import datetime
import json
from pathlib import Path
import tomllib
import click
from signal_brain.llm import LLMClient
from signal_brain.ingest import run_ingest_data_layer
from signal_brain.indexing import bootstrap_brain_root, build_index, append_log
from signal_brain.linking import run_stage1, run_stage2
from signal_brain.lint import run_lint
from signal_brain.sources import resolve_source, AmbiguousSource, NoSourceFound


def _load_config(path: Path = Path("config.toml")) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise click.ClickException(f"Config file not found: {path.resolve()}")


def _paths_for(cfg: dict, source: str | None) -> tuple[str, Path, Path, Path]:
    """Resolve (source_name, source_path, data_dir, brain_dir).

    source_path is `out_root/<name>/data.json`.
    brain_dir is `brain_root/<name>/` — the unified agent-consumable folder.
    data_dir is `brain_dir/data/` — the regeneratable machine layer.
    """
    out_root = Path(cfg["paths"]["out_root"])
    try:
        name = resolve_source(source, out_root)
    except (AmbiguousSource, NoSourceFound) as e:
        raise click.ClickException(str(e))
    source_path = out_root / name / "data.json"
    brain_dir = Path(cfg["paths"]["brain_root"]) / name
    data_dir = brain_dir / "data"
    return name, source_path, data_dir, brain_dir


source_option = click.option(
    "--source", default=None,
    help="Conversation directory under out/. Auto-picked if exactly one exists.",
)


@click.group()
def main():
    """Signal conversation brain."""


@main.command()
@source_option
def ingest(source):
    """Build/refresh the data layer (L0->L2) for the given source."""
    cfg = _load_config()
    name, source_path, data_dir, brain_dir = _paths_for(cfg, source)
    llm_tag = LLMClient(default_model=cfg["llm"]["tagging_model"])
    tagging_cfg = cfg.get("tagging", {})
    stats = run_ingest_data_layer(
        source_path=source_path,
        data_dir=data_dir,
        llm=llm_tag,
        burst_threshold_min=cfg["bursts"]["threshold_minutes"],
        min_burst_count=cfg["arcs"]["min_burst_count"],
        min_msg_count=cfg["arcs"]["min_msg_count"],
        tagging_description=tagging_cfg.get("description", ""),
        tagging_seed_tags=tagging_cfg.get("seed_tags") or None,
    )
    log = brain_dir / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    append_log(log, f"## [{datetime.date.today().isoformat()}] ingest ({name}) | {stats}")
    click.echo(f"source: {name}")
    click.echo(json.dumps(stats, indent=2))


@main.command("build-wiki")
@source_option
def build_wiki_cmd(source):
    """Generate wiki pages for the given source from its data layer."""
    cfg = _load_config()
    name, _, data_dir, brain_dir = _paths_for(cfg, source)
    from signal_brain.wiki.build import build_wiki
    llm = LLMClient(default_model=cfg["llm"]["synthesis_model"])
    stats = build_wiki(
        data_dir=data_dir,
        wiki_dir=brain_dir,
        llm=llm,
        me=cfg["me"],
    )
    click.echo(f"source: {name}")
    click.echo(json.dumps(stats, indent=2))


@main.command("build-index")
@source_option
def build_index_cmd(source):
    """Regenerate the brain reader's guide and the per-source index."""
    cfg = _load_config()
    name, _, _, brain_dir = _paths_for(cfg, source)
    brain_root = Path(cfg["paths"]["brain_root"])
    brain_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_brain_root(brain_root)
    build_index(brain_dir, brain_dir / "index.md")
    click.echo(f"Wrote {brain_root}/AGENTS.md, {brain_root}/CLAUDE.md, {brain_dir}/index.md.")


@main.command("link")
@source_option
@click.option("--stage", type=click.Choice(["1", "2", "all"]), default="all")
def link_cmd(source, stage):
    """Build brain internal links (stage 1: deterministic; stage 2: LLM-assisted)."""
    cfg = _load_config()
    name, _, data_dir, brain_dir = _paths_for(cfg, source)
    if stage in ("1", "all"):
        run_stage1(brain_dir)
        click.echo(f"[{name}] Stage 1 (deterministic) done.")
    if stage in ("2", "all"):
        llm = LLMClient(default_model=cfg["llm"]["synthesis_model"])
        run_stage2(brain_dir, llm, data_dir=data_dir)
        click.echo(f"[{name}] Stage 2 (LLM lateral) done.")


@main.command()
@source_option
def lint(source):
    """Run health checks for the given source; write its lint-report.md."""
    cfg = _load_config()
    name, _, data_dir, brain_dir = _paths_for(cfg, source)
    run_lint(brain_dir, data_dir, brain_dir / "lint-report.md")
    click.echo(f"[{name}] Lint report written to {brain_dir / 'lint-report.md'}")


@main.command("evaluate-bursts")
@source_option
@click.option("--sample-size", type=int, default=20)
def evaluate_bursts_cmd(source, sample_size):
    """Sample burst boundaries for the given source and judge whether they feel natural."""
    cfg = _load_config()
    name, _, data_dir, _ = _paths_for(cfg, source)
    from signal_brain.evaluators import evaluate_bursts
    llm = LLMClient(default_model=cfg["llm"]["synthesis_model"])
    result = evaluate_bursts(data_dir, llm, sample_size=sample_size)
    click.echo(f"source: {name}")
    click.echo(json.dumps(result, indent=2))


@main.command("list-sources")
def list_sources_cmd():
    """List conversation directories available under out/."""
    cfg = _load_config()
    from signal_brain.sources import list_sources
    out_root = Path(cfg["paths"]["out_root"])
    sources = list_sources(out_root)
    if not sources:
        click.echo(f"No conversations found in {out_root}")
        return
    for s in sources:
        click.echo(s)


if __name__ == "__main__":
    main()
