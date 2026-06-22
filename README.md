# Bias Core

Bias forum 后端核心平台包。

`bias-core` 是独立于网站工程的 Python 包，提供 Django app、数据模型、扩展宿主、资源 API 运行时和平台服务。

## 安装

```bash
pip install bias-core
```

## 开发

```bash
# 克隆后安装
pip install -e ".[dev]"

# 运行测试
pytest

# 构建
python -m build
```

## 架构

```
bias_core
├─ conf/           # 配置引导和扩展发现
├─ extensions/     # 扩展宿主 + 公共 SDK（第三方扩展唯一依赖）
├─ resources/      # 资源注册表和 JSON:API 运行时
├─ services/       # 平台服务
├─ api/            # API 应用构建器
├─ realtime/       # WebSocket/实时通信支撑
└─ management/     # 管理命令（doctor、sync_extensions 等）
```

## 扩展开发

```python
from bias_core.extensions import SettingsExtender, setting_field

def extend():
    return [
        SettingsExtender(
            fields=[
                setting_field(
                    key="my_ext.enabled",
                    type="boolean",
                    label="Enable feature",
                    default=True,
                )
            ]
        )
    ]
```

## 依赖

- Python >= 3.11
- Django >= 5.0
- django-ninja >= 1.2
- Channels >= 4.0
- Celery >= 5.3

## 许可

MIT
