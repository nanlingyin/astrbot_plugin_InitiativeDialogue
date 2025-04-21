# 节日检测器 - 检测当前日期是否为特殊节日

import datetime
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import lunardate  # 需要安装此库：pip install lunardate

logger = logging.getLogger("festival_detector")

class FestivalDetector:
    """节日检测器，用于检测特殊节日并提供相关信息"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls, plugin_instance=None):
        """获取单例实例"""
        if cls._instance is None and plugin_instance is not None:
            cls._instance = cls(plugin_instance)
        return cls._instance
        
    def __init__(self, plugin_instance):
        """初始化节日检测器
        
        Args:
            plugin_instance: 父插件实例
        """
        if FestivalDetector._instance is not None:
            raise RuntimeError("请使用get_instance()方法获取实例")
        
        self.plugin = plugin_instance
        self.data_dir = plugin_instance.data_dir
        self.festival_data = self._load_festival_data()
        
        # 当前检测到的节日缓存
        self.current_festival = None
        self.last_check_date = None
        
        FestivalDetector._instance = self
        
        logger.info("节日检测器初始化完成")
    
    def _load_festival_data(self) -> Dict[str, Any]:
        """加载节日数据
        
        Returns:
            Dict: 节日数据字典
        """
        # 首先尝试从配置文件加载
        festivals_data = {}
        
        # 预定义的中国传统节日（农历）
        lunar_festivals = {
            # 格式: (月, 日): ["节日名称", "节日描述", ["提示词1", "提示词2", ...]]
            (1, 1): ["春节", "农历新年，中国最重要的传统节日", [
                "今天是春节，请向用户送上新年祝福，祝愿用户在新的一年里平安健康、万事如意。请确保回复贴合当前的对话上下文情景。",
                "农历新年到了，请向用户表达新春祝福，可以提及红包、团圆饭等春节元素。请确保回复贴合当前的对话上下文情景。",
                "春节快乐！请用充满喜庆的语言向用户送上新年的祝福和美好的期望。请确保回复贴合当前的对话上下文情景。"
            ]],
            (1, 15): ["元宵节", "新年的第一个月圆之夜", [
                "今天是元宵节，请向用户问候，可以提及元宵、汤圆和灯笼等元素，表达团圆美满的祝福。请确保回复贴合当前的对话上下文情景。",
                "元宵佳节到了，请与用户分享元宵节的美好，可以谈论猜灯谜、赏花灯的传统。请确保回复贴合当前的对话上下文情景。",
                "元宵节快乐！请向用户表达节日问候，可以询问用户是否吃了汤圆或元宵。请确保回复贴合当前的对话上下文情景。"
            ]],
            (5, 5): ["端午节", "纪念屈原的传统节日", [
                "今天是端午节，请向用户送上节日祝福，可以提及粽子、龙舟和艾草等传统元素。请确保回复贴合当前的对话上下文情景。",
                "端午安康！请与用户谈论端午节的习俗，如吃粽子、赛龙舟等传统活动。请确保回复贴合当前的对话上下文情景。",
                "端午节到了，请询问用户是否吃了粽子，并送上健康平安的祝福。请确保回复贴合当前的对话上下文情景。"
            ]],
            (7, 7): ["七夕节", "中国传统情人节", [
                "今天是七夕节，请向用户送上浪漫的节日祝福，可以提及牛郎织女的故事。请确保回复贴合当前的对话上下文情景。",
                "七夕佳节，请与用户分享这个中国传统情人节的美好，表达对爱情的祝福。请确保回复贴合当前的对话上下文情景。",
                "七夕到了，请向用户表达节日问候，可以谈论关于牛郎织女或星空的浪漫元素。请确保回复贴合当前的对话上下文情景。"
            ]],
            (8, 15): ["中秋节", "团圆与丰收的节日", [
                "今天是中秋节，请向用户送上团圆的祝福，可以提及月饼、明月和家人团聚等元素。请确保回复贴合当前的对话上下文情景。",
                "中秋佳节，请与用户分享赏月、吃月饼的传统，表达对团圆的美好祝愿。请确保回复贴合当前的对话上下文情景。",
                "中秋快乐！请向用户问候，询问是否与家人团聚，并表达对圆满生活的祝福。请确保回复贴合当前的对话上下文情景。"
            ]],
            (9, 9): ["重阳节", "敬老的传统节日", [
                "今天是重阳节，请向用户送上节日祝福，可以提及登高、赏菊和敬老等传统。请确保回复贴合当前的对话上下文情景。",
                "重阳佳节，请与用户分享这个尊老敬老的节日意义，送上健康长寿的祝福。请确保回复贴合当前的对话上下文情景。",
                "重阳节到了，请向用户表达节日问候，可以谈论菊花茶、重阳糕等节日元素。请确保回复贴合当前的对话上下文情景。"
            ]],
            (12, 8): ["腊八节", "传统佛教节日", [
                "今天是腊八节，请向用户送上节日祝福，可以提及腊八粥的传统。请确保回复贴合当前的对话上下文情景。",
                "腊八到了，请与用户分享喝腊八粥的习俗，表达冬日的温暖祝福。请确保回复贴合当前的对话上下文情景。",
                "腊八节快乐！请询问用户是否喝了腊八粥，并送上温馨的问候。请确保回复贴合当前的对话上下文情景。"
            ]],
            (12, 29): ["除夕", "农历年的最后一天", [
                "今天是除夕，请向用户送上新年前夕的祝福，可以提及团圆饭、守岁等传统。请确保回复贴合当前的对话上下文情景。",
                "除夕夜到了，请与用户分享这个辞旧迎新的重要时刻，表达对新年的期待。请确保回复贴合当前的对话上下文情景。",
                "除夕快乐！请向用户问候，谈论贴春联、放鞭炮等年俗活动，送上温馨祝福。请确保回复贴合当前的对话上下文情景。"
            ]],
        }
        
        # 预定义的公历节日
        solar_festivals = {
            # 格式: (月, 日): ["节日名称", "节日描述", ["提示词1", "提示词2", ...]]
            (1, 1): ["元旦", "新年第一天", [
                "今天是元旦，新的一年开始了，请向用户送上新年的第一份祝福。请确保回复贴合当前的对话上下文情景。",
                "元旦快乐！请与用户分享对新一年的美好期望和祝愿。请确保回复贴合当前的对话上下文情景。",
                "新年第一天，请向用户表达元旦祝福，鼓励用户在新的一年里充满希望。请确保回复贴合当前的对话上下文情景。"
            ]],
            (2, 14): ["情人节", "西方的爱情节日", [
                "今天是情人节，请向用户送上温馨浪漫的祝福，表达对爱的美好祝愿。请确保回复贴合当前的对话上下文情景。",
                "情人节快乐！请与用户分享这个关于爱的节日，可以提及玫瑰、巧克力等元素。请确保回复贴合当前的对话上下文情景。",
                "情人节到了，请向用户表达节日问候，送上关于爱与浪漫的祝福。请确保回复贴合当前的对话上下文情景。"
            ]],
            (5, 1): ["劳动节", "国际劳动节", [
                "今天是劳动节，请向用户送上节日祝福，肯定劳动的价值与意义。请确保回复贴合当前的对话上下文情景。",
                "劳动节快乐！请与用户分享这个表彰劳动人民的节日，送上休息放松的祝福。请确保回复贴合当前的对话上下文情景。",
                "五一劳动节到了，请向用户问候，可以谈论假期安排和休闲活动。请确保回复贴合当前的对话上下文情景。"
            ]],
            (10, 1): ["国庆节", "中华人民共和国成立纪念日", [
                "今天是国庆节，请向用户送上爱国的祝福，表达对祖国的美好祝愿。请确保回复贴合当前的对话上下文情景。",
                "国庆快乐！请与用户分享这个举国同庆的节日，可以提及阅兵、旅游等元素。请确保回复贴合当前的对话上下文情景。",
                "十一国庆到了，请向用户表达节日问候，可以谈论假期安排和爱国情怀。请确保回复贴合当前的对话上下文情景。"
            ]],
            (11, 1): ["万圣节", "西方传统节日", [
                "今天是万圣节，请向用户送上有趣的节日祝福，可以提及南瓜灯、糖果等元素。请确保回复贴合当前的对话上下文情景。",
                "万圣节快乐！请与用户分享这个神秘有趣的节日，谈谈变装派对和讨糖活动。请确保回复贴合当前的对话上下文情景。",
                "Happy Halloween! 请向用户问候，可以用稍微恐怖又有趣的方式表达节日氛围。请确保回复贴合当前的对话上下文情景。"
            ]],
            (12, 25): ["圣诞节", "西方重要节日", [
                "今天是圣诞节，请向用户送上温馨的节日祝福，可以提及圣诞老人、圣诞树等元素。请确保回复贴合当前的对话上下文情景。",
                "圣诞快乐！请与用户分享这个充满爱与分享的节日，谈谈礼物和平安夜的传统。请确保回复贴合当前的对话上下文情景。",
                "Merry Christmas! 请向用户表达节日问候，营造温暖祥和的圣诞气氛。请确保回复贴合当前的对话上下文情景。"
            ]],
        }
        
        # 特殊计算的节日（需要额外逻辑）
        special_festivals = {
            "母亲节": ["每年5月第二个星期日", "感恩母亲的节日", [
                "今天是母亲节，请向用户送上对母亲的感恩与祝福。请确保回复贴合当前的对话上下文情景。",
                "母亲节快乐！请与用户分享这个感恩母爱的日子，表达对母亲的敬意。请确保回复贴合当前的对话上下文情景。",
                "母亲节到了，请向用户问候，可以谈论感恩母亲、表达爱意的方式。请确保回复贴合当前的对话上下文情景。"
            ]],
            "父亲节": ["每年6月第三个星期日", "感恩父亲的节日", [
                "今天是父亲节，请向用户送上对父亲的感恩与祝福。请确保回复贴合当前的对话上下文情景。",
                "父亲节快乐！请与用户分享这个感恩父爱的日子，表达对父亲的敬意。请确保回复贴合当前的对话上下文情景。",
                "父亲节到了，请向用户问候，可以谈论感恩父亲、表达感谢的方式。请确保回复贴合当前的对话上下文情景。"
            ]],
            "感恩节": ["每年11月第四个星期四", "美国传统节日", [
                "今天是感恩节，请向用户送上感恩的祝福，表达对生活感恩的态度。请确保回复贴合当前的对话上下文情景。",
                "感恩节快乐！请与用户分享这个表达感谢的节日，谈谈感恩的意义。请确保回复贴合当前的对话上下文情景。",
                "Happy Thanksgiving! 请向用户问候，可以谈论感恩晚餐和家人团聚。请确保回复贴合当前的对话上下文情景。"
            ]],
        }
        
        festivals_data = {
            "lunar_festivals": lunar_festivals,
            "solar_festivals": solar_festivals,
            "special_festivals": special_festivals
        }
        
        return festivals_data
    
    def check_today_festival(self) -> Optional[Tuple[str, str, List[str]]]:
        """检查今天是否为特殊节日
        
        Returns:
            Optional[Tuple[str, str, List[str]]]: 节日信息(名称, 描述, 提示词列表)，如果不是节日则返回None
        """
        today = datetime.date.today()
        
        # 如果今天已经检查过，直接返回缓存结果
        if self.last_check_date == today:
            return self.current_festival
            
        self.last_check_date = today
        self.current_festival = None
        
        # 检查公历节日
        month, day = today.month, today.day
        solar_key = (month, day)
        if solar_key in self.festival_data["solar_festivals"]:
            self.current_festival = self.festival_data["solar_festivals"][solar_key]
            logger.info(f"今天是公历节日: {self.current_festival[0]}")
            return self.current_festival
            
        # 检查农历节日
        try:
            lunar_date = lunardate.LunarDate.fromSolarDate(today.year, month, day)
            lunar_key = (lunar_date.month, lunar_date.day)
            if lunar_key in self.festival_data["lunar_festivals"]:
                self.current_festival = self.festival_data["lunar_festivals"][lunar_key]
                logger.info(f"今天是农历节日: {self.current_festival[0]}")
                return self.current_festival
        except:
            logger.error("转换农历日期时出错")
            
        # 检查特殊计算的节日
        # 母亲节：5月第二个星期日
        if month == 5 and 8 <= day <= 14 and today.weekday() == 6:  # 周日
            self.current_festival = self.festival_data["special_festivals"]["母亲节"]
            logger.info("今天是母亲节")
            return self.current_festival
            
        # 父亲节：6月第三个星期日
        if month == 6 and 15 <= day <= 21 and today.weekday() == 6:  # 周日
            self.current_festival = self.festival_data["special_festivals"]["父亲节"]
            logger.info("今天是父亲节")
            return self.current_festival
            
        # 感恩节：11月第四个星期四
        if month == 11 and 22 <= day <= 28 and today.weekday() == 3:  # 周四
            self.current_festival = self.festival_data["special_festivals"]["感恩节"]
            logger.info("今天是感恩节")
            return self.current_festival
            
        logger.debug("今天不是特殊节日")
        return None
    
    def get_festival_prompts(self) -> Optional[List[str]]:
        """获取当前节日的提示词列表
        
        Returns:
            Optional[List[str]]: 节日提示词列表，如果不是节日则返回None
        """
        festival = self.check_today_festival()
        if festival:
            return festival[2]  # 返回提示词列表
        return None
    
    def get_festival_name(self) -> Optional[str]:
        """获取当前节日名称
        
        Returns:
            Optional[str]: 节日名称，如果不是节日则返回None
        """
        festival = self.check_today_festival()
        if festival:
            return festival[0]  # 返回节日名称
        return None
    
    def get_festival_info(self) -> Optional[Dict[str, Any]]:
        """获取完整的节日信息
        
        Returns:
            Optional[Dict[str, Any]]: 节日信息字典，如果不是节日则返回None
        """
        festival = self.check_today_festival()
        if festival:
            return {
                "name": festival[0],
                "description": festival[1],
                "prompts": festival[2]
            }
        return None
