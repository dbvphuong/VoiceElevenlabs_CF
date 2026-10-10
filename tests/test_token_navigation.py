"""Lỗi điều hướng ElevenLabs không được hiểu nhầm thành lỗi Captcha."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from captcha.token_farmer import NavigationNetworkError, TokenFarmer, is_navigation_network_error


def make_farmer(goto_side_effect):
    farmer = object.__new__(TokenFarmer)
    farmer._lock = asyncio.Lock()
    farmer.start = AsyncMock()
    farmer._page = MagicMock()
    farmer._page.url = "about:blank"
    farmer._page.goto = AsyncMock(side_effect=goto_side_effect)
    farmer._page.wait_for_load_state = AsyncMock()
    farmer._page.mouse.move = AsyncMock()
    farmer._page.evaluate = AsyncMock(return_value="test-token")
    return farmer


def test_connection_closed_is_network_error():
    assert is_navigation_network_error(Exception("Page.goto: net::ERR_CONNECTION_CLOSED"))
    assert not is_navigation_network_error(Exception("hCaptcha error: challenge-error"))


@pytest.mark.asyncio
async def test_connection_closed_retries_navigation(monkeypatch):
    monkeypatch.setattr("captcha.token_farmer.asyncio.sleep", AsyncMock())
    farmer = make_farmer([Exception("Page.goto: net::ERR_CONNECTION_CLOSED"), None, None])

    assert await farmer.get_token() == "test-token"
    assert farmer._page.goto.await_count == 3  # hai lần mở web, một lần dọn trang
    farmer._page.evaluate.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_connection_closed_reports_network_error(monkeypatch):
    monkeypatch.setattr("captcha.token_farmer.asyncio.sleep", AsyncMock())
    farmer = make_farmer([
        Exception("Page.goto: net::ERR_CONNECTION_CLOSED"),
        Exception("Page.goto: net::ERR_CONNECTION_CLOSED"),
        None,
    ])

    with pytest.raises(NavigationNetworkError, match="Không mở được elevenlabs.io"):
        await farmer.get_token()
    farmer._page.evaluate.assert_not_awaited()


def test_chromewebdata_is_network_error():
    err1 = Exception("Page.goto: Navigation to \"https://elevenlabs.io/\" is interrupted by another navigation to \"chrome-error://chromewebdata/\"")
    err2 = Exception("net::ERR_PROXY_CONNECTION_FAILED")
    assert is_navigation_network_error(err1)
    assert is_navigation_network_error(err2)


@pytest.mark.asyncio
async def test_chromewebdata_raises_navigation_network_error(monkeypatch):
    monkeypatch.setattr("captcha.token_farmer.asyncio.sleep", AsyncMock())
    farmer = make_farmer([
        Exception("Navigation interrupted by another navigation to chrome-error://chromewebdata/"),
        Exception("Navigation interrupted by another navigation to chrome-error://chromewebdata/"),
        None,
    ])

    with pytest.raises(NavigationNetworkError):
        await farmer.get_token()

