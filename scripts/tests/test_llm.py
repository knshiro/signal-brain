import pytest
from signal_brain.llm import LLMClient, LLMResponse


def test_client_uses_configured_model(mocker):
    fake = mocker.MagicMock()
    fake.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text='{"ok": true}')],
        usage=mocker.MagicMock(input_tokens=10, output_tokens=5),
    )
    client = LLMClient(api_client=fake, default_model="m1")
    resp = client.complete("system", "user")
    assert resp.text == '{"ok": true}'
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5
    fake.messages.create.assert_called_once()
    kwargs = fake.messages.create.call_args.kwargs
    assert kwargs["model"] == "m1"
    assert kwargs["system"] == "system"
    assert kwargs["messages"][0]["role"] == "user"


def test_client_parses_json_response(mocker):
    fake = mocker.MagicMock()
    fake.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text='```json\n{"a": 1}\n```')],
        usage=mocker.MagicMock(input_tokens=1, output_tokens=1),
    )
    client = LLMClient(api_client=fake, default_model="m1")
    assert client.complete_json("s", "u") == {"a": 1}
