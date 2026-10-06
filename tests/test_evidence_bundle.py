"""
证据组合（Evidence Bundle）端到端测试。

覆盖：
1. 查询某人距离可考核还缺什么（readiness）
2. 每项必修能力由 原课出勤 / 批准的替代课程 / 补训考核 满足
3. 缺课原因与审批决定全程留痕
4. 安排考核/补考前核对前置证据是否齐全
5. 规则改版只影响之后形成的组合，已发证历史依据快照不被重算覆盖
6. 一次补训替代了哪项要求（按考核反查）
7. 撤销错误证据 → 关联考核/证书进入复核，既有成绩不被物理删除
"""
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# 使用独立临时数据库，避免与 test_api.py 子进程反复重建 redscarf.db 相互干扰。
# 必须在导入 main 之前替换 database 模块的引擎/Session 工厂。
import database  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_TMPDIR = tempfile.mkdtemp(prefix="evidence_test_")
_TEST_ENGINE = create_engine(
    f"sqlite:///{_TMPDIR}/evidence.db",
    connect_args={"check_same_thread": False},
)
database.engine = _TEST_ENGINE
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


def _post(url, **kw):
    r = client.post(url, **kw)
    assert r.status_code == 200, f"POST {url} -> {r.status_code}: {r.text}"
    return r.json()


def _get(url, **kw):
    r = client.get(url, **kw)
    assert r.status_code == 200, f"GET {url} -> {r.status_code}: {r.text}"
    return r.json()


def make_volunteer(name):
    v = _post("/api/volunteers/", json={
        "name": name, "gender": "女", "school_id": 1, "grade": "五年级",
        "parent_name": "家长", "parent_phone": "1390000" + name[-3:].zfill(3),
    })
    _post(f"/api/volunteers/{v['id']}/review", json={"approved": True})
    return v


def make_batch(name, topic_id):
    return _post("/api/trainings/batches", json={
        "name": name, "topic_id": topic_id,
        "min_attendance_rate": 80.0, "capacity": 30,
    })


def add_session(batch_id, no, title):
    return _post("/api/trainings/sessions", json={
        "batch_id": batch_id, "session_no": no, "title": title,
        "session_date": "2026-03-0" + str(no), "start_time": "09:00", "end_time": "10:00",
    })


def enroll(volunteer_id, batch_id):
    r = _post("/api/trainings/enrollments/batch",
              json={"batch_id": batch_id, "volunteer_ids": [volunteer_id]})
    assert volunteer_id in r["enrolled_ids"], r
    en = _get(f"/api/trainings/volunteers/{volunteer_id}/enrollments")
    return [e for e in en if e["batch_id"] == batch_id][0]


def mark_attended(session_id, enrollment_id, volunteer_id):
    _post(f"/api/trainings/sessions/{session_id}/attendances/init")
    _post(f"/api/trainings/sessions/{session_id}/attendances/batch-mark", json=[{
        "enrollment_id": enrollment_id, "session_id": session_id,
        "volunteer_id": volunteer_id, "attended": True,
    }])


def leave_approved(enrollment_id, session_id, reason):
    leave = _post("/api/evidence/leaves", json={
        "enrollment_id": enrollment_id, "session_id": session_id,
        "reason_category": "病假", "reason_detail": reason,
    })
    assert leave["status"] == "待审批"
    out = _post(f"/api/evidence/leaves/{leave['id']}/decision", json={
        "approved": True, "approver": "张主任", "approval_comment": "情况属实，同意请假",
    })
    assert out["status"] == "已批准" and out["approver"] == "张主任"
    return out


# ---------------------------------------------------------------------------

def test_full_evidence_bundle_lifecycle():
    topics = _get("/api/assessments/topics")
    topic_id = topics[0]["id"]

    volunteer = make_volunteer("证据测试学员甲")
    vid = volunteer["id"]

    batch = make_batch("证据组合测试期次", topic_id)
    bid = batch["id"]
    s1 = add_session(bid, 1, "必修课A")
    s2 = add_session(bid, 2, "必修课B")
    s3 = add_session(bid, 3, "必修课C")

    # 报名时按课次冻结 v1 初始规则（3 项必修能力），并把课次对应到能力
    en = enroll(vid, bid)
    eid = en["id"]

    # ---- 1. 初始：3 项全缺，不可考核 ----
    bundle = _get(f"/api/evidence/volunteers/{vid}/readiness?batch_id={bid}")[0]
    assert bundle["required_total"] == 3
    assert bundle["missing_count"] == 3
    assert bundle["ready_for_assessment"] is False
    caps = {r["name"]: r for r in bundle["requirements"]}
    v1_id = bundle["rule_version_id"]

    # ---- 2. 必修课A：原课出勤满足 ----
    mark_attended(s1["id"], eid, vid)
    bundle = _get(f"/api/evidence/enrollments/{eid}/bundle")
    item_a = [r for r in bundle["requirements"] if r["name"] == "必修课A"][0]
    assert item_a["satisfied"] is True
    assert item_a["evidence_type"] == "原课出勤"

    # ---- 3. 必修课B：批准请假 + 补训考核满足 ----
    leave_b = leave_approved(eid, s2["id"], "高烧住院，无法到校")

    # 未批准的请假不能安排替代/补训
    leave_pending = _post("/api/evidence/leaves", json={
        "enrollment_id": eid, "session_id": s3["id"],
        "reason_category": "事假", "reason_detail": "占位",
    })
    r = client.post("/api/evidence/substitute-approvals", json={
        "enrollment_id": eid,
        "requirement_id": caps["必修课C"]["requirement_id"],
        "substitute_type": "替代课程", "leave_request_id": leave_pending["id"],
    })
    assert r.status_code == 400

    # 记录一场补训考核（补考形式的补训）并通过
    makeup = _post("/api/assessments/", json={
        "volunteer_id": vid, "assessment_date": "2026-03-08",
        "topic": "必修课B补训考核", "score": 88.0, "result": "通过",
    })
    appr_b = _post("/api/evidence/substitute-approvals", json={
        "enrollment_id": eid,
        "requirement_id": caps["必修课B"]["requirement_id"],
        "substitute_type": "补训考核", "leave_request_id": leave_b["id"],
        "approver": "教务处李老师", "comment": "同意参加补训考核",
    })
    ev_b = _post("/api/evidence/evidences", json={
        "enrollment_id": eid, "requirement_id": caps["必修课B"]["requirement_id"],
        "evidence_type": "补训考核", "assessment_id": makeup["id"],
        "approval_id": appr_b["id"], "leave_request_id": leave_b["id"],
    })
    assert ev_b["status"] == "有效"

    # 一次补训替代了哪项要求：按补训考核反查
    replaced = _get(f"/api/evidence/evidences/by-assessment/{makeup['id']}")
    assert len(replaced) == 1 and replaced[0]["id"] == ev_b["id"]

    # 未通过的补训考核不能作为依据
    makeup_fail = _post("/api/assessments/", json={
        "volunteer_id": vid, "assessment_date": "2026-03-09",
        "topic": "无效补训", "score": 20.0, "result": "未通过",
    })
    r = client.post("/api/evidence/evidences", json={
        "enrollment_id": eid, "requirement_id": caps["必修课A"]["requirement_id"],
        "evidence_type": "补训考核", "assessment_id": makeup_fail["id"],
        "approval_id": appr_b["id"],
    })
    assert r.status_code == 400

    # ---- 4. 必修课C：批准的替代课程满足（另一期次线下补训课）----
    batch2 = make_batch("周末补训班", topic_id)
    sub_session = add_session(batch2["id"], 1, "补训专场-必修C")
    en2 = enroll(vid, batch2["id"])
    mark_attended(sub_session["id"], en2["id"], vid)
    leave_c = leave_approved(eid, s3["id"], "家中急事")
    appr_c = _post("/api/evidence/substitute-approvals", json={
        "enrollment_id": eid,
        "requirement_id": caps["必修课C"]["requirement_id"],
        "substitute_type": "替代课程",
        "substitute_session_id": sub_session["id"],
        "leave_request_id": leave_c["id"],
        "approver": "教务处李老师",
    })
    ev_c = _post("/api/evidence/evidences", json={
        "enrollment_id": eid, "requirement_id": caps["必修课C"]["requirement_id"],
        "evidence_type": "替代课程", "approval_id": appr_c["id"],
    })
    assert ev_c["evidence_type"] == "替代课程"

    # 一项必修能力只能有一条有效依据：重复登记被拒
    r = client.post("/api/evidence/evidences", json={
        "enrollment_id": eid, "requirement_id": caps["必修课C"]["requirement_id"],
        "evidence_type": "替代课程", "approval_id": appr_c["id"],
    })
    assert r.status_code == 400

    # ---- 5. 证据齐全 ----
    bundle = _get(f"/api/evidence/volunteers/{vid}/readiness?batch_id={bid}")[0]
    assert bundle["satisfied_count"] == 3
    assert bundle["missing_count"] == 0
    assert bundle["ready_for_assessment"] is True

    # ---- 6. 前置证据不齐全时，安排考核被拦截 ----
    v2_vol = make_volunteer("证据测试学员乙")
    en_block = enroll(v2_vol["id"], bid)
    # 直接置为待考核，绕过旧出勤率逻辑以验证证据闸口
    r = client.put(f"/api/volunteers/{v2_vol['id']}", json={"status": "待考核"})
    assert r.status_code == 200
    r = client.post("/api/assessments/create-v2", json={
        "volunteer_id": v2_vol["id"], "topic_id": topic_id,
        "training_batch_id": bid, "enrollment_id": en_block["id"],
        "assessment_date": "2026-03-10",
    })
    assert r.status_code == 400 and "前置培训证据不齐全" in r.json()["detail"]

    # ---- 7. 证据齐全 → 正式考核，前置证据清单被固化 ----
    _post(f"/api/trainings/enrollments/{en2['id']}/promote-to-assessment")
    assessment = _post("/api/assessments/create-v2", json={
        "volunteer_id": vid, "topic_id": topic_id,
        "training_batch_id": bid, "enrollment_id": eid,
        "assessment_date": "2026-03-11", "examiner": "考评组",
    })
    aid = assessment["id"]
    links = _get(f"/api/evidence/assessments/{aid}/evidence-links")
    assert len(links) == 3
    assert {l["requirement_name"] for l in links} == {"必修课A", "必修课B", "必修课C"}

    # ---- 8. 评分通过 → 发证，冻结历史依据快照 ----
    criteria = _get(f"/api/assessments/topics/{topic_id}/criteria")
    scores = [
        {"assessment_id": aid, "criterion_id": c["id"],
         "score": c["max_score"] * 0.9, "comments": "良好"}
        for c in criteria
    ]
    _post(f"/api/assessments/{aid}/submit-scores", json={"scores": scores})
    certs = _get(f"/api/assessments/volunteers/{vid}/certifications")
    cert = [c for c in certs if c["topic_id"] == topic_id and c["is_active"]][0]
    assert cert["rule_version_id"] == v1_id
    snapshot = _get(f"/api/evidence/certifications/{cert['id']}/snapshot")
    assert snapshot is not None
    import json
    frozen = json.loads(snapshot["bundle_json"])
    frozen_evidence_ids = {r["evidence_id"] for r in frozen["requirements"]}
    assert frozen["rule_version_id"] == v1_id
    assert len(frozen_evidence_ids) == 3

    # ---- 9. 规则改版为 v2（新增第 4 项必修）----
    r = client.post("/api/evidence/rule-versions", json={
        "topic_id": topic_id, "name": "2026修订版规则",
        "change_note": "新增应急处理必修能力",
        "capabilities": [
            {"code": "C01", "name": "必修课A"},
            {"code": "C02", "name": "必修课B"},
            {"code": "C03", "name": "必修课C"},
            {"code": "C04", "name": "应急处理", "is_required": True},
        ],
        "publish": True,
    })
    assert r.status_code == 200, r.text
    v2 = r.json()
    assert v2["version_no"] >= 2 and len(v2["capabilities"]) == 4

    # 已形成的历史组合仍按 v1 核对，不被改版重算
    old_bundle = _get(f"/api/evidence/enrollments/{eid}/bundle")
    assert old_bundle["rule_version_id"] == v1_id
    assert old_bundle["required_total"] == 3
    assert old_bundle["ready_for_assessment"] is True

    # 改版后新形成的组合才适用 v2
    batch3 = make_batch("改版后新期次", topic_id)
    assert batch3["rule_version_id"] == v2["id"]
    v3_vol = make_volunteer("证据测试学员丙")
    en3 = enroll(v3_vol["id"], batch3["id"])
    new_bundle = _get(f"/api/evidence/enrollments/{en3['id']}/bundle")
    assert new_bundle["rule_version_id"] == v2["id"]
    assert new_bundle["required_total"] == 4

    # ---- 10. 撤销错误证据：成绩不删除，考核与证书进入复核 ----
    void_result = _post(f"/api/evidence/evidences/{ev_b['id']}/void",
                        json={"reason": "补训考核系他人代考，证据无效", "operator": "督导员"})
    assert void_result["status"] == "已撤销"
    assert aid in void_result["affected_assessments"]
    assert makeup["id"] in void_result["affected_assessments"]
    assert cert["id"] in void_result["certifications_in_review"]

    # 证据记录仍在（非物理删除），只是已撤销
    ev_b_after = _get(f"/api/evidence/evidences/{ev_b['id']}")
    assert ev_b_after["status"] == "已撤销" and ev_b_after["void_reason"]

    # 正式考核成绩保留，但进入待复核
    a_after = _get(f"/api/assessments/{aid}")
    assert a_after["review_status"] == "待复核"
    assert a_after["score"] is not None and a_after["score"] > 0

    # 证书进入复核队列
    review_certs = _get("/api/evidence/reviews/certifications")
    assert any(c["certification_id"] == cert["id"] for c in review_certs)
    review_assessments = _get("/api/evidence/reviews/assessments")
    assert aid in [a["assessment_id"] for a in review_assessments]

    # 撤销后该必修项重新变为缺失，但不能靠删成绩解决
    bundle = _get(f"/api/evidence/enrollments/{eid}/bundle")
    item_b = [r for r in bundle["requirements"] if r["name"] == "必修课B"][0]
    assert item_b["satisfied"] is False and bundle["missing_count"] == 1

    # 复核结论：考核维持（成绩保留）；证书维持有效，历史快照原样不变
    resolved_a = _post(f"/api/evidence/reviews/assessments/{aid}",
                       json={"maintain": True, "reason": "综合其他材料，成绩有效"})
    assert resolved_a["review_status"] == "复核维持" and resolved_a["score_kept"] is not None
    resolved_c = _post(f"/api/evidence/reviews/certifications/{cert['id']}",
                       json={"maintain": True, "reason": "学员已重新补训，证书维持"})
    assert resolved_c["review_status"] == "复核维持" and resolved_c["is_active"] is True

    snapshot_after = _get(f"/api/evidence/certifications/{cert['id']}/snapshot")
    frozen_after = json.loads(snapshot_after["bundle_json"])
    assert {r["evidence_id"] for r in frozen_after["requirements"]} == frozen_evidence_ids

    # 复核撤销路径：另一场景，证书复核不维持 → 停用但记录保留
    makeup2 = _post("/api/assessments/", json={
        "volunteer_id": vid, "assessment_date": "2026-03-12",
        "topic": "二次补训", "score": 90.0, "result": "通过",
    })
    appr_b2 = _post("/api/evidence/substitute-approvals", json={
        "enrollment_id": eid, "requirement_id": caps["必修课B"]["requirement_id"],
        "substitute_type": "补训考核", "leave_request_id": leave_b["id"],
    })
    ev_b2 = _post("/api/evidence/evidences", json={
        "enrollment_id": eid, "requirement_id": caps["必修课B"]["requirement_id"],
        "evidence_type": "补训考核", "assessment_id": makeup2["id"],
        "approval_id": appr_b2["id"],
    })
    _post(f"/api/evidence/evidences/{ev_c['id']}/void", json={"reason": "替代课程签到有误"})
    c_rev = _post(f"/api/evidence/reviews/certifications/{cert['id']}",
                  json={"maintain": False, "reason": "替代依据不实"})
    assert c_rev["review_status"] == "复核撤销" and c_rev["is_active"] is False
    # 证书记录与快照仍可查
    assert _get(f"/api/evidence/certifications/{cert['id']}/snapshot") is not None


def test_leave_rejection_is_traced():
    """请假被驳回同样留痕，且不能据此安排替代。"""
    topics = _get("/api/assessments/topics")
    v = make_volunteer("证据测试学员丁")
    b = make_batch("请假驳回测试期次", topics[0]["id"])
    s = add_session(b["id"], 1, "必修课X")
    en = enroll(v["id"], b["id"])
    bundle = _get(f"/api/evidence/enrollments/{en['id']}/bundle")
    cap_id = bundle["requirements"][0]["requirement_id"]

    leave = _post("/api/evidence/leaves", json={
        "enrollment_id": en["id"], "session_id": s["id"],
        "reason_category": "事假", "reason_detail": "出游",
    })
    decided = _post(f"/api/evidence/leaves/{leave['id']}/decision", json={
        "approved": False, "approver": "张主任", "approval_comment": "非正当理由",
    })
    assert decided["status"] == "已驳回"
    leaves = _get(f"/api/evidence/enrollments/{en['id']}/leaves")
    assert any(l["status"] == "已驳回" and l["approval_comment"] == "非正当理由" for l in leaves)

    r = client.post("/api/evidence/substitute-approvals", json={
        "enrollment_id": en["id"], "requirement_id": cap_id,
        "substitute_type": "补训考核", "leave_request_id": leave["id"],
    })
    assert r.status_code == 400
