"""Import-and-construct smoke tests for each provider's real SDK client —
NOT an API call. Constructing a client object (`Mistral(api_key=...)`,
`anthropic.Anthropic(api_key=...)`, `DocumentIntelligenceClient(...)`) is
a pure local operation for all three SDKs: it builds a Python object and
does not open a connection or send anything over the network. These
tests use obviously-fake, hardcoded placeholder strings — never a real
credential, never something read from the environment.

Why this exists: the first real Phase 5 run surfaced two genuine bugs
that had nothing to do with provider behavior — `from mistralai import
Mistral` failed because the installed SDK's public class actually lives
at `mistralai.client.Mistral`, and the JSON-schema field name had
drifted to `schema_definition`. Both were package-API-surface drift that
a real network call was not required to catch — only actually importing
and constructing against the installed package was. These tests close
that gap for the next time an SDK version changes shape, without ever
needing network access or credentials.

Skipped entirely if the `[spike]` extra isn't installed — these are not
part of the default `.[dev]` test run.
"""

import pytest

anthropic = pytest.importorskip("anthropic")
azure_core_credentials = pytest.importorskip("azure.core.credentials")
azure_di = pytest.importorskip("azure.ai.documentintelligence")
mistralai_client = pytest.importorskip("mistralai.client")

_FAKE_KEY = "not-a-real-key-placeholder-for-construction-only"


def test_mistral_client_class_is_importable_and_constructible():
    # This is exactly the import path that broke on mistralai==2.9.4
    # when the code assumed `from mistralai import Mistral`.
    client = mistralai_client.Mistral(api_key=_FAKE_KEY)
    assert client is not None
    assert hasattr(client, "files")
    assert hasattr(client, "ocr")


def test_claude_client_class_is_importable_and_constructible():
    client = anthropic.Anthropic(api_key=_FAKE_KEY)
    assert client is not None
    assert hasattr(client, "messages")


def test_claude_messages_create_accepts_the_parameters_the_wrapper_uses():
    import inspect

    client = anthropic.Anthropic(api_key=_FAKE_KEY)
    params = inspect.signature(client.messages.create).parameters
    for name in ("model", "max_tokens", "tools", "tool_choice", "messages"):
        assert name in params, f"anthropic SDK no longer accepts a '{name}' parameter"


def test_claude_response_types_have_the_fields_the_wrapper_reads():
    # Confirmed once against anthropic==1.0.0 after that version's
    # response models changed shape from what the >=0.40 pin assumed —
    # Message.content, ToolUseBlock.{type,input}, and
    # Usage.{input_tokens,output_tokens} all still match.
    from anthropic.types import Message, ToolUseBlock, Usage

    assert "content" in Message.model_fields
    assert {"type", "input"} <= set(ToolUseBlock.model_fields)
    assert {"input_tokens", "output_tokens"} <= set(Usage.model_fields)


def test_azure_client_class_is_importable_and_constructible():
    # Azure is excluded from the current Phase 5 comparison (Mistral vs.
    # Claude only, per project owner decision — see
    # docs/adr/0006-extraction-provider.md) but the code is kept ready
    # for a future re-inclusion, so it's worth the same protection.
    credential = azure_core_credentials.AzureKeyCredential(_FAKE_KEY)
    client = azure_di.DocumentIntelligenceClient(
        endpoint="https://example.invalid", credential=credential
    )
    assert client is not None


def test_mistral_provider_module_uses_the_correct_import_path():
    # A static guard against reintroducing the exact bug found in the
    # real run: `from mistralai import Mistral` (wrong in 2.9.4) instead
    # of `from mistralai.client import Mistral` (correct).
    import inspect

    from spike.providers import mistral_provider

    source = inspect.getsource(mistral_provider.extract)
    assert "from mistralai.client import Mistral" in source
    assert "from mistralai import Mistral" not in source


def test_mistral_provider_uses_schema_definition_not_schema():
    # A static guard against the second real bug found: the JSON-schema
    # field is `schema_definition` on the installed SDK, not `schema`.
    import inspect

    from spike.providers import mistral_provider

    source = inspect.getsource(mistral_provider.extract)
    assert "schema_definition" in source
