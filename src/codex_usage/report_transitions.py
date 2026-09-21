"""Verified project-transition disclosure rendering."""
import html


def _project_transitions_section(
    project_transitions: list[dict[str, object]] | None,
) -> str:
    if not project_transitions:
        return ""

    rows = []
    for transition in project_transitions:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(transition.get('source_label', '')))}</td>"
            f"<td>{html.escape(str(transition.get('target_label', '')))}</td>"
            f"<td>{html.escape(str(transition.get('effective_from', '')))}</td>"
            f'<td class="num">{html.escape(str(transition.get("confidence", "")))}</td>'
            "</tr>"
        )

    return (
        '<section class="section">'
        "<h2>Project Transitions</h2>"
        '<p class="muted">Usage is split at verified local repository switch points.</p>'
        '<div class="table-wrap"><table>'
        '<thead><tr><th>From</th><th>To</th><th>Effective From</th><th class="num">Confidence</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table></div>"
        "</section>"
    )


