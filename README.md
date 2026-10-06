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

## 启动

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 培训证据组合（/api/evidence）

解决"学员请假缺课后仅凭考核通过就发证、线下补训材料无法对应原课次"的问题，建立以**培训期次锁定的规则版本**为基准的证据组合：

- **规则版本**：必修能力按版本管理；改版只产生新版本，新建期次/新报名才适用，已形成的组合与已发证快照不被重算覆盖。
- **每项必修能力由一条有效依据满足**：原课出勤（自动物化）/ 批准的替代课程 / 补训考核；重复登记被拒。
- **留痕**：缺课请假（原因、审批人、批准/驳回决定）与替代/补训审批全程记录。
- **考核前置核对**：安排考核或补考前逐项核对证据是否齐全，缺失项直接拦截（`GET .../volunteers/{id}/readiness` 查询还缺什么）。
- **查询**：一次补训替代了哪项要求（`GET .../evidences/by-assessment/{id}`）；发证瞬间冻结历史依据快照。
- **撤销与复核**：撤销错误证据只置"已撤销"并级联标记受影响考核、证书进入复核队列，从不物理删除既有成绩；复核可"维持"或"撤销（停用但留档）"。
