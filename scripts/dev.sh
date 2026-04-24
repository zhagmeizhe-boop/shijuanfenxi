#!/bin/bash
# ============================================
# Math Analysis System - 开发启动脚本
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${CYAN}"
    echo "========================================"
    echo "  $1"
    echo "========================================"
    echo -e "${NC}"
}

# 检查命令是否存在
check_command() {
    if ! command -v $1 &> /dev/null; then
        return 1
    fi
    return 0
}

# 检查 Docker 和 Docker Compose
check_docker() {
    print_info "检查 Docker 环境..."

    if ! check_command docker; then
        print_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    if ! check_command docker-compose; then
        print_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi

    # 检查 Docker 服务是否运行
    if ! docker info &> /dev/null; then
        print_error "Docker 服务未运行，请启动 Docker 服务"
        exit 1
    fi

    print_success "Docker 环境检查通过"
}

# 检查 .env 文件
check_env_file() {
    print_info "检查环境变量文件..."

    if [ ! -f ".env" ]; then
        print_warning ".env 文件不存在，从 .env.example 创建..."
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_success ".env 文件已创建，请根据需要修改配置"
        else
            print_error ".env.example 文件也不存在"
            exit 1
        fi
    else
        print_success ".env 文件已存在"
    fi
}

# 启动服务
start_services() {
    print_header "启动服务"

    check_docker
    check_env_file

    print_info "构建并启动 Docker 服务..."
    docker-compose up -d --build

    if [ $? -eq 0 ]; then
        print_success "服务启动成功！"
        print_info "服务访问地址："
        echo "  - 前端界面: http://localhost:3000"
        echo "  - 后端 API: http://localhost:8000"
        echo "  - API 文档: http://localhost:8000/docs"
        echo "  - 数据库:   localhost:5432"
        echo "  - Redis:   localhost:6379"
    else
        print_error "服务启动失败，请检查日志"
        exit 1
    fi
}

# 停止服务
stop_services() {
    print_header "停止服务"

    print_info "停止 Docker 服务..."
    docker-compose down

    if [ $? -eq 0 ]; then
        print_success "服务已停止"
    else
        print_error "停止服务时出错"
    fi
}

# 查看日志
view_logs() {
    print_header "查看日志"

    if [ -z "$1" ]; then
        print_info "显示所有服务日志..."
        docker-compose logs -f
    else
        print_info "显示 $1 服务日志..."
        docker-compose logs -f $1
    fi
}

# 重启服务
restart_services() {
    print_header "重启服务"
    stop_services
    start_services
}

# 重置环境（删除数据）
reset_environment() {
    print_header "重置环境"

    print_warning "这将删除所有数据卷，包括数据库数据！"
    read -p "确定要继续吗？(yes/no): " confirm

    if [ "$confirm" != "yes" ]; then
        print_info "操作已取消"
        return
    fi

    print_info "停止服务并删除数据卷..."
    docker-compose down -v

    print_info "删除构建缓存..."
    docker-compose rm -f

    print_success "环境已重置"
}

# 检查服务健康状态
check_health() {
    print_header "检查服务健康状态"

    # 检查后端 API
    print_info "检查后端 API..."
    if curl -s http://localhost:8000/health > /dev/null; then
        print_success "后端 API 健康"
    else
        print_error "后端 API 未响应"
    fi

    # 检查前端
    print_info "检查前端..."
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200\|307"; then
        print_success "前端服务正常"
    else
        print_error "前端服务未响应"
    fi

    # 检查数据库
    print_info "检查数据库..."
    if docker-compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
        print_success "数据库连接正常"
    else
        print_error "数据库未就绪"
    fi

    # 检查 Redis
    print_info "检查 Redis..."
    if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
        print_success "Redis 连接正常"
    else
        print_error "Redis 未就绪"
    fi
}

# 显示帮助信息
show_help() {
    echo ""
    print_header "使用帮助"
    echo ""
    echo "用法: ./scripts/dev.sh [命令] [选项]"
    echo ""
    echo "命令:"
    echo "  start              启动所有服务"
    echo "  stop               停止所有服务"
    echo "  restart            重启所有服务"
    echo "  logs [服务名]      查看服务日志"
    echo "  health             检查服务健康状态"
    echo "  reset              重置环境（删除所有数据）"
    echo "  help               显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  ./scripts/dev.sh start           # 启动所有服务"
    echo "  ./scripts/dev.sh logs api        # 查看后端日志"
    echo "  ./scripts/dev.sh health          # 检查服务健康状态"
    echo ""
}

# 主函数
main() {
    # 确保在正确的目录
    if [ ! -f "docker-compose.yml" ]; then
        print_error "请在项目根目录运行此脚本"
        exit 1
    fi

    # 检查参数
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    # 执行命令
    case "$1" in
        start)
            start_services
            ;;
        stop)
            stop_services
            ;;
        restart)
            restart_services
            ;;
        logs)
            view_logs "$2"
            ;;
        health)
            check_health
            ;;
        reset)
            reset_environment
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $1"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
