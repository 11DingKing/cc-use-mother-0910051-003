"""培训证据组合端到端测试：以培训期次必修能力要求为基准的证据组合、缺课审批留痕、
考核前置核对、规则版本化、证据撤销触发复核（不删成绩）。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

if os.path.exists("redscarf.db"):
    os.remove("redscarf.db")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
print("=" * 60)
print("培训证据组合（必修能力依据）API 测试")
print("=" * 60)


def must(r, code=200, tag=""):
    assert r.status_code == code, f"[{tag}] 期望{code}，实际{r.status_code}: {r.text}"
    return r.json()


# ---------- 基础建档：主题 / 期次 / 3节课 / 规则v1（每节课对应一项必修能力） ----------
print("\n[1] 建档：主题、期次、课次、规则版本v1（R1-R3逐项对应课次）...")
school_id = must(client.get("/api/schools"), tag="学校列表")[0]["id"]

topic = must(client.post("/api/assessments/topics", json={
    "name": "证据组合测试主题", "pass_score": 60.0
}), tag="建主题")
topic_id = topic["id"]

batch = must(client.post("/api/trainings/batches", json={
    "name": "证据测试期次", "topic_id": topic_id,
    "min_attendance_rate": 60.0, "capacity": 10
}), tag="建期次")
batch_id = batch["id"]

session_ids = []
for i in range(1, 4):
    s = must(client.post("/api/trainings/sessions", json={
        "batch_id": batch_id, "session_no": i,
        "title": f"第{i}课", "session_date": f"2026-03-0{i}"
    }), tag=f"建课次{i}")
    session_ids.append(s["id"])
s1, s2, s3 = session_ids

v1 = must(client.post(f"/api/evidence/batches/{batch_id}/rule-versions", json={
    "change_summary": "初版：三节必修课对应三项能力",
    "published_by": "张主任",
    "requirements": [
        {"code": "R1", "name": "能力一", "session_ids": [s1]},
        {"code": "R2", "name": "能力二", "session_ids": [s2]},
        {"code": "R3", "name": "能力三", "session_ids": [s3]},
    ]
}), tag="发布规则v1")
assert v1["version_no"] == 1 and v1["is_current"] is True

reqs_v1 = must(client.get(f"/api/evidence/batches/{batch_id}/requirements"))
r1v1, r2v1, r3v1 = {r["code"]: r for r in reqs_v1}["R1"], \
                   {r["code"]: r for r in reqs_v1}["R2"], \
                   {r["code"]: r for r in reqs_v1}["R3"]
assert r1v1["session_ids"] == [s1]
print(f"  ✅ 规则v1 发布，必修要求 {[r['code'] for r in reqs_v1]}")


def make_volunteer(name):
    vid = must(client.post("/api/volunteers", json={
        "name": name, "school_id": school_id
    }), tag=f"建志愿者{name}")["id"]
    must(client.post(f"/api/volunteers/{vid}/review", json={"approved": True}), tag="审核通过")
    r = must(client.post("/api/trainings/enrollments/batch", json={
        "batch_id": batch_id, "volunteer_ids": [vid]
    }), tag="入班")
    assert vid in r["enrolled_ids"]
    en = must(client.get(f"/api/trainings/volunteers/{vid}/enrollments"))
    enrollment_id = [e["id"] for e in en if e["batch_id"] == batch_id][0]
    return vid, enrollment_id


def mark(vid, enrollment_id, attended_map):
    for sid in session_ids:
        must(client.post(f"/api/trainings/sessions/{sid}/attendances/init"), tag="初始化考勤")
    marks = [{
        "enrollment_id": enrollment_id, "session_id": sid, "volunteer_id": vid,
        "attended": att
    } for sid, att in attended_map.items()]
    must(client.post(f"/api/trainings/sessions/{s1}/attendances/batch-mark",
                     json=[m for m in marks if m["session_id"] == s1]))
    must(client.post(f"/api/trainings/sessions/{s2}/attendances/batch-mark",
                     json=[m for m in marks if m["session_id"] == s2]))
    must(client.post(f"/api/trainings/sessions/{s3}/attendances/batch-mark",
                     json=[m for m in marks if m["session_id"] == s3]))


def eligibility(vid):
    gaps = must(client.get(f"/api/evidence/volunteers/{vid}/eligibility",
                           params={"batch_id": batch_id}))
    return gaps[0]


# ---------- 志愿者甲：缺第2课，先验证缺口，再走"批准替代课程" ----------
print("\n[2] 甲：出勤第1、3课，缺第2课 → 查询距可考核还缺什么...")
vid, en_id = make_volunteer("学员甲")
mark(vid, en_id, {s1: True, s2: False, s3: True})
must(client.post(f"/api/evidence/enrollments/{en_id}/sync-attendance-evidence"), tag="汇总出勤证据")

gap = eligibility(vid)
assert gap["can_assess"] is False
assert gap["missing_count"] == 1
assert "R2" in gap["missing_requirements"][0]
sat = {r["code"]: r["satisfied"] for r in gap["requirements"]}
assert sat == {"R1": True, "R2": False, "R3": True}
print(f"  ✅ 缺口：{gap['missing_requirements']}")

must(client.post(f"/api/trainings/enrollments/{en_id}/promote-to-assessment"), tag="出勤率达标进入待考核")
r = client.post("/api/assessments/create-v2", json={
    "volunteer_id": vid, "topic_id": topic_id,
    "training_batch_id": batch_id, "assessment_date": "2026-04-01"
})
assert r.status_code == 400, f"证据不齐应拒考: {r.text}"
assert "R2" in r.json()["detail"]
print("  ✅ 前置证据不齐，考核安排被拒绝")

print("\n[3] 甲：缺课登记与审批留痕（病假→批准替代课程）...")
must(client.post("/api/evidence/absences", json={
    "enrollment_id": en_id, "session_id": s2,
    "reason": "病假", "reason_detail": "高烧39度", "evidence_note": "病历照片已交"
}), tag="缺课登记")
dup = client.post("/api/evidence/absences", json={
    "enrollment_id": en_id, "session_id": s2, "reason": "病假"
})
assert dup.status_code == 400
print("  ✅ 缺课原因留痕，重复登记被拒绝")

# 替代课次放在专门的补训专场，避免与原期次课次混淆
sub_batch = must(client.post("/api/trainings/batches", json={
    "name": "补训专场", "topic_id": topic_id, "min_attendance_rate": 0.0, "capacity": 10
}))
s_sub = must(client.post("/api/trainings/sessions", json={
    "batch_id": sub_batch["id"], "session_no": 1,
    "title": "第2课补训", "session_date": "2026-03-15"
}))["id"]
must(client.post("/api/trainings/enrollments/batch", json={
    "batch_id": sub_batch["id"], "volunteer_ids": [vid]
}))
sub_en_id = [e["id"] for e in must(client.get(f"/api/trainings/volunteers/{vid}/enrollments"))
             if e["batch_id"] == sub_batch["id"]][0]
must(client.post(f"/api/trainings/sessions/{s_sub}/attendances/init"))
must(client.post(f"/api/trainings/sessions/{s_sub}/attendances/batch-mark", json=[{
    "enrollment_id": sub_en_id, "session_id": s_sub, "volunteer_id": vid, "attended": True
}]))

absence = must(client.get(f"/api/evidence/enrollments/{en_id}/absences"))[0]
absence_id = absence["id"]
bad = client.post(f"/api/evidence/absences/{absence_id}/decision", json={
    "decision": "批准替代课程", "decided_by": "王老师"
})
assert bad.status_code == 400 and "替代课次" in bad.json()["detail"]
must(client.post(f"/api/evidence/absences/{absence_id}/decision", json={
    "decision": "批准替代课程", "decided_by": "王老师",
    "substitute_session_id": s_sub, "decision_comment": "同意参加补训专场第2课"
}), tag="批准替代课程")
second = client.post(f"/api/evidence/absences/{absence_id}/decision", json={
    "decision": "不予批准"
})
assert second.status_code == 400
print("  ✅ 审批决定留痕：必须指定替代课次，且不可重复审批")

must(client.post(f"/api/evidence/enrollments/{en_id}/sync-attendance-evidence"), tag="汇总替代证据")
gap = eligibility(vid)
assert gap["can_assess"] is True, gap
r2_evs = must(client.get(f"/api/evidence/requirements/{r2v1['id']}/evidences"))
sub_ev = [e for e in r2_evs if e["evidence_type"] == "替代课程"]
assert len(sub_ev) == 1 and sub_ev[0]["substitute_session_id"] == s_sub
print(f"  ✅ 一次替代课程满足了要求：GET 要求R2证据 → {sub_ev[0]['evidence_type']}(证据#{sub_ev[0]['id']})")

print("\n[4] 甲：前置证据齐全 → 安排考核、评分通过发证，并固化依据快照...")
a = must(client.post("/api/assessments/create-v2", json={
    "volunteer_id": vid, "topic_id": topic_id,
    "training_batch_id": batch_id, "assessment_date": "2026-04-02"
}), tag="安排考核")
assessment_id = a["id"]
criterion = must(client.post("/api/assessments/criteria", json={
    "topic_id": topic_id, "name": "综合讲解", "max_score": 100.0
}))
must(client.post(f"/api/assessments/{assessment_id}/submit-scores", json={
    "scores": [{"assessment_id": assessment_id, "criterion_id": criterion["id"], "score": 85.0}],
    "examiner": "考评组"
}), tag="评分通过")

basis = must(client.get(f"/api/assessments/{assessment_id}/evidence-basis"))
assert basis["basis_count"] == 3
types = sorted(b["evidence_type"] for b in basis["basis"])
assert types == ["原课出勤", "原课出勤", "替代课程"], types
assert all(b["evidence_status"] == "有效" for b in basis["basis"])
cert = must(client.get(f"/api/assessments/volunteers/{vid}/certifications"))
assert len(cert) == 1 and cert[0]["is_active"]
print(f"  ✅ 已发证 {cert[0]['certificate_no']}，历史依据快照 {basis['basis_count']} 条")

blocked_delete = client.delete(f"/api/assessments/{assessment_id}")
assert blocked_delete.status_code == 400 and "复核" in blocked_delete.json()["detail"]
print("  ✅ 已有依据/已发证的考核不能直接删除，引导走撤销→复核")

# ---------- 规则改版：v2新增R4，旧版本冻结、甲的证书历史依据不重算 ----------
print("\n[5] 规则改版v2（新增R4）：只影响之后形成的组合...")
s4 = must(client.post("/api/trainings/sessions", json={
    "batch_id": batch_id, "session_no": 4,
    "title": "第4课", "session_date": "2026-03-08"
}))["id"]
must(client.post(f"/api/evidence/batches/{batch_id}/rule-versions", json={
    "change_summary": "新增第四项必修能力",
    "requirements": [
        {"code": "R1", "name": "能力一", "session_ids": [s1]},
        {"code": "R2", "name": "能力二", "session_ids": [s2]},
        {"code": "R3", "name": "能力三", "session_ids": [s3]},
        {"code": "R4", "name": "能力四", "session_ids": [s4]},
    ]
}), tag="发布规则v2")

history = must(client.get(f"/api/evidence/batches/{batch_id}/requirements",
                          params={"include_history": "true"}))
assert len(history) == 7 and {r["code"] for r in history[-4:]} == {"R1", "R2", "R3", "R4"}
reqs_v2 = must(client.get(f"/api/evidence/batches/{batch_id}/requirements"))
assert len(reqs_v2) == 4
r4v2 = [r for r in reqs_v2 if r["code"] == "R4"][0]

frozen = client.put(f"/api/evidence/requirements/{r1v1['id']}", json={"name": "篡改历史"})
assert frozen.status_code == 409
print("  ✅ v1冻结不可改；当前要求为v2的4项")

# 旧证据隶属v1行：按v2核对时R1-R3需重新形成（出勤事实不变，重新同步即可）
must(client.post(f"/api/evidence/enrollments/{en_id}/sync-attendance-evidence"), tag="v2下重新汇总出勤")
must(client.post(f"/api/evidence/enrollments/{en_id}/sync-attendance-evidence"), tag="重复汇总幂等")
gap = eligibility(vid)
assert not gap["can_assess"] and "R4" in gap["missing_requirements"][0]
basis2 = must(client.get(f"/api/assessments/{assessment_id}/evidence-basis"))
assert basis2["basis_count"] == 3 and all(
    b["requirement_id"] in {r1v1["id"], r2v1["id"], r3v1["id"]} for b in basis2["basis"]
)
cert_after = must(client.get(f"/api/assessments/volunteers/{vid}/certifications"))
assert len(cert_after) == 1
print("  ✅ v2下甲缺R4；已发证证书与考核依据快照未被重算覆盖")

# ---------- 撤销错误证据 → 考核与证书进入复核，成绩不删除 ----------
print("\n[6] 撤销甲的替代课程证据（历史依据之一）→ 生成复核任务，成绩保留...")
rev = must(client.post(f"/api/evidence/evidences/{sub_ev[0]['id']}/revoke", json={
    "revoked_by": "督导员", "revoke_reason": "发现替代课签到代签"
}), tag="撤销证据")
assert rev["review_count"] == 2, rev
reviews = must(client.get("/api/evidence/reviews", params={"status": "待复核"}))
targets = [r for r in reviews if r["evidence_id"] == sub_ev[0]["id"]]
assert len(targets) == 2
assert {r["assessment_id"] for r in targets} == {assessment_id}
assert any(r["certification_id"] == cert[0]["id"] for r in targets)
kept = must(client.get(f"/api/assessments/{assessment_id}"))
assert kept["score"] == 85.0 and kept["result"] == "通过"
print(f"  ✅ 考核成绩 {kept['score']} 分保留；待复核 {len(targets)} 项（考核+证书）")

handled = must(client.post(f"/api/evidence/reviews/{targets[0]['id']}/handle", json={
    "status": "复核维持", "handled_by": "培训负责人",
    "handle_comment": "经面谈确认学员实际掌握该能力，维持原成绩"
}), tag="复核维持")
assert handled["status"] == "复核维持"
again = client.post(f"/api/evidence/reviews/{targets[0]['id']}/handle", json={"status": "复核改判"})
assert again.status_code == 400
print("  ✅ 复核结论已记录，不可重复处理")

# ---------- 志愿者乙：缺第2课 → 批准补训考核 → 排期核对放行 → 通过自动形成补训证据 ----------
print("\n[7] 乙：病假缺第2课，批准补训考核，安排补考前核对前置证据...")
vid2, en2 = make_volunteer("学员乙")
# v2已新增第4课，乙正常出勤第1、3、4课，仅缺第2课
mark(vid2, en2, {s1: True, s2: False, s3: True})
must(client.post(f"/api/trainings/sessions/{s4}/attendances/init"))
must(client.post(f"/api/trainings/sessions/{s4}/attendances/batch-mark", json=[{
    "enrollment_id": en2, "session_id": s4, "volunteer_id": vid2, "attended": True
}]))
must(client.post(f"/api/evidence/enrollments/{en2}/sync-attendance-evidence"))
ab2 = must(client.post("/api/evidence/absences", json={
    "enrollment_id": en2, "session_id": s2, "reason": "病假"
}), tag="乙缺课登记")

r2v2 = [r for r in reqs_v2 if r["code"] == "R2"][0]
# 无审批留痕时，手工补训证据与替代证据都不允许登记
no_approval_sub = client.post("/api/evidence/evidences", json={
    "requirement_id": r2v2["id"], "volunteer_id": vid2,
    "evidence_type": "替代课程", "absence_id": ab2["id"]
})
assert no_approval_sub.status_code == 400
no_approval_makeup = client.post("/api/evidence/evidences", json={
    "requirement_id": r2v2["id"], "volunteer_id": vid2,
    "evidence_type": "补训考核", "absence_id": ab2["id"], "assessment_id": assessment_id
})
assert no_approval_makeup.status_code == 400
print("  ✅ 替代/补训证据无审批留痕一律拒绝登记")

must(client.post(f"/api/evidence/absences/{ab2['id']}/decision", json={
    "decision": "批准补训考核", "decided_by": "王老师", "decision_comment": "准予补训后补考"
}), tag="乙批准补训考核")
gap = eligibility(vid2)
r2_status = [r for r in gap["requirements"] if r["code"] == "R2"][0]
assert gap["can_assess"] is True
assert r2_status["satisfied"] is False and r2_status["has_makeup_approval"] is True
print("  ✅ 补训在途：可安排考核，但R2在补训结果形成前仍标记未最终满足")

must(client.post(f"/api/trainings/enrollments/{en2}/promote-to-assessment"))
a2 = must(client.post("/api/assessments/create-v2", json={
    "volunteer_id": vid2, "topic_id": topic_id,
    "training_batch_id": batch_id, "assessment_date": "2026-04-10"
}), tag="乙安排考核")
must(client.post(f"/api/assessments/{a2['id']}/submit-scores", json={
    "scores": [{"assessment_id": a2["id"], "criterion_id": criterion["id"], "score": 78.0}],
}), tag="乙考核通过")
r2_evs_v2 = must(client.get(f"/api/evidence/requirements/{[r for r in reqs_v2 if r['code']=='R2'][0]['id']}/evidences"))
makeup_ev = [e for e in r2_evs_v2 if e["volunteer_id"] == vid2 and e["evidence_type"] == "补训考核"]
assert len(makeup_ev) == 1 and makeup_ev[0]["assessment_id"] == a2["id"]
assert makeup_ev[0]["absence_id"] == ab2["id"]
assert eligibility(vid2)["can_assess"] is True
print(f"  ✅ 考核通过自动形成补训考核证据（证据#{makeup_ev[0]['id']}，关联缺课审批#{ab2['id']}）")

# 撤销补训证据 → 乙的考核与证书同样进入复核
rev2 = must(client.post(f"/api/evidence/evidences/{makeup_ev[0]['id']}/revoke", json={
    "revoke_reason": "补训材料无法与原课次对应"
}))
assert rev2["review_count"] == 2
kept2 = must(client.get(f"/api/assessments/{a2['id']}"))
assert kept2["result"] == "通过" and kept2["score"] == 78.0
print("  ✅ 撤销补训证据：成绩不删除，考核与证书进入复核")

# ---------- 志愿者丙：缺课且审批未通过 → 前置核对拦截 ----------
print("\n[8] 丙：缺第2课，审批不予批准 → 不能安排考核...")
vid3, en3 = make_volunteer("学员丙")
mark(vid3, en3, {s1: True, s2: False, s3: True})
must(client.post(f"/api/trainings/sessions/{s4}/attendances/init"))
must(client.post(f"/api/trainings/sessions/{s4}/attendances/batch-mark", json=[{
    "enrollment_id": en3, "session_id": s4, "volunteer_id": vid3, "attended": True
}]))
must(client.post(f"/api/evidence/enrollments/{en3}/sync-attendance-evidence"))
ab3 = must(client.post("/api/evidence/absences", json={
    "enrollment_id": en3, "session_id": s2, "reason": "事假"
}))
must(client.post(f"/api/evidence/absences/{ab3['id']}/decision", json={
    "decision": "不予批准", "decided_by": "王老师", "decision_comment": "未提供有效证明"
}))
pre = must(client.get("/api/evidence/assessments/prerequisite-check", params={
    "volunteer_id": vid3, "training_batch_id": batch_id
}))
assert pre["prerequisites_complete"] is False
assert any("R2" in m for g in pre["gaps"] for m in g["missing_requirements"])
must(client.post(f"/api/trainings/enrollments/{en3}/promote-to-assessment"))
blocked = client.post("/api/assessments/create-v2", json={
    "volunteer_id": vid3, "topic_id": topic_id,
    "training_batch_id": batch_id, "assessment_date": "2026-04-12"
})
assert blocked.status_code == 400
print("  ✅ 前置核对明确列出缺失R2，考核安排被拦截")

print("\n" + "=" * 60)
print("🎉 培训证据组合全部场景测试通过！")
print("=" * 60)
