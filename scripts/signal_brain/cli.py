"""signal-brain CLI.

The LLM-using stages (ingest, build-wiki, link --stage 2, evaluate-bursts) are
all two-phase: `--plan` emits a todo file, `--finalize` consumes a done file.
The agent (Claude Code or Codex) fills in the done file by dispatching subagents
between the two phases. No `ANTHROPIC_API_KEY` is required at any point.
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
import tomllib
import click
from signal_brain.ingest import run_ingest_plan, run_ingest_finalize
from signal_brain.indexing import bootstrap_brain_root, build_index, append_log
from signal_brain.linking import run_stage1
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


_PHASE_HELP = (
    "Use --plan to emit a todo file (no LLM). The agent fills in the matching "
    "done file by dispatching subagents. Then use --finalize to consume it."
)


def _require_phase(phase: str | None, command: str) -> str:
    if phase is None:
        raise click.ClickException(
            f"`{command}` is two-phase. {_PHASE_HELP}\n"
            "Or invoke the `signal-brain-build` skill to run the full pipeline."
        )
    return phase


@main.command()
@source_option
@click.option("--plan", "phase", flag_value="plan", default=None,
              help="Emit data/tagging.todo.jsonl. No LLM.")
@click.option("--finalize", "phase", flag_value="finalize", default=None,
              help="Consume data/tagging.done.jsonl; write chunks + arcs.")
def ingest(source, phase):
    """Build/refresh the data layer (L0->L2) for the given source.

    Two-phase. See --plan / --finalize.
    """
    phase = _require_phase(phase, "ingest")
    cfg = _load_config()
    name, source_path, data_dir, brain_dir = _paths_for(cfg, source)
    tagging_cfg = cfg.get("tagging", {})
    if phase == "plan":
        stats = run_ingest_plan(
            source_path=source_path,
            data_dir=data_dir,
            burst_threshold_min=cfg["bursts"]["threshold_minutes"],
            tagging_description=tagging_cfg.get("description", ""),
            tagging_seed_tags=tagging_cfg.get("seed_tags") or None,
        )
    else:
        stats = run_ingest_finalize(
            data_dir=data_dir,
            min_burst_count=cfg["arcs"]["min_burst_count"],
            min_msg_count=cfg["arcs"]["min_msg_count"],
        )
        log = brain_dir / "log.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        append_log(log, f"## [{datetime.date.today().isoformat()}] ingest ({name}) | {stats}")
    click.echo(f"source: {name} (phase: {phase})")
    click.echo(json.dumps(stats, indent=2))


@main.command("build-wiki")
@source_option
@click.option("--plan", "phase", flag_value="plan", default=None,
              help="Emit data/synthesis.todo.jsonl. No LLM.")
@click.option("--finalize", "phase", flag_value="finalize", default=None,
              help="Consume data/synthesis.done.jsonl; write wiki page markdown.")
def build_wiki_cmd(source, phase):
    """Generate wiki pages for the given source from its data layer.

    Two-phase. See --plan / --finalize.
    """
    phase = _require_phase(phase, "build-wiki")
    cfg = _load_config()
    name, _, data_dir, brain_dir = _paths_for(cfg, source)
    from signal_brain.wiki.build import build_wiki_plan, build_wiki_finalize
    todo_path = data_dir / "synthesis.todo.jsonl"
    done_path = data_dir / "synthesis.done.jsonl"
    if phase == "plan":
        stats = build_wiki_plan(
            data_dir=data_dir, wiki_dir=brain_dir, me=cfg["me"],
            todo_path=todo_path,
        )
    else:
        stats = build_wiki_finalize(
            data_dir=data_dir, wiki_dir=brain_dir,
            todo_path=todo_path, done_path=done_path,
        )
    click.echo(f"source: {name} (phase: {phase})")
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
@click.option("--stage", type=click.Choice(["1", "2"]), required=True)
@click.option("--plan", "phase", flag_value="plan", default=None,
              help="(--stage 2 only) emit data/link.todo.jsonl.")
@click.option("--finalize", "phase", flag_value="finalize", default=None,
              help="(--stage 2 only) consume data/link.done.jsonl.")
def link_cmd(source, stage, phase):
    """Build brain internal links.

    Stage 1: deterministic graph from page metadata. No LLM.
    Stage 2: lateral links proposed by the agent. Two-phase (--plan / --finalize).
    """
    cfg = _load_config()
    name, _, data_dir, brain_dir = _paths_for(cfg, source)
    if stage == "1":
        run_stage1(brain_dir)
        click.echo(f"[{name}] Stage 1 (deterministic) done.")
        return
    phase = _require_phase(phase, "link --stage 2")
    from signal_brain.linking import run_stage2_plan, run_stage2_finalize
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    if phase == "plan":
        stats = run_stage2_plan(brain_dir, todo_path, data_dir)
    else:
        stats = run_stage2_finalize(brain_dir, todo_path, done_path, data_dir)
    click.echo(f"[{name}] Stage 2 (phase: {phase}) {json.dumps(stats)}")


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
@click.option("--plan", "phase", flag_value="plan", default=None)
@click.option("--finalize", "phase", flag_value="finalize", default=None)
def evaluate_bursts_cmd(source, sample_size, phase):
    """Sample burst boundaries and judge whether they feel natural.

    Two-phase. See --plan / --finalize.
    """
    phase = _require_phase(phase, "evaluate-bursts")
    cfg = _load_config()
    name, _, data_dir, _ = _paths_for(cfg, source)
    from signal_brain.evaluators import evaluate_bursts_plan, evaluate_bursts_finalize
    todo_path = data_dir / "eval.todo.jsonl"
    done_path = data_dir / "eval.done.jsonl"
    if phase == "plan":
        result = evaluate_bursts_plan(data_dir, todo_path, sample_size=sample_size)
    else:
        result = evaluate_bursts_finalize(todo_path, done_path)
    click.echo(f"source: {name} (phase: {phase})")
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
