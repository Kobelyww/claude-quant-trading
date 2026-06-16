import os
from .models import AppSetting


def get_setting(key, default=""):
    """从数据库读取配置，未配置则回退到环境变量"""
    setting = AppSetting.objects.filter(key=key).first()
    if setting and setting.value:
        return setting.value
    return os.getenv(key, default)


def set_setting(key, value):
    """保存配置到数据库 + 更新 os.environ + 写入 .env"""
    setting, _ = AppSetting.objects.update_or_create(
        key=key, defaults={"value": value}
    )
    os.environ[key] = value
    # Write to .env file for persistence across restarts
    _write_env()
    return setting


def _write_env():
    """将所有 AppSetting 写回 .env 文件"""
    from pathlib import Path
    from django.conf import settings

    env_path = settings.BASE_DIR.parent / ".env"
    lines = []
    for s in AppSetting.objects.all():
        if s.key:
            lines.append(f"{s.key}={s.value}")
    with open(env_path, "w") as f:
        f.write("\n".join(lines) + "\n")
