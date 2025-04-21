import aiohttp
import asyncio



async def get_weather_info(weather_api_key, location):
    """
    使用心知天气的api异步获取天气信息，包括天气状况、温度和地点路径
    返回值为一个元组，包含天气状况、温度和地点路径:
        tuple: 包含天气状况 (weather_text)、温度 (temperature) 和地点路径 (location_path) 的元组。
    """

    # 检查是否成功加载
    if not weather_api_key:
        raise ValueError("未找到 weather_api_key 配置，请检查配置文件！")

    # 请求参数
    url = "https://api.seniverse.com/v3/weather/now.json"
    params = {
        "key": weather_api_key,
        "location": location,
        "language": "zh-Hans",
        "unit": "c",
    }
    timeout = 5

    # 异步发送请求并解析数据
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=timeout) as response:
            data = await response.json()

    # 提取所需信息
    weather_text = data['results'][0]['now']['text']
    temperature = data['results'][0]['now']['temperature']
    location_path = data['results'][0]['location']['path']

    return weather_text, temperature, location_path

if __name__ == "__main__":
    # 测试代码
    weather_api_key = "不告诉你"  # 替换为你的API密钥
    location = "beijing"  # 替换为你想要查询的地点

    # 使用 asyncio.run 调用异步函数
    result = asyncio.run(get_weather_info(weather_api_key, location))
    print(result)