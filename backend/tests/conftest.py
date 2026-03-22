"""pytest 公共 fixture：避免 UserContext 缓存跨用例指向旧路径。"""

import pytest


@pytest.fixture(autouse=True)
def _clear_user_context_cache():
    from app.core import user_context as uc

    uc._user_ctx_cache.clear()
    yield
    uc._user_ctx_cache.clear()
