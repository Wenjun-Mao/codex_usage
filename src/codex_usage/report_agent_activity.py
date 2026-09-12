from __future__ import annotations

import html

from codex_usage.agent_activity import AgentActivity
from codex_usage.report_tables import format_int


def agent_activity_css() -> str:
    """Return styles owned by the Agent Activity report section."""
    return """
    .agent-activity-agents { margin-top: 16px; }
    .agent-activity-agents > summary { cursor: pointer; }
    """


def render_agent_activity_section(activity: AgentActivity | None) -> str:
    """Render the bounded Agent Activity dashboard from report-scoped data."""
    if activity is None:
        return ""
    daily_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row.day)}</td>"
        f'<td class="num">{format_int(row.totals.usage.total_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.input_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.cached_input_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.output_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.reasoning_output_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.responses)}</td>'
        f'<td class="num">{format_int(row.active_root_tasks)}</td>'
        f'<td class="num">{format_int(row.active_subagents)}</td>'
        "</tr>"
        for row in activity.daily_rows
    )
    visible_agents = activity.agent_rows[:50]
    agent_rows = "".join(
        "<tr>"
        f"<td><strong>{html.escape(row.label)}</strong><small>{html.escape(row.agent_id)}</small></td>"
        f"<td>{html.escape(row.role)}</td>"
        f"<td><code>{html.escape(row.root_task_id)}</code></td>"
        f"<td>{html.escape(', '.join(label for _, label in row.projects) or 'Unassigned')}</td>"
        f'<td class="num">{format_int(row.active_days)}</td>'
        f'<td class="num">{format_int(row.totals.usage.input_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.cached_input_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.output_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.reasoning_output_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.usage.total_tokens)}</td>'
        f'<td class="num">{format_int(row.totals.responses)}</td>'
        "</tr>"
        for row in visible_agents
    )
    return (
        '<section class="section agent-activity" data-report-section="agent-activity">'
        "<h2>Agent Activity</h2>"
        '<p class="muted section-help">Responses count positive cumulative-usage deltas, including tool-driven or internal model cycles; they are not user-message counts. Cached input is included in Input and reasoning is included in Output.</p>'
        "<h3>Daily Summary</h3>"
        '<div class="table-wrap"><table><thead><tr><th>Date</th><th class="num">Total</th><th class="num">Input</th><th class="num">Cached Input</th><th class="num">Output</th><th class="num">Reasoning</th><th class="num">Responses</th><th class="num">Root Tasks</th><th class="num">Subagents</th></tr></thead><tbody>'
        f"{daily_rows}</tbody></table></div>"
        "<h3>Agents</h3>"
        '<details class="agent-activity-agents">'
        f'<summary>Show {len(visible_agents):,} of {len(activity.agent_rows):,} agents by total tokens.</summary>'
        '<p class="muted section-help">Export Agent Activity CSV includes every selected agent-day row.</p>'
        '<div class="table-wrap"><table><thead><tr><th>Agent</th><th>Role</th><th>Root Task</th><th>Projects</th><th class="num">Days</th><th class="num">Input</th><th class="num">Cached Input</th><th class="num">Output</th><th class="num">Reasoning</th><th class="num">Total</th><th class="num">Responses</th></tr></thead><tbody>'
        f"{agent_rows}</tbody></table></div></details></section>"
    )
