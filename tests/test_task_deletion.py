from types import SimpleNamespace

from fastapi import HTTPException

from app.api.routes import delete_task


class FakeQuery:
    def filter(self, *_):
        return self

    def delete(self, **_):
        return 1


class FakeSession:
    def __init__(self, task):
        self.task = task
        self.deleted = None
        self.committed = False

    def get(self, _, __):
        return self.task

    def query(self, _):
        return FakeQuery()

    def delete(self, task):
        self.deleted = task

    def add(self, _):
        pass

    def commit(self):
        self.committed = True

    def refresh(self, _):
        pass


def test_delete_completed_task_removes_task_and_result():
    task = SimpleNamespace(id=7, status="completed")
    db = FakeSession(task)
    response = delete_task(7, db)
    assert response.status_code == 204
    assert db.deleted is task
    assert db.committed is True


def test_delete_running_task_is_rejected():
    db = FakeSession(SimpleNamespace(id=7, status="running"))
    try:
        delete_task(7, db)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("running task deletion should be rejected")
