"""Tool-boundary invariants (spec §24). These must never be deleted."""

import ast
import pathlib

import pytest
from pydantic import ValidationError

from muse.tools.schema import ToolIntent

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "muse"
EXECUTORS_PACKAGE = "muse.tools.executors"
# Where the executor attribute may be read, and where executors may be imported.
EXECUTOR_READERS = {"tools/gateway.py"}
EXECUTOR_IMPORTERS = {"tools/specs.py"}


def modules() -> list[tuple[str, ast.Module]]:
    return [
        (str(path.relative_to(SRC)), ast.parse(path.read_text(), filename=str(path)))
        for path in SRC.rglob("*.py")
        if "executors" not in path.parts
    ]


@pytest.mark.parametrize(
    "field", ["risk", "side_effect", "required_permissions", "data_classification"]
)
def test_model_output_cannot_carry_classification(field: str):
    with pytest.raises(ValidationError):
        ToolIntent.model_validate({"tool": "clock.now", "args": {}, field: "READ_ONLY"})


def test_tool_intent_has_only_tool_and_args():
    assert set(ToolIntent.model_fields) == {"tool", "args"}


def test_only_specs_imports_executors():
    offenders = []
    for rel, tree in modules():
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if (
                any(n.startswith(EXECUTORS_PACKAGE) for n in names)
                and rel not in EXECUTOR_IMPORTERS
            ):
                offenders.append(rel)
    assert offenders == []


def test_only_the_gateway_reads_executors():
    offenders = [
        f"{rel}:{node.lineno}"
        for rel, tree in modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "executor"
        and rel not in EXECUTOR_READERS
    ]
    assert offenders == []


def test_agents_reach_tools_only_via_gateway_invoke():
    for rel, tree in modules():
        if not rel.startswith("agents/"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "muse.tools.registry":
                # Registry is allowed for listing specs; proposing/executing is not.
                assert all(a.name == "ToolRegistry" for a in node.names), rel
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"propose", "evaluate", "record_decision"}, rel


BROWSER_SURFACE = {
    "browser.open_session",
    "browser.navigate",
    "browser.snapshot",
    "browser.screenshot",
    "browser.click",
    "browser.fill",
    "browser.press",
    "browser.scroll",
    "browser.download",
    "browser.close_session",
}
SCRIPT_RUNNERS = {
    "evaluate",
    "evaluate_handle",
    "add_init_script",
    "expose_function",
    "new_cdp_session",
}
SCRIPT_ALLOWED_IN = {"browser/snapshot.py"}


def test_the_browser_surface_is_exactly_the_spec_list():
    from muse.tools.specs import build_registry

    names = {s.name for s in build_registry().specs() if s.name.startswith("browser.")}
    assert names == BROWSER_SURFACE
    assert not any(
        word in s.name for s in build_registry().specs() for word in ("eval", "script", "cdp", "js")
    )


def imports_playwright(tree: ast.Module) -> bool:
    return any(
        (isinstance(n, ast.ImportFrom) and (n.module or "").startswith("playwright"))
        or (isinstance(n, ast.Import) and any(a.name.startswith("playwright") for a in n.names))
        for n in ast.walk(tree)
    )


def test_page_scripts_run_only_in_the_trusted_snapshot_module():
    offenders = [
        f"{rel}:{node.lineno}"
        for rel, tree in modules()
        if imports_playwright(tree)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in SCRIPT_RUNNERS
        and rel not in SCRIPT_ALLOWED_IN
    ]
    assert offenders == []


def test_only_the_browser_package_touches_playwright():
    users = {rel for rel, tree in modules() if imports_playwright(tree)}
    assert users <= {"browser/controller.py", "browser/snapshot.py"}, users
