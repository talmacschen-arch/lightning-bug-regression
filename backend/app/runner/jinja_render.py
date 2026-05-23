"""Jinja2 template rendering for case step.run (design.md §5.3 / §5.3.2 / §14 R13).

Templates use StrictUndefined — any reference to an unbound variable
raises UndefinedError, which the orchestrator catches and converts to a
case-level ERROR (NOT a per-step fail — undefined-variable bugs in the
template are author errors, not runtime DUT failures).

Context shape (callers should populate):
  coordinator:
    host: "synxdb-0001"     # str — coordinator hostname
  external:
    <svc_name>: {...}       # arbitrary JSON pulled from system_settings

decide_ssh_user (§5.3.2 / §14 R13):
  Decide which user to ssh as for a given host:
    - host in dut_hosts            → "gpadmin"
    - host is None                 → "gpadmin"   (callers without a host
                                                  default to coordinator-local
                                                  gpadmin shell)
    - else                         → "root"

R13 historical context (Run 47 forensic): early prototype used
'gpadmin@<host>' unconditionally, which broke when shelling onto
build/CI boxes where gpadmin doesn't exist. Now: only DUT hosts get
gpadmin; everything else gets root.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined, UndefinedError


class TemplateRenderError(Exception):
    """Wraps Jinja errors so callers can catch one exception type.
    .original holds the underlying jinja2 exception for diagnostic."""

    def __init__(self, message: str, original: Exception | None = None) -> None:
        super().__init__(message)
        self.original = original


_env = Environment(
    undefined=StrictUndefined,
    autoescape=False,  # we render shell / sql, not html
    keep_trailing_newline=True,
)


def render(template_str: str, context: dict[str, Any]) -> str:
    """Render template_str against context. Raises TemplateRenderError on
    Jinja syntax error or undefined variable reference."""
    try:
        tmpl = _env.from_string(template_str)
        return tmpl.render(**context)
    except UndefinedError as e:
        raise TemplateRenderError(f"undefined variable: {e}", original=e) from e
    except Exception as e:
        raise TemplateRenderError(f"{type(e).__name__}: {e}", original=e) from e


def decide_ssh_user(host: str | None, dut_hosts: set[str]) -> str:
    """§5.3.2 / §14 R13 — return ssh user for given host.

    Args:
      host: target hostname (None → coordinator-local, treat as gpadmin)
      dut_hosts: set of DUT hostnames (loaded from system_settings.dut_hosts)

    Returns:
      "gpadmin" if host is None or host ∈ dut_hosts
      "root"    otherwise
    """
    if host is None:
        return "gpadmin"
    return "gpadmin" if host in dut_hosts else "root"
