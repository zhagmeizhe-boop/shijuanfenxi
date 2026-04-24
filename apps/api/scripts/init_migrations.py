#!/usr/bin/env python3
"""
初始化数据库迁移
生成第一个迁移版本

使用方法:
    python init_migrations.py
"""

import subprocess
import sys
import os


def run_command(cmd, description):
    """运行命令并打印结果"""
    print(f"\n{'='*60}")
    print(f"🔹 {description}")
    print(f"{'='*60}")
    print(f"命令: {cmd}")
    print("-" * 60)

    result = subprocess.run(cmd, shell=True, capture_output=False, text=True)

    if result.returncode != 0:
        print(f"❌ 命令执行失败，返回码: {result.returncode}")
        return False

    print(f"✅ 命令执行成功")
    return True


def main():
    """主函数"""
    print("="*60)
    print("🚀 数据库迁移初始化工具")
    print("="*60)

    # 检查是否在正确的目录
    if not os.path.exists("alembic"):
        print("❌ 错误: 找不到 alembic 目录")
        print("请确保在 apps/api 目录下运行此脚本")
        sys.exit(1)

    # 步骤1: 创建迁移版本
    if not run_command(
        "python -m alembic revision --autogenerate -m 'Initial migration'",
        "步骤 1/3: 创建初始迁移版本"
    ):
        sys.exit(1)

    # 步骤2: 执行迁移
    if not run_command(
        "python -m alembic upgrade head",
        "步骤 2/3: 执行数据库迁移"
    ):
        sys.exit(1)

    # 步骤3: 验证迁移
    if not run_command(
        "python -m alembic current",
        "步骤 3/3: 验证当前迁移版本"
    ):
        sys.exit(1)

    print("\n" + "="*60)
    print("✅ 数据库迁移初始化完成！")
    print("="*60)
    print("\n你可以使用以下命令管理迁移:")
    print("  创建新迁移: python -m alembic revision --autogenerate -m '描述'")
    print("  执行迁移:   python -m alembic upgrade head")
    print("  回滚迁移:   python -m alembic downgrade -1")
    print("  查看历史:   python -m alembic history --verbose")


if __name__ == "__main__":
    main()
