# Description: 主动对话核心模块，检测用户不活跃状态并发送主动消息

import asyncio
import datetime
import logging
import random
from typing import Dict, Any, Set, List, Optional

from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest

from ..utils.message_manager import MessageManager
from ..utils.user_manager import UserManager
from ..utils.task_manager import TaskManager
from ..utils.config_manager import ConfigManager

# 配置日志
logger = logging.getLogger("initiative_dialogue_core")


class InitiativeDialogueCore:
    """主动对话核心类，管理用户状态并在适当时候发送主动消息"""

    def __init__(self, parent, star):
        """初始化主动对话核心

        Args:
            parent: 父插件实例，用于访问上下文和配置
        """
        self.parent = parent
        self.star = star
        self.context = star.context

        # 加载配置
        self.config_manager = ConfigManager(parent.config)
        
        # 从time_settings获取核心配置参数
        time_settings = self.config_manager.get_module_config("time_settings")
        self.inactive_time_seconds = time_settings.get(
            "inactive_time_seconds", 7200
        )  # 默认2小时
        self.max_response_delay_seconds = time_settings.get(
            "max_response_delay_seconds", 3600
        )  # 默认1小时
        self.time_limit_enabled = time_settings.get("time_limit_enabled", True)
        self.probability_enabled = time_settings.get("probability_enabled", True)  # 是否启用概率发送
        self.activity_start_hour = time_settings.get("activity_start_hour", 8)
        self.activity_end_hour = time_settings.get("activity_end_hour", 23)
        self.max_consecutive_messages = time_settings.get("max_consecutive_messages", 3)

        # 从whitelist获取白名单配置
        whitelist_config = self.config_manager.get_module_config("whitelist")
        self.whitelist_enabled = whitelist_config.get("enabled", False)
        self.whitelist_users = set(whitelist_config.get("user_ids", []))

        # 提示词配置 - 根据消息发送次数调整情感
        self.initiative_prompts = [
            # 首次发送 - 表达思念和友好
            "请生成一条简短的消息，表达你因用户长时间未联系而想念对方，想和用户聊天的心情，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            "请生成一条简短的消息，表达你注意到用户很久没有消息，很想和用户聊天的感受，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            "请生成一条简短的消息，表示你发现用户很久没有联系你，表达你想念用户并希望聊天的心情，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            "请生成一条简短的消息，表达因为用户很长时间没给你发消息，你有点想念对方了，想找用户聊聊天，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            
            # 中间阶段 - 表达轻微失落但仍然友好
            "请生成一条简短的消息，表达你已经主动联系用户多次但没收到回复，有些失落但仍希望聊天的心情，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            "请生成一条简短的消息，表示你发现用户似乎很忙，对没有回复感到有点失落，但仍然友好地询问用户的近况，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            
            # 后期阶段 - 表达失望但理解
            "请生成一条简短的消息，表达你多次联系用户没有得到回应的失望情绪，但表示理解用户可能很忙，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            "请生成一条简短的消息，表达你因多次没有收到用户回复而感到有些失望，但仍然尊重用户的选择，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            
            # 最终阶段 - 表示不再打扰
            "请生成一条简短的消息，表示你理解用户可能无暇回复，决定不再频繁打扰，但仍然会在这里等待用户的消息，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。",
            "请生成一条简短的消息，表达你不想过多打扰用户的生活，以后会减少主动联系，但随时欢迎用户的消息，保持符合你的人设特点。请确保回复贴合当前的对话上下文情景。"
        ]

        # 记录每个用户收到的连续主动消息次数
        self.consecutive_message_count = {}

        # 用户数据
        self.user_records = {}
        self.last_initiative_messages = {}
        self.users_received_initiative = set()
        
        # 用户最后收到的主动消息类型记录 - 新增
        self.last_initiative_types = {}

        # 检查任务引用
        self.inactive_check_task = None

        # 初始化共享组件
        self.message_manager = MessageManager(parent)
        self.user_manager = UserManager(parent)
        self.task_manager = TaskManager(parent)

        logger.info(
            f"主动对话核心初始化完成，不活跃时间阈值：{self.inactive_time_seconds}秒"
        )

    def get_data(self) -> Dict[str, Any]:
        """获取核心数据用于持久化

        Returns:
            Dict: 包含用户记录和主动消息记录的字典
        """
        return {
            "user_records": self.user_records,
            "last_initiative_messages": self.last_initiative_messages,
            "users_received_initiative": self.users_received_initiative,
            "consecutive_message_count": self.consecutive_message_count,  # 添加连续消息计数
            "last_initiative_types": self.last_initiative_types,  # 添加最后消息类型
        }

    def set_data(
        self,
        user_records: Dict[str, Any],
        last_initiative_messages: Dict[str, Any],
        users_received_initiative: Set[str],
        consecutive_message_count: Dict[str, int] = None,  # 添加新参数
        last_initiative_types: Dict[str, str] = None,  # 添加新参数
    ) -> None:
        """设置核心数据，从持久化存储恢复

        Args:
            user_records: 用户记录字典
            last_initiative_messages: 最后主动消息记录字典
            users_received_initiative: 已接收主动消息的用户ID集合
            consecutive_message_count: 连续消息计数字典 (可选)
            last_initiative_types: 最后消息类型字典 (可选)
        """
        self.user_records = user_records
        self.last_initiative_messages = last_initiative_messages
        self.users_received_initiative = users_received_initiative
        
        # 如果提供了计数数据，则加载它
        if consecutive_message_count is not None:
            self.consecutive_message_count = consecutive_message_count
            
        # 如果提供了最后消息类型数据，则加载它
        if last_initiative_types is not None:
            self.last_initiative_types = last_initiative_types

        logger.info(
            f"已加载用户数据，共有 {len(user_records)} 条用户记录，"
            f"{len(last_initiative_messages)} 条主动消息记录，"
            f"{len(users_received_initiative)} 个用户已接收主动消息，"
            f"{len(self.consecutive_message_count)} 个用户的连续消息计数"
        )

    async def start_checking_inactive_conversations(self) -> None:
        """启动检查不活跃对话的任务"""
        if self.inactive_check_task is not None:
            logger.warning("检查不活跃对话任务已在运行中")
            return

        logger.info("启动检查不活跃对话任务")
        self.inactive_check_task = asyncio.create_task(
            self._check_inactive_conversations_loop()
        )

    async def stop_checking_inactive_conversations(self) -> None:
        """停止检查不活跃对话的任务"""
        if self.inactive_check_task is not None and not self.inactive_check_task.done():
            self.inactive_check_task.cancel()
            try:
                await self.inactive_check_task
            except asyncio.CancelledError:
                pass

            self.inactive_check_task = None
            logger.info("不活跃对话检查任务已停止")

    async def _check_inactive_conversations_loop(self) -> None:
        """定期检查不活跃对话的循环"""
        try:
            while True:
                # 每30秒检查一次
                await asyncio.sleep(30)

                # 如果启用了时间限制，检查当前是否在活动时间范围内
                if self.time_limit_enabled:
                    current_hour = datetime.datetime.now().hour
                    if not (
                        self.activity_start_hour
                        <= current_hour
                        < self.activity_end_hour
                    ):
                        # 不在活动时间范围内，跳过本次检查
                        continue

                # 获取当前时间
                now = datetime.datetime.now()

                # 遍历所有用户记录，检查不活跃状态
                for user_id, record in list(self.user_records.items()):
                    # 如果启用了白名单且用户不在白名单中，跳过
                    if self.whitelist_enabled and user_id not in self.whitelist_users:
                        continue
                        
                    # 检查用户连续消息计数，如果已达到最大值，跳过
                    current_count = self.consecutive_message_count.get(user_id, 0)
                    if current_count >= self.max_consecutive_messages:
                        logger.debug(f"用户 {user_id} 已达到最大连续消息数 {self.max_consecutive_messages}，跳过")
                        continue

                    # 检查用户最后活跃时间
                    last_active = record.get("timestamp")
                    if not last_active:
                        continue

                    # 计算不活跃时间（秒）
                    inactive_seconds = (now - last_active).total_seconds()

                    # 如果超过阈值，安排发送主动消息
                    if inactive_seconds >= self.inactive_time_seconds:
                        # 为用户创建发送主动消息的任务
                        task_id = f"initiative_{user_id}_{int(now.timestamp())}"
                        
                        logger.info(f"用户 {user_id} 当前计数为 {current_count}，准备发送主动消息")
                        
                        # 计算随机延迟时间，增加自然感
                        await self.task_manager.schedule_task(
                            task_id=task_id,
                            coroutine_func=self._send_initiative_message,
                            random_delay=True,
                            min_delay=0,
                            max_delay=int(self.max_response_delay_seconds / 60),
                            user_id=user_id,
                            conversation_id=record["conversation_id"],
                            unified_msg_origin=record["unified_msg_origin"],
                        )
                        
                        # 从记录中移除该用户，防止重复发送
                        self.user_records.pop(user_id, None)

        except asyncio.CancelledError:
            logger.info("不活跃对话检查循环已取消")
            raise
        except Exception as e:
            logger.error(f"检查不活跃对话时发生错误: {str(e)}")

    async def _send_initiative_message(
        self, user_id: str, conversation_id: str, unified_msg_origin: str
    ) -> None:
        """发送主动消息给指定用户

        Args:
            user_id: 用户ID
            conversation_id: 会话ID
            unified_msg_origin: 统一消息来源
        """
        # 再次检查用户是否在白名单中（如果启用了白名单）
        if self.whitelist_enabled and user_id not in self.whitelist_users:
            logger.info(f"用户 {user_id} 不在白名单中，取消发送主动消息")
            return
        
        # 获取当前计数并增加1 - 修改这部分逻辑，确保计数更新
        # 检查last_initiative_types中是否有该用户的记录，优先使用这个记录的count值
        current_count = 0
        if user_id in self.last_initiative_types:
            last_info = self.last_initiative_types[user_id]
            current_count = last_info.get("count", 0)
            logger.info(f"从last_initiative_types获取到用户 {user_id} 的计数: {current_count}")
        else:
            # 如果没有记录，才从consecutive_message_count获取
            current_count = self.consecutive_message_count.get(user_id, 0)
            logger.info(f"从consecutive_message_count获取到用户 {user_id} 的计数: {current_count}")
        
        next_count = current_count + 1
        
        # 检测是否达到最大消息数
        if next_count > self.max_consecutive_messages:
            logger.info(f"用户 {user_id} 的计数 {next_count} 超过最大值 {self.max_consecutive_messages}，取消发送")
            return
        
        logger.info(f"准备向用户 {user_id} 发送第 {next_count} 次主动消息")
        
        # 获取当前时间段，用于调整消息内容
        current_hour = datetime.datetime.now().hour
        if 6 <= current_hour < 8:
            time_period = "早上"
        elif 8 <= current_hour < 11:
            time_period = "上午"
        elif 11 <= current_hour < 13:
            time_period = "午饭"
        elif 13 <= current_hour < 17:
            time_period = "下午"
        elif 17 <= current_hour < 19:
            time_period = "晚饭"
        elif 19 <= current_hour < 23:
            time_period = "晚上"
        else:
            time_period = "深夜"
        
        # 确定使用的提示词
        prompt_index = 0
        
        if next_count == 1:
            # 首次发送 - 随机选择前4个提示词之一
            prompt_index = random.randint(0, 3)
        elif next_count == 2:
            # 第二次发送 - 使用中间阶段提示词
            prompt_index = random.randint(4, 5)
        elif next_count == self.max_consecutive_messages:
            # 最后一次发送 - 使用最终阶段提示词
            prompt_index = random.randint(8, 9)
        else:
            # 其他情况 - 使用后期阶段提示词
            prompt_index = random.randint(6, 7)
        
        # 确保索引在有效范围内
        prompt_index = min(prompt_index, len(self.initiative_prompts) - 1)
        
        # 获取最终提示词
        selected_prompt = self.initiative_prompts[prompt_index]
        
        # 修改上下文提示词构建方式，使其更加明确
        extra_context = f"现在是{time_period}，这是第{next_count}次主动联系用户(请不要在回复中直接提及这个数字或'第几次'字样)，"
        extra_context += f"请根据目前的时间段({time_period})调整内容，"
        
        # 检查今天是否是特殊节日
        festival_detector = self.parent.festival_detector if hasattr(self.parent, 'festival_detector') else None
        festival_name = None
        
        if festival_detector:
            festival_name = festival_detector.get_festival_name()
            
        # 如果是节日，在上下文中添加节日信息
        if festival_name:
            extra_context += f"今天是{festival_name}，可以在对话中自然地融入节日元素。"
            
        if next_count >= self.max_consecutive_messages:
            extra_context += "这将是最后一次主动联系，表达你将不再打扰的意思。"
            
        # 记录本次主动消息的类型信息
        message_type_info = {
            "count": next_count, 
            "time_period": time_period,
            "timestamp": datetime.datetime.now()
        }
        
        try:
            # 使用消息管理器发送主动消息
            result = await self.message_manager.generate_and_send_message(
                user_id=user_id,
                conversation_id=conversation_id,
                unified_msg_origin=unified_msg_origin,
                prompts=[selected_prompt],  # 只使用选定的提示词
                message_type="主动消息",
                time_period=time_period,
                extra_context=extra_context
            )

            # 消息发送后，更新计数和信息 - 确保在这里更新两个地方的计数
            self.consecutive_message_count[user_id] = next_count
            
            # 记录本次主动消息的类型信息
            message_type_info = {
                "count": next_count, 
                "time_period": time_period,
                "timestamp": datetime.datetime.now()
            }
            self.last_initiative_types[user_id] = message_type_info
            
            # 打印确认日志，确保计数已更新
            logger.info(f"用户 {user_id} 的计数已更新：consecutive_message_count={next_count}, "
                       f"last_initiative_types.count={message_type_info['count']}")
            
            # 更新主动消息记录
            now = datetime.datetime.now()
            self.last_initiative_messages[user_id] = {
                "timestamp": now,
                "conversation_id": conversation_id,
                "unified_msg_origin": unified_msg_origin,
            }

            # 标记用户已接收主动消息
            self.users_received_initiative.add(user_id)

            logger.info(f"已向用户 {user_id} 发送第 {next_count} 次主动消息")
            
            # 如果未达到最大连续发送次数，将用户重新加入记录以继续监控
            if next_count < self.max_consecutive_messages:
                # 将用户重新添加到记录中，以重新开始计时
                self.user_records[user_id] = {
                    "timestamp": now,
                    "conversation_id": conversation_id,
                    "unified_msg_origin": unified_msg_origin,
                }
                logger.info(f"用户 {user_id} 未回复，已重新加入监控记录，当前连续发送次数: {next_count}")
            else:
                logger.info(f"用户 {user_id} 已达到最大连续发送次数({self.max_consecutive_messages})，停止连续发送")
            
            # 立即保存数据以确保计数不丢失
            if hasattr(self.parent, 'data_loader'):
                try:
                    self.parent.data_loader.save_data_to_storage()
                    logger.info(f"用户 {user_id} 的消息计数更新后数据已保存: {next_count}")
                except Exception as save_error:
                    logger.error(f"保存计数数据时出错: {str(save_error)}")
                
        except Exception as e:
            logger.error(f"发送主动消息给用户 {user_id} 时发生错误: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    async def handle_user_message(self, user_id: str, event: AstrMessageEvent) -> None:
        """处理用户消息，更新活跃状态

        Args:
            user_id: 用户ID
            event: 消息事件
        """
        # 获取会话信息
        conversation_id = (
            await self.context.conversation_manager.get_curr_conversation_id(
                event.unified_msg_origin
            )
        )
        unified_msg_origin = event.unified_msg_origin

        # 更新用户记录
        now = datetime.datetime.now()
        self.user_records[user_id] = {
            "timestamp": now,
            "conversation_id": conversation_id,
            "unified_msg_origin": unified_msg_origin,
        }

        logger.debug(f"已更新用户 {user_id} 的活跃状态，最后活跃时间：{now}")
