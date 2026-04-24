"""日志模块

提供应用日志功能
"""

import logging
import sys

# 配置根日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# 获取应用日志器
logger = logging.getLogger("math_report")

# 导出
def get_logger(name: str = None) -> logging.Logger:
    """获取指定名称的日志器"""
    if name:
        return logging.getLogger(f"math_report.{name}")
    return logger
