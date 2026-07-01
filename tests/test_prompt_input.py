from kbcode.prompt_input import suggest

COMMANDS = [
    ("/help", "Show help"),
    ("/cost", "Show cost summary"),
    ("/compact", "Compact the conversation"),
    ("/provider <name>", "Switch provider"),
]


def test_non_slash_text_returns_no_suggestions():
    assert suggest("just a normal message", COMMANDS) == []
    assert suggest("", COMMANDS) == []


def test_slash_alone_lists_all_commands():
    results = suggest("/", COMMANDS)
    names = [r[0] for r in results]
    assert names == ["/help", "/cost", "/compact", "/provider"]


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
