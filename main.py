# Description: 一个主动对话插件，当用户长时间不回复时主动发送消息
from astrbot.api.all import *
from astrbot.api.event import filter  # 明确导入对象
import datetime
import random
import asyncio
import json
import time

@register("initiative_dialogue", "Jason","主动对话, 当用户长时间不回复时主动发送消息", "1.0.0")
class InitiativeDialogue(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        # 存储用户的会话记录 {user_id: {'conversation_id': conversation_id, 'timestamp': timestamp}}
        self.user_records = {}
        
        # 加载配置
        self.config = config or {}
        self.time_settings = self.config.get('time_settings', {})
        
        # 设置时间参数（使用配置文件的值或默认值）
        self.inactive_time_seconds = self.time_settings.get('inactive_time_seconds', 7200)  # 默认2小时
        self.max_response_delay_seconds = self.time_settings.get('max_response_delay_seconds', 3600)  # 默认1小时
        self.activity_start_hour = self.time_settings.get('activity_start_hour', 8)  # 默认8点
        self.activity_end_hour = self.time_settings.get('activity_end_hour', 23)  # 默认23点
        
        # 预设的prompt列表（从配置文件中获取）
        self.prompts = self.config.get('prompts', [
            "请以调皮可爱的语气，用简短的一句话表达我很想念用户，希望他/她能来陪我聊天",
            "请以略带不满的语气，用简短的一句话表达用户很久没有理你，你有点生气了",
            "请以撒娇的语气，用简短的一句话问候用户，表示很想念他/她",
            "请以可爱的语气，用简短的一句话表达你很无聊，希望用户能来陪你聊天",
            "请以委屈的语气，用简短的一句话问用户是不是把你忘了",
            "请以俏皮的语气，用简短的一句话表达你在等用户来找你聊天",
            "请以温柔的语气，用简短的一句话表达你想知道用户最近过得怎么样",
            "请以可爱的语气，用简短的一句话提醒用户你还在这里等他/她",
            "请以友好的语气，用简短的一句话问用户最近是不是很忙",
            "请以亲切的语气，用简短的一句话表达你希望用户能告诉你他/她的近况"
        ])
        
        # 记录配置信息到日志
        logger.info(f"已加载配置，不活跃时间阈值: {self.inactive_time_seconds}秒, "
                    f"随机回复窗口: {self.max_response_delay_seconds}秒, "
                    f"活动时间: {self.activity_start_hour}点-{self.activity_end_hour}点")
        
        # 启动检查任务
        self.message_check_task = asyncio.create_task(self._check_inactive_conversations())
        # 记录任务以防止被垃圾回收
        self.tasks = {"check_inactive": self.message_check_task}
    
    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        """处理私聊消息"""
        user_id = str(event.get_sender_id())
        message_str = event.message_str
        current_time = datetime.datetime.now()
        
        # 检查是否有为该用户安排的待发送消息任务
        if hasattr(self, '_message_tasks'):
            # 查找该用户的所有任务并取消
            tasks_to_cancel = []
            for task_id, task in list(self._message_tasks.items()):
                if task_id.startswith(f"send_message_{user_id}_") and not task.done():
                    tasks_to_cancel.append((task_id, task))
            
            # 取消找到的任务
            for task_id, task in tasks_to_cancel:
                task.cancel()
                self._message_tasks.pop(task_id, None)
                logger.info(f"由于用户 {user_id} 发送新消息，已取消待发送的主动消息任务 {task_id}")
        
        # 获取当前的会话ID
        curr_cid = await self.context.conversation_manager.get_curr_conversation_id(event.unified_msg_origin)
        
        # 如果没有会话ID，创建一个新的
        if not curr_cid:
            curr_cid = await self.context.conversation_manager.new_conversation(event.unified_msg_origin)
        
        # 更新或创建用户记录
        self.user_records[user_id] = {
            'conversation_id': curr_cid,
            'timestamp': current_time,
            'unified_msg_origin': event.unified_msg_origin
        }
        
        logger.info(f"用户 {user_id} 发送了私聊消息，会话ID: {curr_cid}")
        
        # 可以在这里添加对私聊消息的其他处理逻辑
    
    async def _check_inactive_conversations(self):
        """定期检查不活跃的会话，并发送主动消息"""
        try:
            while True:
                # 检查当前时间是否在允许的活动时间段内
                current_hour = datetime.datetime.now().hour
                if self.activity_start_hour <= current_hour < self.activity_end_hour:
                    current_time = datetime.datetime.now()
                    users_to_message = []
                    
                    # 检查每个用户记录
                    for user_id, record in list(self.user_records.items()):
                        # 计算自上次消息以来的时间（秒）
                        seconds_elapsed = (current_time - record['timestamp']).total_seconds()
                        
                        # 只处理那些刚好超过不活跃阈值但未超过阈值+窗口时间的记录
                        if self.inactive_time_seconds <= seconds_elapsed < (self.inactive_time_seconds + self.max_response_delay_seconds):
                            users_to_message.append((user_id, record))
                    
                    # 为每个需要发送消息的用户安排一个随机时间发送
                    for user_id, record in users_to_message:
                        # 计算还剩多少时间到窗口结束（最多为最大延迟时间）
                        seconds_elapsed = (current_time - record['timestamp']).total_seconds()
                        max_delay = min(self.inactive_time_seconds + self.max_response_delay_seconds - seconds_elapsed, 
                                       self.max_response_delay_seconds)
                        
                        # 在剩余时间内随机选择一个时间点
                        delay = random.randint(1, int(max_delay))
                        
                        # 创建并存储任务，以防垃圾回收
                        task_id = f"send_message_{user_id}_{int(time.time())}"
                        task = asyncio.create_task(self._send_initiative_message(
                            user_id=user_id,
                            conversation_id=record['conversation_id'],
                            unified_msg_origin=record['unified_msg_origin'],
                            delay_seconds=delay
                        ))
                        
                        # 存储任务引用
                        if not hasattr(self, '_message_tasks'):
                            self._message_tasks = {}
                        self._message_tasks[task_id] = task
                        
                        # 设置清理回调
                        task.add_done_callback(lambda t: self._message_tasks.pop(task_id, None))
                        
                        # 从记录中移除该用户
                        self.user_records.pop(user_id, None)
                        
                        logger.info(f"已为用户 {user_id} 安排在 {delay} 秒后发送主动消息")
                
                # 每1分钟检查一次，提高时间精度
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            logger.info("检查不活跃会话的任务已取消")
        except Exception as e:
            logger.error(f"检查不活跃会话时发生错误: {str(e)}")
    
    async def _send_initiative_message(self, user_id, conversation_id, unified_msg_origin, delay_seconds):
        """在指定延迟后发送主动消息"""
        try:
            # 等待指定时间
            await asyncio.sleep(delay_seconds)
            
            # 获取对话对象
            conversation = await self.context.conversation_manager.get_conversation(unified_msg_origin, conversation_id)
            context = []
            system_prompt = "你是一个可爱的AI助手，喜欢和用户互动。"
            
            # 获取当前对话的人格设置
            if conversation:
                context = json.loads(conversation.history)
                persona_id = conversation.persona_id
                
                # 获取对话使用的人格设置
                if persona_id is None:
                    # 使用默认人格
                    default_persona = self.context.provider_manager.selected_default_persona
                    if default_persona:
                        system_prompt = default_persona.get('prompt', system_prompt)
                        logger.info(f"使用默认人格: {default_persona.get('name', '未命名')}")
                elif persona_id != "[%None]":
                    # 使用指定人格
                    try:
                        personas = self.context.provider_manager.personas
                        for persona in personas:
                            if persona.get('id') == persona_id:
                                system_prompt = persona.get('prompt', system_prompt)
                                logger.info(f"使用指定人格: {persona.get('name', '未命名')}")
                                break
                    except Exception as e:
                        logger.error(f"获取人格信息时出错: {str(e)}")
            
            # 随机选择一个prompt
            base_prompt = random.choice(self.prompts)
            
            # 根据当前人格调整prompt
            adjusted_prompt = f"{base_prompt}，请保持与你的人格设定一致的风格"
            
            # 获取LLM工具管理器
            func_tools_mgr = self.context.get_llm_tool_manager()
            
            # 调用LLM获取回复
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=adjusted_prompt,
                session_id=None,
                contexts=context,
                image_urls=[],
                func_tool=func_tools_mgr,
                system_prompt=system_prompt
            )
            
            # 获取回复文本
            if llm_response.role == "assistant":
                message_text = llm_response.completion_text
                
                # 使用MessageChain构造消息
                message_chain = MessageChain().message(message_text)
                
                # 直接发送消息
                await self.context.send_message(unified_msg_origin, message_chain)
                
                # 记录日志
                logger.info(f"已向用户 {user_id} 发送主动消息: {message_text}")
                
        except Exception as e:
            logger.error(f"发送主动消息时发生错误: {str(e)}")

    async def terminate(self):
        '''插件被卸载/停用时调用'''
        # 取消所有任务
        if hasattr(self, 'message_check_task'):
            self.message_check_task.cancel()
        
        if hasattr(self, '_message_tasks'):
            for task in self._message_tasks.values():
                task.cancel()
