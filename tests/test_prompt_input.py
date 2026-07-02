import os

from kbcode.prompt_input import PATH_COMMANDS, suggest

COMMANDS = [
    ("/help", "Show help"),
    ("/cost", "Show cost summary"),
    ("/compact", "Compact the conversation"),
    ("/provider <name>", "Switch provider"),
    ("/open <folder>", "Switch project folder"),
]


def test_non_slash_text_returns_no_suggestions():
    assert suggest("just a normal message", COMMANDS) == []
    assert suggest("", COMMANDS) == []


def test_slash_alone_lists_all_commands():
    results = suggest("/", COMMANDS)
    names = [r[0] for r in results]
    assert names == ["/help", "/cost", "/compact", "/provider", "/open"]


def test_partial_command_filters_by_prefix():
    results = suggest("/co", COMMANDS)
    names = [r[0] for r in results]
    assert names == ["/cost", "/compact"]


def test_unmatched_prefix_returns_empty():
    assert suggest("/zzz", COMMANDS) == []


def test_argument_completion_uses_arg_options():
    arg_options = {"/provider": ["anthropic", "openai", "openrouter"]}
    results = suggest("/provider an", COMMANDS, arg_options)
    names = [r[0] for r in results]
    assert names == ["anthropic"]


def test_argument_completion_with_no_options_for_command():
    results = suggest("/help x", COMMANDS)
    assert results == []


def test_argument_completion_returns_all_when_word_empty():
    arg_options = {"/provider": ["anthropic", "openai"]}
    results = suggest("/provider ", COMMANDS, arg_options)
    names = [r[0] for r in results]
    assert names == ["anthropic", "openai"]


def test_static_list_completes_first_argument_only():
    # A plain list is for the first argument; it must NOT reappear for later
    # words (the old behavior re-suggested provider names where a model goes).
    arg_options = {"/provider": ["anthropic", "openai"]}
    assert suggest("/provider deepseek ", COMMANDS, arg_options) == []


def test_callable_arg_options_receive_words_after_command():
    seen = []

    def options(args):
        seen.append(list(args))
        return ["deepseek-chat", "deepseek-reasoner"]

    results = suggest("/provider deepseek deepseek-c", COMMANDS, {"/provider": options})
    assert seen == [["deepseek", "deepseek-c"]]
    assert [r[0] for r in results] == ["deepseek-chat"]


def test_callable_arg_options_exception_means_no_popup():
    def boom(args):
        raise RuntimeError("network down")

    assert suggest("/provider deepseek ", COMMANDS, {"/provider": boom}) == []


# --- path completion (#9) --------------------------------------------------


def test_path_command_completes_files_and_folders(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden").write_text("x", encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        results = suggest("/open ", COMMANDS)
    finally:
        os.chdir(cwd)
    names = {r[0] for r in results}
    assert "src" + os.sep in names  # directories carry a trailing separator
    assert "readme.md" in names
    assert ".hidden" not in names  # hidden entries stay hidden until the dot is typed


def test_path_completion_filters_by_typed_prefix(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        results = suggest("/open al", COMMANDS)
    finally:
        os.chdir(cwd)
    assert [r[0] for r in results] == ["alpha" + os.sep]


def test_path_completion_only_for_first_argument():
    # /video takes <path> [question]; once past the path, no more path popups.
    assert suggest("/video some.mp4 what", COMMANDS) == []


def test_non_path_command_gets_no_path_completion(tmp_path):
    (tmp_path / "src").mkdir()
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        results = suggest("/help ", COMMANDS)
    finally:
        os.chdir(cwd)
    assert results == []


def test_path_commands_cover_the_path_taking_slash_commands():
    assert {"/open", "/image", "/video"} <= PATH_COMMANDS


def test_callable_returns_tuples_with_metadata():
    """Callables can return (name, meta) tuples for richer autocomplete display."""

    def provider_args(args):
        if len(args) <= 1:
            return [("anthropic", "current"), ("openai", ""), ("gemini", "")]
        return []

    cmds = [("/provider", "Switch provider")]
    results = suggest("/provider ", cmds, {"/provider": provider_args})
    expected = [
        ("anthropic", "anthropic", "current"),
        ("openai", "openai", ""),
        ("gemini", "gemini", ""),
    ]
    assert results == expected


def test_callable_mixed_strings_and_tuples():
    """A callable can mix plain strings and (name, meta) tuples."""

    def mixed_args(args):
        return ["plain-one", ("with-meta", "extra info"), "plain-two"]

    cmds = [("/test", "Test")]
    results = suggest("/test x", cmds, {"/test": mixed_args})
    # The user typed 'x' which matches nothing here, so
    # depending on what 'x' matches, just verify the handling works.
    # Actually test with a prefix that matches.
    results = suggest("/test p", cmds, {"/test": mixed_args})
    assert results == [
        ("plain-one", "plain-one", ""),
        ("plain-two", "plain-two", ""),
    ]


def test_callable_tuple_filters_by_prefix():
    """Tuple candidates are filtered by the name prefix, not the meta."""

    def opts(args):
        return [("gpt-4o", "current"), ("gpt-4o-mini", ""), ("claude-opus", "")]

    cmds = [("/model", "Switch model")]
    results = suggest("/model gpt", cmds, {"/model": opts})
    assert results == [
        ("gpt-4o", "gpt-4o", "current"),
        ("gpt-4o-mini", "gpt-4o-mini", ""),
    ]
