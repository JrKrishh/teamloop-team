from teamloop.redact import HIDDEN, redact, redact_obj

CANARIES = [
    "sk-ant-api03-" + "A" * 40,
    "sk-proj-" + "b" * 40,
    "ghp_" + "c" * 36,
    "github_pat_" + "d" * 50,
    "AKIA" + "E" * 16,
    "AIza" + "f" * 35,
    "xoxb-1234567890-abcdefghij",
    "gsk_" + "g" * 50,
    "tvly-" + "h" * 30,
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
    "sk_live_" + "i" * 24,
    "rk_test_" + "j" * 24,
    "whsec_" + "k" * 32,
]


def test_known_shapes_are_hidden():
    for secret in CANARIES:
        out = redact(f"value is {secret} ok")
        assert secret not in out and HIDDEN in out, secret
    assert redact("pk_live_" + "p" * 24) == "pk_live_" + "p" * 24  # Stripe publishable keys are public


def test_env_secrets_hidden_by_value(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-opaque-value-123456")
    assert "nb-opaque-value-123456" not in redact("curl -H key:nb-opaque-value-123456")


def test_assignments_keep_name_hide_value():
    out = redact('DATABASE_PASSWORD="hunter2hunter2" and api_key: abcdef123456')
    assert "hunter2" not in out and "abcdef123456" not in out
    assert "DATABASE_PASSWORD" in out and "api_key" in out


def test_private_key_block():
    block = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3Nza\n-----END OPENSSH PRIVATE KEY-----"
    assert "AAAAB3Nza" not in redact(block)


def test_plain_text_untouched():
    text = "Fixed add() in calc.py; 1 passed, 0 failed. Next: SSE endpoint."
    assert redact(text) == text


def test_nested_objects():
    out = redact_obj({"a": ["x", {"b": CANARIES[2]}], "n": 3})
    assert CANARIES[2] not in str(out) and out["n"] == 3
