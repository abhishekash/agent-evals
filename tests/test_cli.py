from types import SimpleNamespace

from agent_evals.cli import _live_provider_factory, _selected_model, build_parser


def test_opencode_go_default_model(monkeypatch):
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    args = build_parser().parse_args(["run", "--provider", "opencode"])
    assert _selected_model(args) == "mimo-v2.6-pro"


def test_opencode_cli_model_from_environment_is_normalized(monkeypatch):
    monkeypatch.setenv("OPENCODE_MODEL", "opencode-go/mimo-v2.6-pro")
    args = build_parser().parse_args(["run", "--provider", "opencode"])
    assert _selected_model(args) == "mimo-v2.6-pro"


def test_explicit_go_model_takes_precedence_and_is_normalized(monkeypatch):
    monkeypatch.setenv("OPENCODE_MODEL", "big-pickle")
    args = build_parser().parse_args(
        ["run", "--provider", "opencode", "--model", "opencode-go/mimo-v2.6-pro"]
    )
    assert _selected_model(args) == "mimo-v2.6-pro"


def test_go_factory_uses_go_route_and_fresh_session_per_attempt(monkeypatch):
    from agent_harness.providers import openai as adapter

    clients = []
    requests = []

    def fake_openai(**kwargs):
        clients.append(kwargs)

        def create(**request):
            requests.append(request)
            return {"choices": [{"message": {"content": "done"}}]}

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(adapter, "OpenAI", fake_openai)
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    args = build_parser().parse_args(["run", "--provider", "opencode"])
    factory = _live_provider_factory(args)
    first, second = factory(), factory()
    first.complete([], [])
    first.summarize([])
    second.complete([], [])

    assert len(clients) == 2
    assert all(client["base_url"] == "https://opencode.ai/zen/go/v1" for client in clients)
    assert all(request["model"] == "mimo-v2.6-pro" for request in requests)
    sessions = [request["extra_headers"]["x-opencode-session"] for request in requests]
    assert sessions[0] == sessions[1]
    assert sessions[0] != sessions[2]
    assert all(request["extra_headers"]["User-Agent"].startswith("agent-harness/") for request in requests)
