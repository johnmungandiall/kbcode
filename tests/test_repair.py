from kbcode.repair import promote

ALLOWED = {"read_file", "write_file", "list_dir"}


def test_no_tool_calls_returns_original_text():
    text = "Sure, here is a plain answer with no tool call."
    calls, cleaned = promote(text, ALLOWED)
    assert calls == []
    assert cleaned == text


def test_empty_text_or_no_allowed_names():
    assert promote("", ALLOWED) == ([], "")
    assert promote("[read_file]\n{}", set()) == ([], "[read_file]\n{}")


def test_bracketed_call():
    text = '[read_file]\n{"path": "main.py"}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]
    assert cleaned == ""


def test_bracketed_call_with_tool_prefix():
    text = 'Before.\n[tool:read_file]\n{"path": "main.py"}\nAfter.'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]
    assert cleaned == "Before.\n\nAfter."


def test_bracketed_call_with_closing_marker_is_consumed():
    text = '[read_file]\n{"path": "main.py"}\n[/read_file]\ndone'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]
    assert cleaned == "done"


def test_tagged_call():
    text = '<read_file>{"path": "main.py"}</read_file>'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]
    assert cleaned == ""


def test_keyed_json_tool_and_arguments():
    text = '{"tool": "read_file", "arguments": {"path": "main.py"}}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]


def test_keyed_json_name_and_parameters():
    text = '{"name": "read_file", "parameters": {"path": "main.py"}}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]


def test_keyed_json_openai_function_shape_with_string_arguments():
    text = '{"function": {"name": "read_file", "arguments": "{\\"path\\": \\"main.py\\"}"}}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "main.py"})]


def test_disallowed_tool_name_not_promoted():
    text = '[delete_everything]\n{"path": "main.py"}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == []
    assert cleaned == text


def test_ordinary_json_the_user_pasted_is_not_promoted():
    text = 'Here is some config: {"host": "localhost", "port": 8080}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == []
    assert cleaned == text


def test_multiple_calls_in_order():
    text = (
        '[read_file]\n{"path": "a.py"}\n'
        'then\n'
        '[list_dir]\n{"path": "."}'
    )
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("read_file", {"path": "a.py"}), ("list_dir", {"path": "."})]
    assert cleaned == "then"


def test_missing_args_object_is_skipped():
    text = "[read_file] no json here at all"
    calls, cleaned = promote(text, ALLOWED)
    assert calls == []
    assert cleaned == text


def test_no_arguments_defaults_to_empty_dict():
    text = '{"name": "list_dir"}'
    calls, cleaned = promote(text, ALLOWED)
    assert calls == [("list_dir", {})]
