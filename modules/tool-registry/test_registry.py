"""Correctness tests for the tool-registry scanner's bug-prone pure functions.

Run: python3 -m pytest test_registry.py  (or: python3 test_registry.py)

Only the two functions where a subtle bug would silently misclassify a
capability are pinned here: frontmatter parsing (what a tool IS) and the
cwd-ancestor check (whether a project tool is usable HERE). The filesystem
scan is exercised by the live `--self-test` invocation, not unit tests.
"""

import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "registry", pathlib.Path(__file__).with_name("registry.py")
)
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)


def test_parse_frontmatter_reads_name_and_description():
    text = "---\nname: watts\ndescription: Coordinator. Use when deciding dirs.\nuser-invocable: true\n---\n\n# Watts\nbody\n"
    fm = registry.parse_frontmatter(text)
    assert fm["name"] == "watts"
    assert fm["description"].startswith("Coordinator.")


def test_parse_frontmatter_missing_fields_are_empty_not_crash():
    fm = registry.parse_frontmatter("# no frontmatter here\njust body\n")
    assert fm["name"] == ""
    assert fm["description"] == ""


def test_parse_frontmatter_ignores_colon_in_body():
    # A `description:` further down the body must not be picked up.
    text = "---\nname: x\n---\nbody line description: not this one\n"
    fm = registry.parse_frontmatter(text)
    assert fm["description"] == ""


def test_is_within_true_for_cwd_inside_root():
    assert registry.is_within("/a/b/c", "/a/b") is True
    assert registry.is_within("/a/b", "/a/b") is True  # equal counts


def test_is_within_false_for_sibling_prefix_collision():
    # /a/foobar must NOT count as inside /a/foo (string-prefix trap).
    assert registry.is_within("/a/foobar", "/a/foo") is False


def test_is_within_false_for_unrelated_path():
    assert registry.is_within("/x/y", "/a/b") is False


def test_parse_frontmatter_folds_block_scalar_description():
    # Many skills write `description: >-` with the text on indented lines below.
    text = "---\nname: babysit\ndescription: >-\n  Watch the PRs\n  and report back.\nuser-invocable: true\n---\nbody\n"
    fm = registry.parse_frontmatter(text)
    assert fm["description"] == "Watch the PRs and report back."


def test_current_runtime_prefers_claude_when_both_markers_present():
    # This session runs Claude Code inside Cursor's IDE → both env families set.
    env = {"CLAUDECODE": "1", "CURSOR_WORKSPACE_LABEL": "x"}
    assert registry.current_runtime(env) == "claude"


def test_current_runtime_cursor_when_only_cursor_markers():
    assert registry.current_runtime({"CURSOR_SPAWN_CHAIN": "x"}) == "cursor"


def test_current_runtime_none_when_unknown():
    assert registry.current_runtime({"PATH": "/usr/bin"}) is None


def test_skill_runnable_flags_cursor_only_under_claude():
    cursor_only = registry._entry("skill", "canvas", "global", "/a", "", "cursor")
    shared = registry._entry("skill", "watts", "global", "/a", "", "claude+cursor")
    assert registry.skill_runnable(cursor_only, "claude") is False
    assert registry.skill_runnable(shared, "claude") is True
    # unknown runtime → don't claim it's unrunnable
    assert registry.skill_runnable(cursor_only, None) is True


def test_merge_runtimes_collapses_shared_global_skill():
    entries = [
        registry._entry("skill", "watts", "global", "/a", "d", "claude"),
        registry._entry("skill", "watts", "global", "/b", "d", "cursor"),
        registry._entry("skill", "octeth", "project:x", "/c", "d", "claude"),
    ]
    merged = registry.merge_runtimes(entries)
    watts = [e for e in merged if e["name"] == "watts"]
    assert len(watts) == 1
    assert watts[0]["runtime"] == "claude+cursor"
    # project-scoped entry untouched
    assert any(e["name"] == "octeth" and e["runtime"] == "claude" for e in merged)


if __name__ == "__main__":
    import sys
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL {name}: {e}")
    sys.exit(1 if failures else 0)
