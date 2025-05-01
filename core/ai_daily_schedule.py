# AI日程安排管理器 - 生成和管理AI的每日日程安排

import asyncio
import datetime
import json
import os
import pathlib
import random
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("ai_daily_schedule")

class AIDailySchedule:
    """AI日程安排管理器，负责生成和管理AI的每日日程安排"""

    def __init__(self, parent):
        """初始化AI日程安排管理器
        
        Args:
            parent: 父插件实例，用于访问上下文和其他模块
        """
        self.parent = parent
        self.context = parent.context
        
        # 日程数据存储路径
        self.schedule_dir = parent.data_dir / "schedules"
        self.schedule_dir.mkdir(exist_ok=True)
        
        # 今天的日期
        self.today = datetime.datetime.now().date()
        
        # 日程安排 - 修改为所有用户共用一个日程
        self.schedules = {}  # {date: {morning: "...", forenoon: "...", lunch: "...", afternoon: "...", dinner: "...", evening: "...", night: "..."}}
        
        # 定时任务
        self.generate_schedule_task = None

        # 加载配置
        schedule_settings = parent.config.get("schedule_settings", {})
        self.enabled = schedule_settings.get("enabled", True)  # 默认启用
        self.schedule_generation_hour = schedule_settings.get("generation_hour", 0)  # 默认0点生成
        self.schedule_generation_minute = schedule_settings.get("generation_minute", 5)  # 默认5分钟，给系统一些缓冲时间
        self.persona_name = schedule_settings.get("persona_name", "")  # 用于生成日程的人格名称

        # 日程安排提示词
        self.schedule_prompt = (
            "请以JSON格式生成今天AI角色的日程安排，格式要求为：\n"
            "{\n"
            '  "morning": "早上(6-8点)计划做的事情",\n'
            '  "forenoon": "上午(8-11点)计划做的事情",\n'
            '  "lunch": "午饭(11-13点)计划做的事情",\n'
            '  "afternoon": "下午(13-17点)计划做的事情",\n'
            '  "dinner": "晚饭(17-19点)计划做的事情",\n'
            '  "evening": "晚上(19-23点)计划做的事情",\n'
            '  "night": "深夜(23点-次日6点)计划做的事情"\n'
            "}\n"
            "计划应该符合你的人格设定，具体、生动、有趣，但不要太长。"
            "请确保生成的内容是完整的JSON格式，只返回JSON，不要有其他解释文字。"
        )

    async def start(self):
        """启动AI日程安排任务"""
        if not self.enabled:
            logger.info("AI日程安排功能已禁用")
            return

        logger.info("启动AI日程安排任务")
        
        # 加载日程
        self.load_schedules()
        
        # 检查今天是否已生成日程，如果没有则立即生成
        today_str = self.today.isoformat()
        if today_str not in self.schedules:
            logger.info("今天的日程尚未生成，立即开始生成")
            await self.generate_daily_schedule()
        
        # 设置定时任务，每天在指定时间生成新的日程
        self.generate_schedule_task = asyncio.create_task(
            self._schedule_daily_generation()
        )

    async def stop(self):
        """停止AI日程安排任务"""
        if self.generate_schedule_task and not self.generate_schedule_task.done():
            self.generate_schedule_task.cancel()
            try:
                await self.generate_schedule_task
            except asyncio.CancelledError:
                pass
            self.generate_schedule_task = None
            logger.info("AI日程安排任务已停止")

    async def _schedule_daily_generation(self):
        """设置每天定时生成日程的任务"""
        try:
            while True:
                now = datetime.datetime.now()
                # 计算下一次执行时间（今天或明天的指定时间）
                target_time = datetime.datetime(
                    now.year, now.month, now.day,
                    self.schedule_generation_hour, self.schedule_generation_minute
                )
                
                # 如果当前时间已过今天的目标时间，则设置为明天的目标时间
                if now >= target_time:
                    target_time += datetime.timedelta(days=1)
                
                # 计算等待时间
                wait_seconds = (target_time - now).total_seconds()
                logger.info(f"下一次日程安排生成将在 {target_time} 进行，等待 {wait_seconds:.0f} 秒")
                
                # 等待到指定时间
                await asyncio.sleep(wait_seconds)
                
                # 到达指定时间，生成新的日程
                logger.info("开始生成今日AI日程安排")
                self.today = datetime.datetime.now().date()
                await self.generate_daily_schedule()
                
        except asyncio.CancelledError:
            logger.info("AI日程安排定时任务已取消")
            raise
        except Exception as e:
            logger.error(f"AI日程安排定时任务发生错误: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    async def generate_daily_schedule(self):
        """生成今日AI日程安排，所有用户共用一份"""
        try:
            logger.info("正在生成今日AI日程安排...")
            
            # 获取今天的日期字符串
            today_str = self.today.isoformat()
            
            # 获取昨天的日程（如果有）
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).date().isoformat()
            yesterday_schedule = self.schedules.get(yesterday)
            
            # 构建提示词
            prompt = self.schedule_prompt
            
            # 如果有昨天的日程安排，将其加入上下文
            contexts = []
            if yesterday_schedule:
                contexts = [
                    {"role": "system", "content": f"昨天你的日程安排是: {json.dumps(yesterday_schedule, ensure_ascii=False)}。请基于这个安排，生成今天的新日程，保持一定的连续性但有新的内容。"}
                ]
            
            # 获取指定人格的系统提示词
            system_prompt = self.get_persona_system_prompt()
            if self.persona_name:
                logger.info(f"使用人格 '{self.persona_name}' 的系统提示词生成日程安排")
            
            # 直接调用LLM生成日程，不发送消息给用户
            func_tools_mgr = self.context.get_llm_tool_manager()
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                session_id=None,  # 已废弃
                contexts=contexts,  # 上下文（可能包含昨天的日程）
                image_urls=[],  # 没有图片
                func_tool=func_tools_mgr,  # 函数调用工具
                system_prompt=system_prompt  # 使用指定人格的系统提示词
            )
            
            if llm_response.role == "assistant":
                schedule_text = llm_response.completion_text
                
                # 提取JSON部分
                json_start = schedule_text.find('{')
                json_end = schedule_text.rfind('}') + 1
                
                if json_start != -1 and json_end != -1:
                    json_text = schedule_text[json_start:json_end]
                    try:
                        schedule_data = json.loads(json_text)
                        
                        # 验证所需字段
                        required_fields = ["morning", "forenoon", "lunch", "afternoon", "dinner", "evening", "night"]
                        
                        # 检查是否有缺失字段，如果有，添加默认值
                        missing_fields = [field for field in required_fields if field not in schedule_data]
                        if missing_fields:
                            logger.warning(f"日程安排缺少字段: {missing_fields}，将添加默认值")
                            
                            # 添加缺失的字段
                            default_values = {
                                "morning": "准备开始新的一天",
                                "forenoon": "整理个人空间",
                                "lunch": "享用午餐，休息一会儿",
                                "afternoon": "阅读一些有趣的资料",
                                "dinner": "准备晚餐，享用美食",
                                "evening": "放松心情，看看视频或阅读",
                                "night": "睡觉休息，恢复精力"
                            }
                            
                            for field in missing_fields:
                                schedule_data[field] = default_values.get(field, "休息时间")
                        
                        # 保存日程
                        self.schedules[today_str] = schedule_data
                        logger.info("今日AI日程安排已生成")
                        
                        # 保存日程到文件
                        self.save_schedules()
                    except json.JSONDecodeError as json_error:
                        logger.error(f"解析日程安排JSON时出错: {str(json_error)}")
                        logger.error(f"原始JSON文本: {json_text}")
                        self._generate_default_schedule(today_str)
                else:
                    logger.warning(f"日程安排未能识别为JSON格式: {schedule_text}")
                    self._generate_default_schedule(today_str)
            else:
                logger.warning("生成日程安排失败，LLM未返回有效回复")
                self._generate_default_schedule(today_str)
        
        except Exception as e:
            logger.error(f"生成日程安排时发生错误: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 生成默认日程
            today_str = self.today.isoformat()
            self._generate_default_schedule(today_str)
    
    def _generate_default_schedule(self, date_str: str):
        """生成默认的日程安排
        
        Args:
            date_str: 日期字符串，格式为ISO格式的日期
        """
        logger.info("生成默认日程安排")
        self.schedules[date_str] = {
            "morning": "起床，伸个懒腰，准备开始新的一天",
            "forenoon": "整理个人空间，回复一些重要消息",
            "lunch": "享用午餐，休息一会儿",
            "afternoon": "学习和探索新知识，处理一些日常事务",
            "dinner": "准备晚餐，享用美食",
            "evening": "放松心情，看些有趣的视频或阅读",
            "night": "记录今日心得，为明天做准备，然后睡觉休息"
        }
        self.save_schedules()

    def get_schedule_by_time_period(self, time_period: str) -> Optional[str]:
        """根据时间段获取AI日程安排
        
        Args:
            time_period: 时间段，如"早上"、"上午"等
            
        Returns:
            Optional[str]: 该时间段的日程安排内容，如果没有则返回None
        """
        if not self.enabled:
            return None
            
        today_str = self.today.isoformat()
        
        # 如果没有今天的日程，返回None
        if today_str not in self.schedules:
            return None
            
        # 获取今天的日程
        today_schedule = self.schedules[today_str]
        
        # 根据时间段返回对应的日程
        if time_period in ["早上", "早晨"]:
            return today_schedule.get("morning")
        elif time_period in ["上午"]:
            return today_schedule.get("forenoon")
        elif time_period in ["午饭", "中午"]:
            return today_schedule.get("lunch")    
        elif time_period in ["下午", "午后"]:
            return today_schedule.get("afternoon")
        elif time_period in ["晚饭"]:
            return today_schedule.get("dinner")
        elif time_period in ["晚上", "傍晚"]:
            return today_schedule.get("evening")
        elif time_period in ["深夜", "夜晚", "凌晨"]:
            return today_schedule.get("night")
        
        return None

    def save_schedules(self):
        """保存所有AI日程安排到本地文件"""
        try:
            # 确保目录存在
            self.schedule_dir.mkdir(exist_ok=True)
            
            # 保存日程到共用文件
            file_path = self.schedule_dir / "ai_schedules.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.schedules, f, ensure_ascii=False, indent=2)
            
            logger.info(f"AI日程安排已保存到 {file_path}")
        except Exception as e:
            logger.error(f"保存AI日程安排时发生错误: {str(e)}")

    def load_schedules(self):
        """从本地文件加载AI日程安排"""
        try:
            # 确保目录存在
            self.schedule_dir.mkdir(exist_ok=True)
            
            # 读取共用日程文件
            file_path = self.schedule_dir / "ai_schedules.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.schedules = json.load(f)
                logger.info(f"已加载AI日程安排，共有 {len(self.schedules)} 天的安排")
            else:
                logger.info("AI日程安排文件不存在，将创建新的日程")
                self.schedules = {}
                
        except Exception as e:
            logger.error(f"加载AI日程安排时发生错误: {str(e)}")
            self.schedules = {}

    async def generate_daily_schedules_for_all_users(self):
        """手动生成今日AI日程安排的方法，供命令调用"""
        logger.info("手动触发生成今日AI日程安排")
        self.today = datetime.datetime.now().date()
        await self.generate_daily_schedule()
        logger.info("手动生成今日AI日程安排完成")

    def get_data(self) -> Dict[str, Any]:
        """获取模块数据用于持久化
        
        Returns:
            Dict: 包含日程数据的字典
        """
        return {
            "schedules": self.schedules,
            "today": self.today.isoformat()
        }

    def set_data(self, data: Dict[str, Any]):
        """从持久化数据中恢复模块数据
        
        Args:
            data: 包含日程数据的字典
        """
        if "schedules" in data:
            self.schedules = data["schedules"]
            
        if "today" in data:
            try:
                self.today = datetime.date.fromisoformat(data["today"])
            except ValueError:
                self.today = datetime.datetime.now().date()

    def get_persona_system_prompt(self) -> str:
        """获取指定人格的系统提示词
        
        Returns:
            str: 系统提示词，如果未指定人格或找不到指定人格则使用默认提示词
        """
        try:
            # 如果未设置人格名称，则使用默认提示词
            if not self.persona_name:
                logger.info("未指定人格名称，将使用默认系统提示词")
                return "你是一个AI日程生成助手，负责生成清晰、符合AI角色的日程安排，只返回JSON格式结果"
                
            # 从provider_manager获取所有人格
            personas = self.context.provider_manager.personas
            
            # 如果personas为空，使用默认提示词
            if not personas:
                logger.warning("未找到任何人格，将使用默认系统提示词")
                return "你是一个AI日程生成助手，负责生成清晰、符合AI角色的日程安排，只返回JSON格式结果"
            
            # 查找指定名称的人格
            for persona in personas:
                persona_name = persona["name"] if isinstance(persona, dict) else getattr(persona, "name", None)
                persona_prompt = persona["prompt"] if isinstance(persona, dict) else getattr(persona, "prompt", "")
                
                if persona_name == self.persona_name:
                    logger.info(f"找到人格 '{self.persona_name}' 的系统提示词")
                    # 添加一些额外提示，确保生成的是JSON格式
                    prompt = persona_prompt + "\n请严格按照要求，只返回JSON格式的日程安排，不要添加额外解释。"
                    return prompt
            
            # 如果找不到指定名称的人格，尝试获取当前默认人格
            default_persona = getattr(self.context.provider_manager, "selected_default_persona", None)
            default_persona_name = default_persona.get("name", "") if isinstance(default_persona, dict) else None
            
            if default_persona_name:
                for persona in personas:
                    persona_name = persona["name"] if isinstance(persona, dict) else getattr(persona, "name", None)
                    persona_prompt = persona["prompt"] if isinstance(persona, dict) else getattr(persona, "prompt", "")
                    
                    if persona_name == default_persona_name:
                        logger.info(f"未找到指定人格 '{self.persona_name}'，使用默认人格 '{default_persona_name}' 的系统提示词")
                        # 添加一些额外提示，确保生成的是JSON格式
                        prompt = persona_prompt + "\n请严格按照要求，只返回JSON格式的日程安排，不要添加额外解释。"
                        return prompt
            
            # 如果都找不到，使用默认提示词
            logger.warning(f"未找到指定人格 '{self.persona_name}' 或默认人格，将使用默认系统提示词")
            return "你是一个AI日程生成助手，负责生成清晰、符合AI角色的日程安排，只返回JSON格式结果"
        except Exception as e:
            logger.error(f"获取人格系统提示词时出错: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return "你是一个AI日程生成助手，负责生成清晰、符合AI角色的日程安排，只返回JSON格式结果"