# 后端服务测试说明

## 测试框架

本项目使用 `pytest` 作为自动化测试框架，对后端服务进行全面测试。

## 测试文件结构

```
test/
├── conftest.py                    # pytest配置文件
├── test_data_manager.py           # 数据层测试
├── test_path_calculator.py        # 路径计算测试
├── test_decision_manager.py        # 决策管理测试
├── test_api.py                   # API接口测试
└── requirements.txt              # 测试依赖包
```

## 安装测试依赖

```bash
cd test
pip install -r requirements.txt
```

## 运行测试

### 运行所有测试

```bash
pytest
```

### 运行特定测试文件

```bash
pytest test_data_manager.py
pytest test_path_calculator.py
pytest test_decision_manager.py
pytest test_api.py
```

### 运行特定测试用例

```bash
pytest test_data_manager.py::test_add_task
pytest test_api.py::test_create_task
```

### 显示详细输出

```bash
pytest -v
```

### 显示测试覆盖率

```bash
pytest --cov=../backend --cov-report=html
```

## 测试覆盖范围

### 1. 数据层测试 (test_data_manager.py)

- 任务管理：添加任务、获取任务、获取待处理任务
- 车辆管理：添加车辆、获取车辆、获取空闲车辆
- 充电站管理：添加充电站、获取充电站
- 仓库位置：设置仓库位置
- 系统状态：获取系统状态

### 2. 路径计算测试 (test_path_calculator.py)

- 距离计算：计算路径总距离
- 能耗计算：计算车辆行驶能耗
- 充电站查找：查找最近的充电站
- 路径距离：计算两点间距离

### 3. 决策管理测试 (test_decision_manager.py)

- 系统状态：获取系统状态信息
- 性能评估：评估系统性能指标
- 动态调度：执行动态调度
- 电池管理：管理车辆充电

### 4. API接口测试 (test_api.py)

- 基础接口：根路径、健康检查
- 任务接口：获取任务、创建任务
- 车辆接口：获取车辆、创建车辆
- 充电站接口：获取充电站、创建充电站
- 系统接口：获取系统状态、性能指标、仿真状态
- 调度接口：执行调度、获取策略、获取命令

## 测试注意事项

1. **测试环境**：测试在独立环境中运行，不会影响生产数据
2. **测试数据**：每个测试用例使用独立的测试数据，确保测试之间不相互影响
3. **异步测试**：使用 pytest-asyncio 支持异步测试
4. **API测试**：使用 FastAPI 的 TestClient 模拟 HTTP 请求

## 持续集成

建议将测试集成到 CI/CD 流程中：

```yaml
# 示例 GitHub Actions 配置
name: Run Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          cd test
          pip install -r requirements.txt
      - name: Run tests
        run: pytest --cov=../backend --cov-report=xml
```

## 测试报告

测试完成后，可以生成详细的测试报告：

```bash
# 生成 HTML 覆盖率报告
pytest --cov=../backend --cov-report=html

# 生成 XML 覆盖率报告（用于CI/CD）
pytest --cov=../backend --cov-report=xml
```

## 故障排查

如果测试失败，可以：

1. 查看详细错误信息：`pytest -v`
2. 进入调试模式：`pytest --pdb`
3. 只运行失败的测试：`pytest --lf`
4. 查看测试输出：`pytest -s`

## 贡献指南

添加新的测试用例时，请遵循以下规范：

1. 测试文件名以 `test_` 开头
2. 测试函数名以 `test_` 开头
3. 使用描述性的测试名称
4. 每个测试用例只测试一个功能点
5. 使用 pytest fixtures 共享测试数据
6. 添加必要的断言和错误处理
