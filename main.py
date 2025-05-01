# Description: 一个主动对话插件，当用户长时间不回复时主动发送消息
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, register, Star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import AstrBotConfig, logger
import asyncio
import os
import pathlib
import datetime
from .core.daily_greetings import DailyGreetings
from .core.initiative_dialogue_core import InitiativeDialogueCore
from .core.random_daily_activities import RandomDailyActivities
from .core.ai_daily_schedule import AIDailySchedule
from .utils.data_loader import DataLoader
from .utils.festival_detector import FestivalDetector


@register(
    "initiative_dialogue",
    "Jason",
    "主动对话, 当用户长时间不回复时主动发送消息",
    "1.0.0",
)
class InitiativeDialogue(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        # 基础配置
        self.config = config or {}

        # 打印收到的配置，用于调试
        logger.info(f"收到的配置内容: {self.config}")

        # 设置数据存储路径
        self.data_dir = (
            pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "data"
        )
        self.data_file = self.data_dir / "umo_storage.json"

        # 确保数据目录存在
        self.data_dir.mkdir(exist_ok=True)

        # 初始化核心对话模块
        self.dialogue_core = InitiativeDialogueCore(self, self)
        
        # 初始化节日检测器
        self.festival_detector = FestivalDetector.get_instance(self)
        
        # 检查今天是否是节日
        festival_info = self.festival_detector.get_festival_info()
        if festival_info:
            logger.info(f"今天是 {festival_info['name']}！将使用节日相关提示词。")

        # 初始化定时问候模块
        self.daily_greetings = DailyGreetings(self)

        # 初始化随机日常模块
        self.random_daily = RandomDailyActivities(self)
        
        # 初始化AI日程安排模块
        self.ai_schedule = AIDailySchedule(self)

        # 初始化数据加载器并加载数据
        self.data_loader = DataLoader.get_instance(self)
        self.data_loader.load_data_from_storage()

        # 记录配置信息到日志
        logger.info(
            f"已加载配置，不活跃时间阈值: {self.dialogue_core.inactive_time_seconds}秒, "
            f"随机回复窗口: {self.dialogue_core.max_response_delay_seconds}秒, "
            f"时间限制: {'启用' if self.dialogue_core.time_limit_enabled else '禁用'}, "
            f"活动时间: {self.dialogue_core.activity_start_hour}点-{self.dialogue_core.activity_end_hour}点, "
            f"最大连续消息数: {self.dialogue_core.max_consecutive_messages}条"
        )
        
        # 添加白名单信息日志
        logger.info(
            f"白名单功能状态: {'启用' if self.dialogue_core.whitelist_enabled else '禁用'}, "
            f"白名单用户数量: {len(self.dialogue_core.whitelist_users)}"
        )
        
        # 添加日常分享设置日志
        logger.info(
            f"随机日常分享状态: {'启用' if self.random_daily.sharing_enabled else '禁用'}, "
            f"最小间隔: {self.random_daily.min_interval_minutes}分钟, "
            f"最大延迟: {self.random_daily.sharing_max_delay_seconds}秒"
        )
        
        # 添加每日问候设置日志
        logger.info(
            f"每日问候状态: {'启用' if self.daily_greetings.enabled else '禁用'}, "
            f"早安时间: {self.daily_greetings.morning_hour}:{self.daily_greetings.morning_minute:02d}, "
            f"晚安时间: {self.daily_greetings.night_hour}:{self.daily_greetings.night_minute:02d}"
        )
        
        # 添加AI日程安排设置日志
        schedule_settings = self.config.get("schedule_settings", {})
        logger.info(
            f"AI日程安排状态: {'启用' if self.ai_schedule.enabled else '禁用'}, "
            f"生成时间: {self.ai_schedule.schedule_generation_hour}:{self.ai_schedule.schedule_generation_minute:02d}"
        )
        
        # 添加节日检测信息
        festival_config = self.config.get('festival_settings', {})
        festival_enabled = festival_config.get('enabled', True)
        logger.info(
            f"节日检测状态: {'启用' if festival_enabled else '禁用'}, "
            f"优先使用节日提示词: {'是' if festival_config.get('prioritize_festival', True) else '否'}"
        )

        # 启动检查任务
        asyncio.create_task(self.dialogue_core.start_checking_inactive_conversations())

        # 启动定期保存数据任务
        asyncio.create_task(self.data_loader.start_periodic_save())

        # 启动定时问候任务
        asyncio.create_task(self.daily_greetings.start())

        # 启动随机日常任务
        asyncio.create_task(self.random_daily.start())
        
        # 启动AI日程安排任务
        asyncio.create_task(self.ai_schedule.start())

        logger.info("主动对话插件初始化完成，检测任务已启动")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        """处理私聊消息"""
        user_id = str(event.get_sender_id())
        message_str = event.message_str

        # 检查消息是否包含系统提示词标记
        if "[SYS_PROMPT]" in message_str:
            logger.debug(f"检测到系统提示词消息，跳过计数重置: {message_str[:50]}...")
            return
            
        # 委托给核心模块处理
        await self.dialogue_core.handle_user_message(user_id, event)
        
        # 调试日志，查看当前计数
        current_count = self.dialogue_core.consecutive_message_count.get(user_id, 0)
        logger.debug(f"用户 {user_id} 当前计数为 {current_count}")
        
        # 如果用户曾收到过主动消息，这里直接处理重置计数逻辑
        if user_id in self.dialogue_core.users_received_initiative:
            old_count = self.dialogue_core.consecutive_message_count.get(user_id, 0)
            self.dialogue_core.consecutive_message_count[user_id] = 0
            
            # 同时也重置last_initiative_types中的计数
            if user_id in self.dialogue_core.last_initiative_types:
                old_info = self.dialogue_core.last_initiative_types[user_id]
                old_info["count"] = 0
                self.dialogue_core.last_initiative_types[user_id] = old_info
            
            logger.info(f"用户 {user_id} 已回复消息，计数从 {old_count} 重置为 0")
            
            # 移除标记，表示已处理该回复
            self.dialogue_core.users_received_initiative.discard(user_id)
            
            # 立即保存数据以确保计数重置被保存
            if hasattr(self, 'data_loader'):
                try:
                    self.data_loader.save_data_to_storage()
                    logger.info(f"用户 {user_id} 计数重置后数据已保存")
                except Exception as save_error:
                    logger.error(f"保存重置计数数据时出错: {str(save_error)}")

    async def terminate(self):
        """插件被卸载/停用时调用"""
        logger.info("正在停止主动对话插件...")

        # 在终止前打印当前状态
        for user_id, count in self.dialogue_core.consecutive_message_count.items():
            logger.info(f"用户 {user_id} 的最终连续消息计数: {count}")

        # 保存当前数据
        self.data_loader.save_data_to_storage()

        # 停止核心模块的检查任务
        await self.dialogue_core.stop_checking_inactive_conversations()

        # 停止定期保存数据的任务
        await self.data_loader.stop_periodic_save()

        # 停止定时问候任务
        await self.daily_greetings.stop()

        # 停止随机日常任务
        await self.random_daily.stop()
        
        # 停止AI日程安排任务
        await self.ai_schedule.stop()

    @filter.command("initiative_test_message")
    async def test_initiative_message(self, event: AstrMessageEvent):
        """测试主动消息生成"""
        if not event.is_admin():
            yield event.plain_result("只有管理员可以使用此命令")
            return

        user_id = str(event.get_sender_id())
        conversation_id = (
            await self.context.conversation_manager.get_curr_conversation_id(
                event.unified_msg_origin
            )
        )
        unified_msg_origin = event.unified_msg_origin

        prompts = self.dialogue_core.initiative_prompts
        time_period = "测试"

        yield await self.dialogue_core.message_manager.generate_and_send_message(
            user_id=user_id,
            conversation_id=conversation_id,
            unified_msg_origin=unified_msg_origin,
            prompts=prompts,
            message_type="测试",
            time_period=time_period,
        )
    
    @filter.command("generate_schedule")
    async def generate_ai_schedule(self, event: AstrMessageEvent):
        """手动生成AI日程安排（仅管理员）"""
        if not event.is_admin():
            yield event.plain_result("只有管理员可以使用此命令")
            return
            
        yield event.plain_result("正在为所有用户生成AI日程安排...")
        
        # 手动触发日程生成
        await self.ai_schedule.generate_daily_schedules_for_all_users()
        
        yield event.plain_result("AI日程安排生成完成")

    @filter.command("check_festival")
    async def check_current_festival(self, event: AstrMessageEvent):
        """查看当前是否是节日的命令"""
        if not event.is_admin():
            yield event.plain_result("只有管理员可以使用此命令")
            return
            
        festival_info = self.festival_detector.get_festival_info()
        if festival_info:
            result = f"今天是 {festival_info['name']}！\n"
            result += f"描述: {festival_info['description']}\n"
            result += f"节日提示词示例: {festival_info['prompts'][0][:50]}..."
            yield event.plain_result(result)
        else:
            yield event.plain_result("今天不是特殊节日")
            
    @filter.command("check_schedule")
    async def check_ai_schedule(self, event: AstrMessageEvent):
        """查看当前AI日程安排（仅管理员）"""
        if not event.is_admin():
            yield event.plain_result("只有管理员可以使用此命令")
            return
            
        today_str = datetime.datetime.now().date().isoformat()
        
        # 检查是否有今日日程安排
        if today_str in self.ai_schedule.schedules:
            schedule = self.ai_schedule.schedules[today_str]
            result = f"今日AI日程安排：\n"
            result += f"早上(6-8点): {schedule.get('morning', '无安排')}\n"
            result += f"上午(8-11点): {schedule.get('forenoon', '无安排')}\n"
            result += f"午饭(11-13点): {schedule.get('lunch', '无安排')}\n"
            result += f"下午(13-17点): {schedule.get('afternoon', '无安排')}\n"
            result += f"晚饭(17-19点): {schedule.get('dinner', '无安排')}\n"
            result += f"晚上(19-23点): {schedule.get('evening', '无安排')}\n"
            result += f"深夜(23-6点): {schedule.get('night', '无安排')}\n"
            yield event.plain_result(result)
        else:
            yield event.plain_result("当前没有AI日程安排，请使用 generate_schedule 命令生成")
