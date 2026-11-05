from unittest.mock import MagicMock, patch

from app.deepseek_transport import DeepSeekTransport


def _transport() -> DeepSeekTransport:
    return DeepSeekTransport(
        api_key="secret",
        timeout_for=lambda kind, default: 4.0 if kind == "connect" else default,
    )


def test_transport_retries_once_and_closes_failed_connection() -> None:
    failed = MagicMock()
    successful = MagicMock()
    response = MagicMock()
    successful.getresponse.return_value = response
    with patch(
        "app.deepseek_transport.http.client.HTTPSConnection",
        side_effect=[failed, successful],
    ):
        failed.request.side_effect = OSError("offline")
        connection, result = _transport().open({"model": "deepseek-chat"})

    assert connection is successful
    assert result is response
    failed.close.assert_called_once_with()


def test_transport_close_releases_response_and_connection() -> None:
    response = MagicMock()
    connection = MagicMock()
    DeepSeekTransport.close(connection, response)
    response.close.assert_called_once_with()
    connection.close.assert_called_once_with()
