# Description: 一个主动对话插件，当用户长时间不回复时主动发送消息
from astrbot.api.all import *
from astrbot.api.event import filter  # 明确导入对象
from astrbot.api.provider import ProviderRequest  # 添加导入
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
        
        # 跟踪最近收到过主动消息的用户，用于检测用户回复
        self.users_received_initiative = set()
        
        # 加载配置
        self.config = config or {}
        self.time_settings = self.config.get('time_settings', {})
        
        # 设置时间参数（使用配置文件的值或默认值）
        self.time_limit_enabled = self.time_settings.get('time_limit_enabled', True)  # 默认启用时间限制
        self.inactive_time_seconds = self.time_settings.get('inactive_time_seconds', 7200)  # 默认2小时
        self.max_response_delay_seconds = self.time_settings.get('max_response_delay_seconds', 3600)  # 默认1小时
        self.activity_start_hour = self.time_settings.get('activity_start_hour', 8)  # 默认8点
        self.activity_end_hour = self.time_settings.get('activity_end_hour', 23)  # 默认23点
        
        # 加载白名单配置
        self.whitelist_config = self.config.get('whitelist', {})
        self.whitelist_enabled = self.whitelist_config.get('enabled', False)
        self.whitelist_users = set(self.whitelist_config.get('user_ids', []))
        
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
                    f"时间限制: {'启用' if self.time_limit_enabled else '禁用'}, "
                    f"活动时间: {self.activity_start_hour}点-{self.activity_end_hour}点")
        logger.info(f"白名单功能状态: {'启用' if self.whitelist_enabled else '禁用'}, "
                    f"白名单用户数量: {len(self.whitelist_users)}")
        
        # 存储消息任务的字典
        self._message_tasks = {}
        
        # 启动检查任务
        self.message_check_task = asyncio.create_task(self._check_inactive_conversations())
        # 记录任务以防止被垃圾回收
        self.tasks = {"check_inactive": self.message_check_task}
        
        logger.info("主动对话插件初始化完成，检测任务已启动")
    
    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        """处理私聊消息"""
        user_id = str(event.get_sender_id())
        message_str = event.message_str
        current_time = datetime.datetime.now()
        
        # 检查用户是否刚收到过主动消息（用于后续钩子中判断）
        user_responding_to_initiative = user_id in self.users_received_initiative
        if user_responding_to_initiative:
            logger.info(f"用户 {user_id} 回复了主动消息，将在LLM请求钩子中添加欣喜表达")
            # 不要在这里移除用户ID，让钩子函数处理
            # self.users_received_initiative.remove(user_id)
        
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
        
        # 检查用户是否在白名单中（如果启用了白名单）
        is_whitelisted = True
        if self.whitelist_enabled:
            is_whitelisted = user_id in self.whitelist_users
        
        # 更新或创建用户记录（仅当用户在白名单中或白名单未启用时）
        if is_whitelisted:
            self.user_records[user_id] = {
                'conversation_id': curr_cid,
                'timestamp': current_time,
                'unified_msg_origin': event.unified_msg_origin
            }
            logger.info(f"用户 {user_id} 已加入主动对话监控，当前监控总数: {len(self.user_records)}，会话ID: {curr_cid}")
        else:
            logger.info(f"用户 {user_id} 未在白名单中，不加入监控")
    
    @filter.on_llm_request()
    async def check_initiative_response(self, event, req: ProviderRequest):
        """检查是否是对主动消息的回复，并修改提示词"""
        if event is None:
            return
            
        try:
            user_id = str(event.get_sender_id())
            # 仅当用户处于"回复主动消息"状态时修改请求
            if user_id in self.users_received_initiative:
                logger.info(f"[钩子触发] 检测到用户 {user_id} 正在回复主动消息，添加欣喜表达提示")
                
                # 修改用户提示词（prompt而非system_prompt），添加对用户回复的欣喜反应
                original_prompt = req.prompt or ""
                excitement_addition = "\n请注意：用户刚刚回复了你的主动消息，这表明用户关注到了你。请在回复的开头一定要明确表达出你对用户回复的欣喜和感激之情，语气要热情、自然。之后再正常回答用户的问题。即使用户只是简单回复'嗯'、'哦'等词语，也要表现出欣喜情绪。"
                req.prompt = original_prompt + excitement_addition
                
                # 记录详细日志，帮助调试
                logger.info(f"[钩子日志] 用户ID: {user_id}")
                logger.info(f"[钩子日志] 原始提示词: {original_prompt[:50]}...")
                logger.info(f"[钩子日志] 修改后提示词: {req.prompt[:50]}...")
                logger.info(f"[钩子日志] 用户消息: {event.message_str}")
                
                # 从集合中移除用户，避免重复处理
                self.users_received_initiative.remove(user_id)
                logger.info(f"[钩子日志] 已从回复检测集合中移除用户 {user_id}")
        except Exception as e:
            logger.error(f"[钩子错误] 处理用户回复主动消息时出错: {str(e)}")
    
    async def _check_inactive_conversations(self):
        """定期检查不活跃的会话，并发送主动消息"""
        try:
            while True:
                current_time = datetime.datetime.now()
                
                # 检查当前时间是否在允许的活动时间段内（如果启用了时间限制）
                current_hour = current_time.hour
                is_active_time = True  # 默认为活动时间
                
                # 仅当启用时间限制时才检查时间段
                if self.time_limit_enabled:
                    is_active_time = self.activity_start_hour <= current_hour < self.activity_end_hour
                
                if is_active_time and self.user_records:  # 只有当有用户记录时才继续处理
                    users_to_message = []
                    
                    # 检查每个用户记录
                    for user_id, record in list(self.user_records.items()):
                        # 如果启用白名单，检查用户是否在白名单中
                        if self.whitelist_enabled and user_id not in self.whitelist_users:
                            # 从记录中移除非白名单用户
                            self.user_records.pop(user_id, None)
                            logger.info(f"用户 {user_id} 不在白名单中，已从监控记录中移除")
                            continue
                            
                        # 计算自上次消息以来的时间（秒）
                        seconds_elapsed = (current_time - record['timestamp']).total_seconds()
                        
                        # 检查是否在发送窗口期内
                        if seconds_elapsed >= (self.inactive_time_seconds + self.max_response_delay_seconds):
                            # 重置这些用户的记录
                            record['timestamp'] = current_time
                            continue
                        
                        # 只处理那些刚好超过不活跃阈值但未超过阈值+窗口时间的记录
                        if self.inactive_time_seconds <= seconds_elapsed < (self.inactive_time_seconds + self.max_response_delay_seconds):
                            users_to_message.append((user_id, record))
                    
                    # 为每个需要发送消息的用户安排一个随机时间发送
                    if users_to_message:
                        logger.info(f"发现 {len(users_to_message)} 个需要发送主动消息的用户")
                        
                    for user_id, record in users_to_message:
                        # 计算还剩多少时间到窗口结束（最多为最大延迟时间）
                        seconds_elapsed = (current_time - record['timestamp']).total_seconds()
                        max_delay = min(self.inactive_time_seconds + self.max_response_delay_seconds - seconds_elapsed, 
                                       self.max_response_delay_seconds)
                        
                        # 在剩余时间内随机选择一个时间点
                        delay = random.randint(1, int(max_delay))
                        
                        # 获取连续发送计数（如果已存在）
                        consecutive_count = record.get('consecutive_count', 0) + 1
                        
                        # 创建并存储任务，以防垃圾回收
                        task_id = f"send_message_{user_id}_{int(time.time())}"
                        task = asyncio.create_task(self._send_initiative_message(
                            user_id=user_id,
                            conversation_id=record['conversation_id'],
                            unified_msg_origin=record['unified_msg_origin'],
                            delay_seconds=delay,
                            consecutive_count=consecutive_count  # 传递当前连续发送次数
                        ))
                        
                        # 确保_message_tasks字典已初始化
                        if not hasattr(self, '_message_tasks'):
                            self._message_tasks = {}
                            
                        self._message_tasks[task_id] = task
                        
                        # 设置清理回调
                        def remove_task(t, tid=task_id):
                            if tid in self._message_tasks:
                                self._message_tasks.pop(tid, None)
                            
                        task.add_done_callback(remove_task)
                        
                        # 从记录中移除该用户
                        self.user_records.pop(user_id, None)
                        
                        scheduled_time = current_time + datetime.timedelta(seconds=delay)
                        logger.info(f"为用户 {user_id} 安排在 {delay} 秒后({scheduled_time.strftime('%H:%M:%S')})发送主动消息，连续发送次数: {consecutive_count}")
                
                # 每10秒检查一次，提高时间精度
                await asyncio.sleep(10)
                
        except asyncio.CancelledError:
            logger.info("检查不活跃会话的任务已取消")
        except Exception as e:
            logger.error(f"检查不活跃会话时发生错误: {str(e)}")
            # 尝试重新启动检查任务
            logger.info("尝试重新启动检查任务")
            await asyncio.sleep(5)
            self.message_check_task = asyncio.create_task(self._check_inactive_conversations())
            self.tasks["check_inactive"] = self.message_check_task
    
    async def _send_initiative_message(self, user_id, conversation_id, unified_msg_origin, delay_seconds, consecutive_count=1):
        """在指定延迟后发送主动消息"""
        try:
            # 等待指定时间
            await asyncio.sleep(delay_seconds)
            
            # 再次检查用户是否在白名单中（针对延迟期间可能发生的白名单变化）
            if self.whitelist_enabled and user_id not in self.whitelist_users:
                logger.info(f"用户 {user_id} 不再在白名单中，取消发送主动消息")
                return
                
            # 获取对话对象
            conversation = await self.context.conversation_manager.get_conversation(unified_msg_origin, conversation_id)
            
            if not conversation:
                logger.error(f"无法获取用户 {user_id} 的对话，会话ID: {conversation_id} 可能不存在")
                return
                
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
                elif persona_id != "[%None]":
                    # 使用指定人格
                    try:
                        personas = self.context.provider_manager.personas
                        for persona in personas:
                            if persona.get('id') == persona_id:
                                system_prompt = persona.get('prompt', system_prompt)
                                break
                    except Exception as e:
                        logger.error(f"获取人格信息时出错: {str(e)}")
            
            # 设置最大连续发送次数（从配置文件读取，默认为3）
            max_consecutive_messages = self.time_settings.get('max_consecutive_messages', 3)
            
            # 随机选择一个prompt
            base_prompt = random.choice(self.prompts)
            
            # 根据连续发送次数调整prompt
            adjusted_prompt = base_prompt
            if consecutive_count == max_consecutive_messages:  # 最后一次发送
                adjusted_prompt = f"假设这是你最后一次主动联系用户，之前已经联系了{consecutive_count-1}次但用户都没有回复。请用简短的一句话，表达你对用户一直不回复感到失望和伤心，同时表示你理解他/她可能很忙，以后不会再主动打扰，但会一直等待用户回来找你聊天的。保持与你的人格设定一致的风格。"
            elif consecutive_count > 1:
                # 如果这是连续的第N次发送，调整提示词
                adjusted_prompt = f"假设这是你第{consecutive_count}次主动联系用户，但用户仍然没有回复你。{base_prompt}，请表达出你的耐心等待和真诚期待，但不要表现得过于急切或打扰用户。"
            else:
                adjusted_prompt = f"{base_prompt}，请保持与你的人格设定一致的风格"
            
            # 获取LLM工具管理器
            func_tools_mgr = self.context.get_llm_tool_manager()
            
            # 调用LLM获取回复
            logger.info(f"正在为用户 {user_id} 生成主动消息内容...")
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
                logger.info(f"已向用户 {user_id} 发送第 {consecutive_count} 条连续主动消息: {message_text}")
                
                # 将用户添加到已接收主动消息用户集合中，用于检测用户回复
                self.users_received_initiative.add(user_id)
                logger.info(f"用户 {user_id} 已添加到主动消息回复检测中，当前集合大小: {len(self.users_received_initiative)}")
                
                # 如果未超过最大连续发送次数，将用户重新加入记录以继续监控
                if consecutive_count < max_consecutive_messages:
                    current_time = datetime.datetime.now()
                    # 将用户重新添加到记录中，以重新开始计时
                    self.user_records[user_id] = {
                        'conversation_id': conversation_id,
                        'timestamp': current_time,
                        'unified_msg_origin': unified_msg_origin,
                        'consecutive_count': consecutive_count  # 记录已经连续发送的次数
                    }
                    logger.info(f"用户 {user_id} 未回复，已重新加入监控记录，当前连续发送次数: {consecutive_count}")
                else:
                    logger.info(f"用户 {user_id} 已达到最大连续发送次数({max_consecutive_messages})，停止连续发送")
            else:
                logger.error(f"生成消息失败，LLM响应角色错误: {llm_response.role}")
                
        except asyncio.CancelledError:
            logger.info(f"发送给用户 {user_id} 的主动消息任务已被取消")
        except Exception as e:
            logger.error(f"发送主动消息时发生错误: {str(e)}")

    async def terminate(self):
        '''插件被卸载/停用时调用'''
        logger.info("正在停止主动对话插件...")
        
        # 取消所有任务
        if hasattr(self, 'message_check_task'):
            self.message_check_task.cancel()
            logger.info("已取消主检查任务")
        
        if hasattr(self, '_message_tasks'):
            task_count = len(self._message_tasks)
            for task_id, task in list(self._message_tasks.items()):
                task.cancel()
            logger.info(f"已取消 {task_count} 个待发送的消息任务")
            
        logger.info("主动对话插件已成功停止")
