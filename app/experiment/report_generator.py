from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import ExperimentDefinition, ExperimentResult, ExperimentRun, ObjectiveDef

logger = logging.getLogger("engine.experiment.report_generator")


def _param_summary(run: ExperimentRun) -> str:
    """One-line parameter summary."""
    parts = []
    for k, v in sorted(run.parameters.items()):
        parts.append(f"{k}={v}")
    return ", ".join(parts)


def _objective_table_rows(runs: List[ExperimentRun], objectives: List[ObjectiveDef]) -> str:
    """Generate HTML table rows for objective values."""
    rows = []
    for idx, run in enumerate(runs[:20]):  # Top 20
        obj_cells = "".join(
            f"<td>{run.objective_values.get(o.name, 0.0):.4f}</td>"
            for o in objectives
        )
        params_short = ", ".join(
            f"{k}={v}"
            for k, v in list(run.parameters.items())[:4]
        )
        rows.append(
            f"<tr><td>{idx + 1}</td><td>{run.run_id}</td>"
            f"<td>{params_short}...</td>"
            f"<td>{run.evaluation_score:.4f}</td>"
            f"{obj_cells}</tr>"
        )
    return "\n".join(rows)


def generate_html_report(result: ExperimentResult) -> str:
    """Generate an HTML research report for an experiment."""
    d = result.definition
    obj = d.objectives

    champion_row = ""
    if result.champion:
        champ = result.champion
        obj_cells = "".join(
            f"<td>{champ.objective_values.get(o.name, 0.0):.4f}</td>"
            for o in obj
        )
        champion_row = (
            f"<h3>Champion Design</h3>"
            f"<p><b>Run ID:</b> {champ.run_id}</p>"
            f"<p><b>Evaluation Score:</b> {champ.evaluation_score:.4f}</p>"
            f"<p><b>Parameters:</b> {_param_summary(champ)}</p>"
            f"<table border='1' cellpadding='4'>"
            f"<tr><th>Metric</th>{''.join(f'<th>{o.name}</th>' for o in obj)}</tr>"
            f"<tr><td>Value</td>{obj_cells}</tr>"
            f"</table>"
        )

    # Pareto front table (top 20)
    pareto_rows = _objective_table_rows(result.pareto_ranked[:20], obj)

    # Statistics
    stats = ""
    if result.pareto_ranked:
        front0 = [r for r in result.pareto_ranked if r.passed]
        if front0:
            avg_score = sum(r.evaluation_score for r in front0) / len(front0)
            max_score = max(r.evaluation_score for r in front0)
            min_score = min(r.evaluation_score for r in front0)
            stats = (
                f"<h3>Population Statistics</h3>"
                f"<ul>"
                f"<li>Total variants evaluated: {result.total_runs}</li>"
                f"<li>Successful: {result.successful_runs}</li>"
                f"<li>Failed: {result.failed_runs}</li>"
                f"<li>Average evaluation score: {avg_score:.4f}</li>"
                f"<li>Best evaluation score: {max_score:.4f}</li>"
                f"<li>Worst evaluation score: {min_score:.4f}</li>"
                f"</ul>"
            )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Experiment Report - {d.name}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    h1, h2, h3 {{ color: #333; }}
    table {{ border-collapse: collapse; margin: 10px 0; }}
    th {{ background: #4a90d9; color: white; }}
    td, th {{ padding: 6px 12px; text-align: center; }}
    .summary {{ background: #f5f5f5; padding: 15px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>Engineering Experiment Report</h1>
  <div class="summary">
    <h2>{d.name}</h2>
    <p>{d.description}</p>
    <p><b>Machine Type:</b> {d.machine_type}</p>
    <p><b>Sample Method:</b> {d.sample_method.value} ({d.sample_count} variants)</p>
    <p><b>Experiment ID:</b> {result.experiment_id}</p>
  </div>

  {stats}
  {champion_row}

  <h3>Pareto Front (Top 20)</h3>
  <table border='1' cellpadding='4'>
    <tr>
      <th>Rank</th><th>Run ID</th><th>Parameters</th><th>Score</th>
      {''.join(f'<th>{o.name}</th>' for o in obj)}
    </tr>
    {pareto_rows if pareto_rows else '<tr><td colspan="4">No solutions in Pareto front.</td></tr>'}
  </table>
</body>
</html>"""
    return html


def generate_text_summary(result: ExperimentResult) -> str:
    """Generate a plain-text research summary."""
    d = result.definition
    lines = [
        "=" * 60,
        f"Engineering Experiment: {d.name}",
        f"Description: {d.description}",
        f"Machine Type: {d.machine_type}",
        f"Sample Method: {d.sample_method.value} ({d.sample_count} variants)",
        f"Experiment ID: {result.experiment_id}",
        "=" * 60,
        "",
        f"Results: {result.total_runs} variants evaluated",
        f"  Successful: {result.successful_runs}",
        f"  Failed: {result.failed_runs}",
        f"  Pareto front size: {len(result.pareto_ranked)}",
        "",
    ]

    if result.champion:
        champ = result.champion
        lines.append("Champion Design:")
        lines.append(f"  Run ID: {champ.run_id}")
        lines.append(f"  Score: {champ.evaluation_score:.4f}")
        lines.append("  Parameters:")
        for k, v in sorted(champ.parameters.items()):
            lines.append(f"    {k}: {v}")
        lines.append("  Objectives:")
        for o in d.objectives:
            val = champ.objective_values.get(o.name, 0.0)
            direction = "minimize" if o.minimize else "maximize"
            lines.append(f"    {o.name} ({direction}): {val:.4f}")
        lines.append("")

    if result.pareto_ranked:
        lines.append("Top 10 Pareto Solutions:")
        for idx, run in enumerate(result.pareto_ranked[:10]):
            obj_str = ", ".join(
                f"{o.name}={run.objective_values.get(o.name, 0.0):.3f}"
                for o in d.objectives
            )
            lines.append(f"  {idx + 1}. {run.run_id} score={run.evaluation_score:.3f} ({obj_str})")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
