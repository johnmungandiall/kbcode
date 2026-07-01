from kbcode import redact


def test_openai_style_key_is_masked():
    text = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx"
    out = redact.redact_sensitive_text(text)
    assert "sk-abcdefghijklmnopqrstuvwx" not in out


def test_prefix_match_alone_keeps_debug_affixes():
    # code_file=True skips the env-assignment pass, isolating the prefix-match
    # behavior: first 6 / last 4 chars are kept for debuggability.
    text = "key = sk-abcdefghijklmnopqrstuvwx"
    out = redact.redact_sensitive_text(text, code_file=True)
    assert "sk-abcdefghijklmnopqrstuvwx" not in out
    assert "sk-abc" in out
    assert "uvwx" in out


def test_github_pat_is_masked():
    token = "ghp_" + "a" * 36
    out = redact.redact_sensitive_text(f"token: {token}")
    assert token not in out


def test_aws_access_key_is_masked():
    token = "AKIAABCDEFGHIJKLMNOP"
    out = redact.redact_sensitive_text(f"key={token}")
    assert token not in out


def test_env_assignment_redacted_by_default():
    text = 'DB_PASSWORD=hunter2superlongsecretvalue'
    out = redact.redact_sensitive_text(text)
    assert "hunter2superlongsecretvalue" not in out


def test_env_assignment_not_touched_for_code_file():
    text = "MAX_TOKENS=100"
    out = redact.redact_sensitive_text(text, code_file=True)
    assert out == text


def test_json_field_redacted_by_default():
    text = '{"apiKey": "verylongsecretvaluehere123"}'
    out = redact.redact_sensitive_text(text)
    assert "verylongsecretvaluehere123" not in out


def test_json_field_not_touched_for_code_file():
    text = '{"apiKey": "test"}'
    out = redact.redact_sensitive_text(text, code_file=True)
    assert out == text


def test_authorization_header_redacted():
    text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789"
    out = redact.redact_sensitive_text(text)
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in out
    assert out.startswith("Authorization: Bearer")


def test_private_key_block_redacted():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"
    out = redact.redact_sensitive_text(text)
    assert "MIIB" not in out
    assert "[REDACTED PRIVATE KEY]" in out


def test_db_connection_string_password_redacted():
    text = "postgres://user:supersecretpassword@localhost:5432/db"
    out = redact.redact_sensitive_text(text)
    assert "supersecretpassword" not in out
    assert "postgres://user:***@" in out


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    out = redact.redact_sensitive_text(f"token is {jwt}")
    assert jwt not in out


def test_non_matching_text_passes_through_unchanged():
    text = "just a normal sentence with no secrets in it"
    assert redact.redact_sensitive_text(text) == text


def test_redaction_can_be_disabled(monkeypatch):
    monkeypatch.setattr(redact, "_REDACT_ENABLED", False)
    text = "sk-abcdefghijklmnopqrstuvwx"
    assert redact.redact_sensitive_text(text) == text


def test_is_env_dump_command_detects_env_and_printenv():
    assert redact.is_env_dump_command("env")
    assert redact.is_env_dump_command("printenv")
    assert redact.is_env_dump_command("cd /tmp && env")
    assert redact.is_env_dump_command("env | grep KEY")


def test_is_env_dump_command_false_for_normal_commands():
    assert not redact.is_env_dump_command("ls -la")
    assert not redact.is_env_dump_command(None)
    assert not redact.is_env_dump_command("")


def test_redact_terminal_output_uses_env_dump_pass_for_env_command():
    output = "SECRET_TOKEN=abcdefghijklmnopqrstuvwxyz"
    out = redact.redact_terminal_output(output, command="env")
    assert "abcdefghijklmnopqrstuvwxyz" not in out


def test_redact_terminal_output_skips_env_pass_for_code_like_output():
    output = "MAX_TOKENS=100"
    out = redact.redact_terminal_output(output, command="cat config.py")
    assert out == output


def test_redact_with_count_reports_zero_for_clean_text():
    text, count = redact.redact_with_count("nothing secret here")
    assert text == "nothing secret here"
    assert count == 0


def test_redact_with_count_counts_each_masked_secret():
    text = "sk-" + "a" * 20 + " and ghp_" + "b" * 20
    out, count = redact.redact_with_count(text, code_file=True)
    assert count == 2
    assert "aaaaaaaaaaaaaaaaaaaa" not in out
    assert "bbbbbbbbbbbbbbbbbbbb" not in out


def test_redact_with_count_disabled_reports_zero(monkeypatch):
    monkeypatch.setattr(redact, "_REDACT_ENABLED", False)
    text = "sk-" + "a" * 20
    out, count = redact.redact_with_count(text)
    assert out == text
    assert count == 0


def test_redact_terminal_output_with_count_matches_plain_variant():
    output = "SECRET_TOKEN=abcdefghijklmnopqrstuvwxyz"
    plain = redact.redact_terminal_output(output, command="env")
    counted, count = redact.redact_terminal_output_with_count(output, command="env")
    assert counted == plain
    assert count == 1
