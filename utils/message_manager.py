# 消息管理器 - 处理消息生成和发送逻辑

import json
import random
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from astrbot.api.all import (
    AstrBotMessage,
    MessageType,
    MessageMember,
    MessageChain,
    MessageEventResult,
)
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain

logger = logging.getLogger("message_manager")


class MessageManager:
    """消息管理器，负责生成和发送各类消息"""

    def __init__(self, parent):
        """初始化消息管理器

        Args:
            parent: 父插件实例，用于访问上下文
        """
        self.parent = parent
        self.context = parent.context

    async def generate_and_send_message(
        self,
        user_id: str,
        conversation_id: str,
        unified_msg_origin: str,
        prompts: List[str],
        message_type: str = "一般",
        time_period: Optional[str] = None,
        extra_context: Optional[str] = None,
    ):
        """生成并发送消息

        Args:
            user_id: 用户ID
            conversation_id: 会话ID
            unified_msg_origin: 统一消息来源
            prompts: 可用的提示词列表
            message_type: 消息类型描述（用于日志）
            time_period: 时间段描述（如"早上"、"下午"等）
            extra_context: 额外的上下文信息

        """
        try:
            _, _, session_id = self.parse_unified_msg_origin(unified_msg_origin)
            # 获取对话对象
            conversation = await self.context.conversation_manager.get_conversation(
                unified_msg_origin, conversation_id
            )

            if not conversation:
                logger.error(
                    f"无法获取用户 {user_id} 的对话，会话ID: {conversation_id} 可能不存在"
                )
                return False

            # 获取对话历史和系统提示
            system_prompt = "你是一个可爱的AI助手，喜欢和用户互动。"

            # 获取当前对话的人格设置
            if conversation:
                persona_id = conversation.persona_id

                # 获取对话使用的人格设置
                system_prompt = self._get_system_prompt(persona_id, system_prompt)

            # 检查今天是否是特殊节日
            festival_detector = self.parent.festival_detector if hasattr(self.parent, 'festival_detector') else None
            festival_prompts = None
            festival_name = None
            
            if festival_detector:
                festival_prompts = festival_detector.get_festival_prompts()
                festival_name = festival_detector.get_festival_name()
            
            # 如果今天是节日且不是特定消息类型，优先使用节日相关提示词
            if festival_prompts and message_type not in ["主动消息", "早安", "晚安"]:
                prompts = festival_prompts
                logger.info(f"今天是{festival_name}，使用节日相关提示词")

            # 随机选择一个提示词
            prompt = random.choice(prompts)

            # 调整提示词
            adjusted_prompt = prompt
            if festival_name and message_type not in ["主动消息"]:
                if time_period:
                    adjusted_prompt = f"{prompt}，今天是{festival_name}，现在是{time_period}，请保持与你的人格设定一致的风格，确保回复符合你的人设特点。"
                else:
                    adjusted_prompt = f"{prompt}，今天是{festival_name}，请保持与你的人格设定一致的风格，确保回复符合你的人设特点。"
            elif time_period:
                adjusted_prompt = f"{prompt}，现在是{time_period}，请保持与你的人格设定一致的风格，确保回复符合你的人设特点。"
            else:
                adjusted_prompt = f"{prompt}，请保持与你的人格设定一致的风格，确保回复符合你的人设特点。"

            if extra_context:
                adjusted_prompt = f"{adjusted_prompt} {extra_context}"

            # 获取LLM工具管理器
            func_tools_mgr = self.context.get_llm_tool_manager()

            # 调用LLM获取回复
            logger.info(f"正在为用户 {user_id} 生成{message_type}消息内容...")
            logger.debug(f"使用的提示词: {adjusted_prompt}")

            platform = self.context.get_platform("aiocqhttp")
            fake_event = self.create_fake_event(
                message_str=adjusted_prompt,
                bot=platform.bot,
                umo=unified_msg_origin,
                sender_id=user_id,
                session_id=session_id,
            )
            platform.commit_event(fake_event)
            self.parent.dialogue_core.users_received_initiative.add(user_id)
            return fake_event.request_llm(
                prompt=adjusted_prompt,
                func_tool_manager=func_tools_mgr,
                image_urls=[],
                system_prompt=system_prompt,
                conversation=conversation,
            )

        except Exception as e:
            import traceback

            error_traceback = traceback.format_exc()
            logger.error(
                f"发送{message_type}消息时发生错误: {str(e)}\n{error_traceback}"
            )
            return

    def parse_unified_msg_origin(self, unified_msg_origin: str):
        """解析统一消息来源

        格式: platform_name:message_type:session_id
        """
        try:
            parts = unified_msg_origin.split(":")
            if len(parts) != 3:
                raise ValueError("统一消息来源格式错误")

            platform_name = parts[0]
            message_type = parts[1]
            session_id = parts[2]

            return platform_name, message_type, session_id
        except Exception as e:
            logger.error(f"解析统一消息来源时发生错误: {str(e)}")
            return None, None, None

    def create_fake_event(
        self,
        message_str: str,
        bot,
        umo: str,
        session_id: str,
        sender_id: str = "123456",
    ):
        from astrbot.core.platform.platform_metadata import PlatformMetadata
        from .aiocqhttp_message_event import AiocqhttpMessageEvent

        abm = AstrBotMessage()
        abm.message_str = message_str
        abm.message = [Plain(message_str)]
        abm.self_id = sender_id
        abm.sender = MessageMember(user_id=sender_id)

        if "group" in umo.lower():
            # 群消息
            group_id = umo.split("_")[-1] if "_" in umo else sender_id
            abm.raw_message = {
                "message_type": "group",
                "group_id": int(group_id),
                "user_id": int(sender_id),
                "message": message_str,
            }
        else:
            # 私聊消息
            abm.raw_message = {
                "message_type": "private",
                "user_id": int(sender_id),
                "message": message_str,
            }

        abm.session_id = session_id
        abm.type = MessageType.FRIEND_MESSAGE

        meta = PlatformMetadata("aiocqhttp", "fake_adapter")
        event = AiocqhttpMessageEvent(
            message_str=message_str,
            message_obj=abm,
            platform_meta=meta,
            session_id=session_id,
            bot=bot,
        )
        event.is_wake = True
        event.call_llm = False

        return event

    def _get_system_prompt(self, persona_id: Optional[str], default_prompt: str) -> str:
        """获取系统提示词

        Args:
            persona_id: 人格ID
            default_prompt: 默认提示词

        Returns:
            str: 系统提示词
        """
        try:
            if persona_id is None:
                # 使用默认人格
                default_persona = self.context.provider_manager.selected_default_persona
                if default_persona:
                    return default_persona.get("prompt", default_prompt)
            elif persona_id != "[%None]":
                # 使用指定人格
                personas = self.context.provider_manager.personas
                for persona in personas:
                    if persona.get("id") == persona_id:
                        return persona.get("prompt", default_prompt)
        except Exception as e:
            logger.error(f"获取人格信息时出错: {str(e)}")

        return default_prompt
