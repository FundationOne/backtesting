"""
Reusable multi-select filter component for Dash.

Renders as a <details> toggle with a checklist panel, "Select All" / "Clear All"
actions, and a summary label showing "N / M" when not all items are selected.

Usage (layout):
    from components.multi_select import multi_filter, register_multi_select_callbacks

    multi_filter("my-filter", "All items")
    multi_filter("my-filter", "All items", options=[{"label": "A", "value": "a"}, ...])

Usage (callbacks):
    register_multi_select_callbacks(app, [
        ("my-filter", "All items"),
    ])
"""

from dash import html, dcc, Input, Output, State


# ── Layout helper ───────────────────────────────────────────────────────

def multi_filter(fid, placeholder, options=None):
    """Return a custom multi-select widget.

    Parameters
    ----------
    fid : str
        The Dash component ID for the inner ``dcc.Checklist``.
        Auxiliary IDs are derived: ``{fid}-summary``, ``{fid}-selall``,
        ``{fid}-clrall``.
    placeholder : str
        Text shown in the closed toggle when all (or no) items are selected.
    options : list[dict] | None
        Static options (``[{"label": …, "value": …}, …]``).  Leave empty when
        options are populated dynamically by a server callback.
    """
    opts = options or []
    return html.Details([
        html.Summary([
            html.Span(placeholder, id=f"{fid}-summary", className="bs-ms-text"),
            html.I(className="bi bi-chevron-down bs-ms-chevron"),
        ], className="bs-ms-toggle"),
        html.Div([
            html.Div([
                html.Button("Select All", id=f"{fid}-selall", n_clicks=0,
                            className="bs-ms-action", type="button"),
                html.Span("·", className="mx-1 text-muted small"),
                html.Button("Clear All", id=f"{fid}-clrall", n_clicks=0,
                            className="bs-ms-action", type="button"),
            ], className="bs-ms-actions"),
            dcc.Checklist(
                id=fid,
                options=opts,
                value=[o["value"] for o in opts],
                className="bs-ms-checklist",
                inputClassName="bs-ms-checkbox",
                labelClassName="bs-ms-label",
            ),
        ], className="bs-ms-panel"),
    ], className="bs-multiselect")


# ── Callback registration ──────────────────────────────────────────────

def register_multi_select_callbacks(app, filters, *, outside_click_output=None):
    """Register clientside callbacks for a list of multi-select filters.

    Parameters
    ----------
    app : dash.Dash
        The Dash application instance.
    filters : list[tuple[str, str]]
        Each entry is ``(component_id, all_label)`` where *all_label* is the
        text displayed when every option is selected (e.g. ``"All categories"``).
    outside_click_output : tuple | None
        ``(component_id, property)`` for the outside-click initialiser callback.
        Defaults to the first filter's summary ``title`` property.
    """
    for _fid, _all_label in filters:
        # Select All
        app.clientside_callback(
            """function(nAll, opts) {
                if (!nAll) return dash_clientside.no_update;
                return (opts || []).map(function(o){ return o.value; });
            }""",
            Output(_fid, "value", allow_duplicate=True),
            Input(f"{_fid}-selall", "n_clicks"),
            State(_fid, "options"),
            prevent_initial_call=True,
        )

        # Clear All
        app.clientside_callback(
            """function(nClr) {
                if (!nClr) return dash_clientside.no_update;
                return [];
            }""",
            Output(_fid, "value", allow_duplicate=True),
            Input(f"{_fid}-clrall", "n_clicks"),
            prevent_initial_call=True,
        )

        # Summary label  (e.g.  "3 / 12"  or  "All categories")
        app.clientside_callback(
            """function(val, opts) {{
                var total = (opts && opts.length) ? opts.length : 0;
                var sel = (val && val.length) ? val.length : 0;
                if (total === 0) return "{all_label}";
                if (sel === 0) return "0 / " + total;
                if (sel === total) return "{all_label}";
                return sel + " / " + total;
            }}""".format(all_label=_all_label),
            Output(f"{_fid}-summary", "children"),
            [Input(_fid, "value"), Input(_fid, "options")],
        )

    # Outside-click handler — close any open panel when clicking elsewhere
    oc = outside_click_output or (f"{filters[0][0]}-summary", "title")
    app.clientside_callback(
        """function(p) {
            if (!window._bsMsOutsideClick) {
                window._bsMsOutsideClick = true;
                document.addEventListener("click", function(e) {
                    document.querySelectorAll(".bs-multiselect[open]").forEach(function(el) {
                        if (!el.contains(e.target)) el.removeAttribute("open");
                    });
                });
            }
            return dash_clientside.no_update;
        }""",
        Output(*oc),
        Input("url", "pathname"),
    )
