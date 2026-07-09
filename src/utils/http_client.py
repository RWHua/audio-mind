"""HTTP 客户端：带超时和重试机制的 requests Session"""

from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_http_session(
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    timeout: int = 30,
    headers: Optional[dict] = None,
) -> requests.Session:
    """创建配置了超时和重试的 requests Session

    Args:
        max_retries: 最大重试次数
        backoff_factor: 退避因子（延迟 = backoff_factor * (2^(retry-1))）
        timeout: 默认超时（秒）
        headers: 自定义请求头

    Returns:
        配置好的 requests.Session 实例
    """
    session = requests.Session()

    # 重试策略：仅对 5xx 和连接错误重试
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # 默认超时
    session.timeout = timeout

    # 默认请求头（模拟浏览器）
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    session.headers.update(default_headers)

    return session
