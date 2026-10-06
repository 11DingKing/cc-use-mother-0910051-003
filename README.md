# 青少年志愿讲解成长服务

本项目是使用 Python、FastAPI 与 SQLite 实现的服务端应用，覆盖志愿者、培训考核、服务记录、积分权益、监护关系和统计。它可在单个 Linux 应用容器内完成安装、测试、编译和接口验收，不依赖浏览器、外部数据库、缓存、消息队列或额外运行服务。

## 安装

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

## 测试

```bash
python3 -m pytest -q
```

## 编译

```bash
python3 -m compileall -q .
```

## 接口验收

```bash
python3 -c "from main import app; assert len(app.routes) > 5; print(len(app.routes))"
```

## 培训证据组合

针对"请假缺必修课、考核通过即发证、线下补训材料无法与原课次对应"的问题，系统建立了以**培训期次必修能力要求**为基准的证据组合（路由前缀 `/api/evidence`）：

- **必修要求与规则版本**：每期次可发布课程规则版本（`POST /api/evidence/batches/{id}/rule-versions`），必修要求关联到具体课次。改版只生成新版本，旧版本要求冻结不可改（返回 409），已发证人员的历史依据不重算。
- **三类证据满足一项要求**：原课出勤、批准的替代课程、补训考核。替代/补训证据必须挂接对应缺课审批留痕，否则拒绝登记。
- **缺课原因与审批留痕**：`POST /api/evidence/absences` 登记原因，`POST /api/evidence/absences/{id}/decision` 记录批准决定（批准替代课程须指定替代课次、批准补训考核、不予批准），不可重复审批。
- **考核前置核对**：安排考核/补考前自动同步出勤证据并逐项核对（`GET /api/evidence/assessments/prerequisite-check`），缺失必修要求时拒绝安排。
- **负责人查询**：某人距可考核还缺什么（`GET /api/evidence/volunteers/{id}/eligibility`）、一次补训/替代满足了哪项要求（`GET /api/evidence/requirements/{id}/evidences`）、考核的历史依据快照（`GET /api/assessments/{id}/evidence-basis`）。
- **撤销错误证据**：`POST /api/evidence/evidences/{id}/revoke` 只将证据置为已撤销，不删除成绩；引用该证据的考核与有效证书自动生成待复核任务（`GET /api/evidence/reviews`），复核可"维持"或"改判"。已有依据或已发证的考核拒绝直接删除。

## 启动

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
