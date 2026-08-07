"""fio 参数模板管理服务。"""
from __future__ import annotations
import json
from sqlalchemy.orm import Session
from app.models import BenchmarkTemplate
from app.services.fio_service import FioOptions, TESTS


class TemplateService:
    @staticmethod
    def validate(test_name: str, fio_options: dict) -> dict:
        if test_name not in TESTS:
            raise ValueError("不支持的测试类型")
        return FioOptions.from_mapping(fio_options).as_dict()

    @classmethod
    def create(cls, db: Session, name: str, description: str | None, test_name: str, fio_options: dict) -> BenchmarkTemplate:
        if db.query(BenchmarkTemplate).filter(BenchmarkTemplate.name == name).first():
            raise ValueError("模板名称已存在")
        template = BenchmarkTemplate(name=name.strip(), description=description.strip() if description else None, test_name=test_name, fio_options=json.dumps(cls.validate(test_name, fio_options), ensure_ascii=False))
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    @classmethod
    def update(cls, db: Session, template: BenchmarkTemplate, name: str | None = None, description: str | None = None, test_name: str | None = None, fio_options: dict | None = None) -> BenchmarkTemplate:
        next_name = name.strip() if name else template.name
        if next_name != template.name and db.query(BenchmarkTemplate).filter(BenchmarkTemplate.name == next_name).first():
            raise ValueError("模板名称已存在")
        next_test = test_name or template.test_name
        next_options = fio_options if fio_options is not None else json.loads(template.fio_options)
        template.name, template.description, template.test_name = next_name, description.strip() if description is not None else template.description, next_test
        template.fio_options = json.dumps(cls.validate(next_test, next_options), ensure_ascii=False)
        db.commit()
        db.refresh(template)
        return template

    @staticmethod
    def as_dict(template: BenchmarkTemplate) -> dict:
        return {"id": template.id, "name": template.name, "description": template.description, "test_name": template.test_name, "fio_options": json.loads(template.fio_options), "created_at": template.created_at, "updated_at": template.updated_at}
