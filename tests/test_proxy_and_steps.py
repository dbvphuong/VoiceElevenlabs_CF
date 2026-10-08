"""Kiểm thử tính đúng đắn của bộ lọc Proxy, phân giải API key và xoay Profile."""

import pytest
from network.proxy_pool import parse_proxy_string, RotatingProxyKey, ProxyPool
from captcha.profile_manager import profile_manager

def test_parse_proxy_string_rejects_api_keys():
    """Kiểm tra parse_proxy_string phải từ chối API key (chuỗi không có dấu hai chấm và port)."""
    api_key_1 = "FhGCLyWKIGuhNDajgPvfSA"
    api_key_2 = "iCVojUaUtRbJkTYYVqCIPJ"
    api_key_3 = "dOXJihiqdIpCRXwORBCVAv"

    assert parse_proxy_string(api_key_1) is None
    assert parse_proxy_string(api_key_2) is None
    assert parse_proxy_string(api_key_3) is None
    assert parse_proxy_string("null") is None
    assert parse_proxy_string("") is None

def test_parse_proxy_string_accepts_valid_proxies():
    """Kiểm tra parse_proxy_string phân tích đúng các dạng proxy IP:Port."""
    # 1. Dạng host:port
    res1 = parse_proxy_string("160.250.166.29:10110")
    assert res1 is not None
    assert res1["host"] == "160.250.166.29"
    assert res1["port"] == 10110
    assert res1["playwright"]["server"] == "http://160.250.166.29:10110"

    # 2. Dạng host:port:user:pass
    res2 = parse_proxy_string("1.2.3.4:8080:myuser:mypass")
    assert res2 is not None
    assert res2["host"] == "1.2.3.4"
    assert res2["port"] == 8080
    assert res2["user"] == "myuser"
    assert res2["password"] == "mypass"
    assert res2["playwright"]["server"] == "http://1.2.3.4:8080"
    assert res2["playwright"]["username"] == "myuser"

    # 3. Dạng URI
    res3 = parse_proxy_string("http://user:pass@5.6.7.8:9999")
    assert res3 is not None
    assert res3["host"] == "5.6.7.8"
    assert res3["port"] == 9999

def test_rotating_proxy_key_flag():
    """Kiểm tra cờ is_direct_proxy của RotatingProxyKey."""
    key_api = RotatingProxyKey("FhGCLyWKIGuhNDajgPvfSA")
    assert key_api.is_direct_proxy is False
    assert key_api.current_ip == ""

    key_direct = RotatingProxyKey("160.250.166.29:10110")
    assert key_direct.is_direct_proxy is True
    assert key_direct.current_ip == "160.250.166.29:10110"

def test_profile_manager_rotation():
    """Kiểm tra ProfileManager xoay vòng profile đã nuôi."""
    profiles = profile_manager.get_available_profiles()
    if len(profiles) >= 2:
        p1 = profile_manager.get_next_warmed_profile()
        p2 = profile_manager.get_next_warmed_profile()
        assert p1 != p2
