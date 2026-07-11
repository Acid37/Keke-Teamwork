"""会话标题生成服务。"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from backend.config import AppConfig
from backend.llm.client import LLMClient
from backend.session import SessionStore
from backend.types import Session

logger = logging.getLogger(__name__)

Broadcast = Callable[[str, dict], Awaitable[None]]


class TitleService:
    """会话标题生成：确定性 fallback + 异步 LLM 语义标题。"""

    def __init__(
        self,
        config: AppConfig,
        session_store: SessionStore | None,
        llm: LLMClient,
    ):
        self._config = config
        self._session_store = session_store
        self._llm = llm

    # ─── 确定性 fallback ───

    @staticmethod
    def should_generate_title(session: Session) -> bool:
        """只替换占位标题，不替换项目/用户提供的名称。"""
        title = (session.title or "").strip()
        return not title or bool(re.fullmatch(r"Session \d{2}:\d{2}", title))

    @staticmethod
    def generate_title(text: str, work_dir) -> str:
        """从第一条用户消息生成简短的确定性标题。

        这是异步 LLM 标题更新完成前（或 LLM 调用失败时）使用的即时 fallback。
        """
        cleaned = re.sub(r"[`*_#>\[\](){}]", "", text).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^(?:(?:请|帮我|麻烦|能不能|可以)\s*)+", "", cleaned)
        if not cleaned:
            cleaned = work_dir.name or "新会话"
        if len(cleaned) > 24:
            cleaned = cleaned[:24].rstrip() + "…"
        return cleaned

    # ─── 异步 LLM 标题 ───

    async def update_title_with_llm(
        self,
        *,
        session: Session,
        user_text: str,
        broadcast: Broadcast,
    ) -> None:
        """异步通过 LLM 生成语义会话标题。

        使用 main LLM 客户端（无专用标题模型）。任何错误时回退到
        算法标题。广播 ``session.title.updated`` 让前端刷新侧栏。
        """
        try:
            title = await self._call_llm_for_title(user_text)
            title = (title or "").strip().strip('"\'""''')
            if not title:
                return
            if len(title) > 48:
                title = title[:48].rstrip() + "…"
            session.title = title
            if self._session_store:
                self._session_store.save(session)
            await broadcast("session.title.updated", {
                "session_id": session.id,
                "title": title,
            })
        except Exception:
            logger.debug("LLM title generation failed, keeping fallback", exc_info=True)

    async def _call_llm_for_title(self, user_text: str) -> str:
        """调用轻量 LLM 生成简洁的会话标题。

        配置了 ``title_model`` 时使用专用模型（可以是便宜/小模型），
        否则回退到主模型。返回原始标题字符串，调用方负责清理和回退。
        """
        title_model = self._config.effective_title_model
        if self._config.title_model:
            llm = LLMClient(
                provider=self._config.provider,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                model=title_model,
            )
        else:
            llm = self._llm

        system_prompt = (
            "你是一个会话标题生成器。根据用户的第一条消息，生成一个简洁的中文会话标题。"
            "要求：不超过 20 个字，不要引号，不要句号，概括用户意图。"
            "只返回标题文本，不要任何解释或前缀。"
        )
        title = ""
        async for event in llm.chat(
            messages=[{"role": "user", "content": user_text[:2000]}],
            system=system_prompt,
            model=title_model,
            max_tokens=64,
            temperature=0.3,
            stream=True,
        ):
            if event.text_delta:
                title += event.text_delta
            if event.finish:
                break
        return title