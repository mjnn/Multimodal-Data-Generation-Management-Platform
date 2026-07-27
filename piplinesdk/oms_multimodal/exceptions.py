"""SDK 异常定义。"""


class OmsMultimodalError(Exception):
    """SDK 基础异常。"""


class ConfigurationError(OmsMultimodalError):
    """配置缺失或无效。"""


class ApiError(OmsMultimodalError):
    """云端 API 调用失败。"""


class ParseError(OmsMultimodalError):
    """Rosbag 或模型响应解析失败。"""
