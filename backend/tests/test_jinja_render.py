"""Tests for app.runner.jinja_render (design.md §5.3 / §5.3.2 / §14 R13)."""

from __future__ import annotations

from typing import Any

import pytest
from jinja2 import UndefinedError
from jinja2.exceptions import TemplateSyntaxError

from app.runner.jinja_render import TemplateRenderError, decide_ssh_user, render


@pytest.mark.parametrize(
    "template_str, context, expected",
    [
        # Simple substitution against coordinator.host.
        (
            "{{ coordinator.host }}",
            {"coordinator": {"host": "synxdb-0001"}},
            "synxdb-0001",
        ),
        # Nested external.<svc>.<attr> lookup.
        (
            "{{ external.minio.endpoint }}",
            {"external": {"minio": {"endpoint": "http://minio.local:9000"}}},
            "http://minio.local:9000",
        ),
        # Filters are available (upper).
        (
            "{{ name | upper }}",
            {"name": "gpadmin"},
            "GPADMIN",
        ),
        # autoescape=False: HTML metacharacters pass through unmodified.
        # We render shell / sql, not html, so '<', '>', '&', etc. must NOT
        # be turned into entities.
        (
            "{{ raw }}",
            {"raw": '<a href="x">&copy;</a>'},
            '<a href="x">&copy;</a>',
        ),
    ],
)
def test_render_success(template_str: str, context: dict[str, Any], expected: str) -> None:
    assert render(template_str, context) == expected


def test_render_undefined_variable_raises() -> None:
    with pytest.raises(TemplateRenderError) as exc_info:
        render("{{ coordinator.host }}", {})
    err = exc_info.value
    assert "undefined variable" in str(err)
    assert isinstance(err.original, UndefinedError)


def test_render_undefined_nested_attribute_raises() -> None:
    # external.minio defined but .endpoint not — StrictUndefined treats
    # this as an error too, not as a silent empty string.
    with pytest.raises(TemplateRenderError) as exc_info:
        render("{{ external.minio.endpoint }}", {"external": {"minio": {}}})
    err = exc_info.value
    assert "undefined variable" in str(err)
    assert isinstance(err.original, UndefinedError)


def test_render_syntax_error_raises() -> None:
    # Unbalanced '{{' is a TemplateSyntaxError raised at parse time
    # (from_string), and is wrapped in TemplateRenderError by the
    # generic except-Exception branch.
    with pytest.raises(TemplateRenderError) as exc_info:
        render("{{ unbalanced", {})
    err = exc_info.value
    assert isinstance(err.original, TemplateSyntaxError)


@pytest.mark.parametrize(
    "host, dut_hosts, expected_user",
    [
        # host is in DUT set → gpadmin
        ("sdw1", {"sdw1", "sdw2"}, "gpadmin"),
        # host is outside DUT set (build / CI box) → root
        ("build-host-7", {"sdw1", "sdw2"}, "root"),
        # host=None → coordinator-local default, gpadmin
        (None, {"sdw1"}, "gpadmin"),
        # coordinator host NOT in dut_hosts in this fixture → root
        # (operator's responsibility to add coordinator to dut_hosts
        # if they want gpadmin there; we don't infer.)
        ("synxdb-0001", set(), "root"),
        # empty dut_hosts and arbitrary host → root
        ("anything", set(), "root"),
    ],
)
def test_decide_ssh_user(host: str | None, dut_hosts: set[str], expected_user: str) -> None:
    assert decide_ssh_user(host, dut_hosts) == expected_user
