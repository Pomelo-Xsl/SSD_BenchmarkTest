"""Linux 发行版、工具链和权限能力兼容探测。"""
from __future__ import annotations
import os, platform, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
@dataclass(frozen=True)
class Capability:
    key:str; available:bool; required:bool; detail:str; remedy:str
class PlatformCompatibilityService:
    REQUIRED=("fio","lsblk")
    OPTIONAL=("nvme","smartctl","systemctl","journalctl")
    @staticmethod
    def os_release(path:Path=Path('/etc/os-release'))->dict[str,str]:
        if not path.exists():return {"name":platform.system(),"id":"unknown"}
        result={}
        for line in path.read_text(errors='ignore').splitlines():
            if '=' in line:
                k,v=line.split('=',1);result[k.lower()]=v.strip().strip('"')
        return {"name":result.get('pretty_name',result.get('name','Linux')),"id":result.get('id','unknown'),"version":result.get('version_id','unknown')}
    @staticmethod
    def tool(name:str,required:bool)->Capability:
        location=shutil.which(name)
        if location:return Capability(name,True,required,f"已找到：{location}","")
        remedy=f"请使用系统包管理器安装 {name}" if required else f"未安装 {name}，相关扩展功能将不可用"
        return Capability(name,False,required,"未找到可执行文件",remedy)
    @classmethod
    def inspect(cls)->dict[str,Any]:
        items=[cls.tool(name,True) for name in cls.REQUIRED]+[cls.tool(name,False) for name in cls.OPTIONAL]
        return {"platform":platform.platform(),"architecture":platform.machine(),"os":cls.os_release(),"python":platform.python_version(),"effective_uid":os.geteuid() if hasattr(os,'geteuid') else None,"capabilities":[item.__dict__ for item in items],"ready":all(item.available for item in items if item.required)}
    @staticmethod
    def filesystem(path:str)->dict[str,Any]:
        target=Path(path);exists=target.exists();return {"path":str(target),"exists":exists,"readable":os.access(target,os.R_OK) if exists else False,"writable":os.access(target,os.W_OK) if exists else False}
