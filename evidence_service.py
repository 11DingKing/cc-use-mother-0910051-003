"""
证据组合（Evidence Bundle）核心业务逻辑。

以培训期次锁定的规则版本为基准，为每名学员逐项核对必修能力的满足依据：
原课出勤 / 批准的替代课程 / 补训考核。规则改版只产生新版本，
已形成的组合（报名时锁定版本）与已发证快照不被重算覆盖。
"""
from datetime import datetime
import json
from typing import Optional, List, Dict, Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
import schemas


# --------------------------------------------------------------------
# 规则版本
# --------------------------------------------------------------------

def get_published_rule_version(db: Session, topic_id: Optional[int],
                               before: Optional[datetime] = None) -> Optional[models.RuleVersion]:
    """取该主题最新发布版本；before 给定时只取在该时刻之前已发布的版本，
    以保证规则改版只影响改版之后形成的组合。"""
    query = db.query(models.RuleVersion).filter(
        models.RuleVersion.status == models.RuleVersionStatus.PUBLISHED
    )
    if topic_id is not None:
        query = query.filter(models.RuleVersion.topic_id == topic_id)
    if before is not None:
        query = query.filter(
            (models.RuleVersion.published_at.is_(None)) |
            (models.RuleVersion.published_at <= before)
        )
    return query.order_by(
        models.RuleVersion.version_no.desc(), models.RuleVersion.id.desc()
    ).first()


def _provision_baseline_version(db: Session, batch: models.TrainingBatch) -> models.RuleVersion:
    """
    为没有显式规则版本的历史期次，按其既有课次冻结一版"初始规则"。
    一次性、幂等：生成后即锁定，之后改版只会产生新版本，不影响历史组合。
    """
    next_no = (db.query(models.RuleVersion).filter(
        models.RuleVersion.topic_id == batch.topic_id
    ).count() or 0) + 1

    version = models.RuleVersion(
        topic_id=batch.topic_id,
        version_no=next_no,
        name=f"{batch.name}-初始规则",
        status=models.RuleVersionStatus.PUBLISHED,
        change_note="按期次既有必修课次自动生成的初始规则版本（历史数据冻结）",
        published_at=datetime.utcnow(),
    )
    db.add(version)
    db.flush()

    sessions = sorted(batch.sessions, key=lambda s: s.session_no)
    for idx, session in enumerate(sessions):
        cap = models.RequiredCapability(
            rule_version_id=version.id,
            code=f"C{idx + 1:02d}",
            name=session.title,
            description=session.content,
            is_required=True,
            sort_order=idx,
        )
        db.add(cap)
        db.flush()
        if session.requirement_id is None:
            session.requirement_id = cap.id
    batch.rule_version_id = version.id
    db.flush()
    return version


def effective_rule_version(db: Session, enrollment: models.Enrollment) -> Optional[models.RuleVersion]:
    """
    组合所依据的规则版本，优先级：
    报名锁定版本 > 期次版本 > 该主题最新发布版本 > 按期次课次冻结初始版本。
    """
    if enrollment.rule_version_id:
        return db.get(models.RuleVersion, enrollment.rule_version_id)

    batch = enrollment.batch
    if batch is None:
        return None
    if batch.rule_version_id:
        return db.get(models.RuleVersion, batch.rule_version_id)

    published = get_published_rule_version(db, batch.topic_id)
    if published:
        # 新报名一旦开始形成组合，即锁定当时发布版本
        enrollment.rule_version_id = published.id
        db.flush()
        return published

    if batch.sessions:
        version = _provision_baseline_version(db, batch)
        enrollment.rule_version_id = version.id
        db.flush()
        return version
    return None


# --------------------------------------------------------------------
# 证据归集
# --------------------------------------------------------------------

def _original_session_for_requirement(db: Session, batch_id: int, requirement_id: int):
    return db.query(models.TrainingSession).filter(
        models.TrainingSession.batch_id == batch_id,
        models.TrainingSession.requirement_id == requirement_id,
    ).first()


def sync_original_attendance_evidence(
    db: Session, enrollment: models.Enrollment, version: models.RuleVersion
) -> None:
    """
    将已签到的原课出勤物化为 ORIGINAL_ATTENDANCE 证据。
    已被人工撤销（VOID）的证据不会自动复活。
    """
    for cap in version.capabilities:
        if not cap.is_required:
            continue
        session = _original_session_for_requirement(db, enrollment.batch_id, cap.id)
        if not session:
            continue
        att = db.query(models.SessionAttendance).filter(
            models.SessionAttendance.enrollment_id == enrollment.id,
            models.SessionAttendance.session_id == session.id,
        ).first()
        if not att or not att.attended:
            continue

        existing = db.query(models.RequirementEvidence).filter(
            models.RequirementEvidence.enrollment_id == enrollment.id,
            models.RequirementEvidence.requirement_id == cap.id,
            models.RequirementEvidence.evidence_type == models.RequirementEvidenceType.ORIGINAL_ATTENDANCE,
        ).first()
        if existing is None:
            db.add(models.RequirementEvidence(
                enrollment_id=enrollment.id,
                requirement_id=cap.id,
                volunteer_id=enrollment.volunteer_id,
                evidence_type=models.RequirementEvidenceType.ORIGINAL_ATTENDANCE,
                attendance_id=att.id,
                detail=f"原课《{session.title}》正常出勤",
            ))
    db.flush()


def _latest_leave(db: Session, enrollment_id: int, session_id: Optional[int]):
    if not session_id:
        return None
    return db.query(models.LeaveRequest).filter(
        models.LeaveRequest.enrollment_id == enrollment_id,
        models.LeaveRequest.session_id == session_id,
    ).order_by(models.LeaveRequest.created_at.desc()).first()


def _valid_evidence_for(db: Session, enrollment_id: int, requirement_id: int):
    return db.query(models.RequirementEvidence).filter(
        models.RequirementEvidence.enrollment_id == enrollment_id,
        models.RequirementEvidence.requirement_id == requirement_id,
        models.RequirementEvidence.status == models.EvidenceStatus.VALID,
    ).order_by(models.RequirementEvidence.created_at.desc()).first()


def build_bundle(db: Session, enrollment: models.Enrollment, commit: bool = True) -> schemas.EvidenceBundle:
    """以期次要求为基准，逐项组装该学员当前的证据组合。"""
    batch = enrollment.batch
    version = effective_rule_version(db, enrollment)

    items: List[schemas.RequirementStatusItem] = []
    required_total = 0
    satisfied_count = 0

    if version is not None:
        sync_original_attendance_evidence(db, enrollment, version)
        if commit:
            db.commit()

        caps = sorted(version.capabilities, key=lambda c: c.sort_order)
        for cap in caps:
            if not cap.is_required:
                continue
            required_total += 1
            evidence = _valid_evidence_for(db, enrollment.id, cap.id)
            session = _original_session_for_requirement(db, enrollment.batch_id, cap.id)
            leave = _latest_leave(db, enrollment.id, session.id if session else None)

            satisfied = evidence is not None
            if satisfied:
                satisfied_count += 1
            items.append(schemas.RequirementStatusItem(
                requirement_id=cap.id,
                code=cap.code,
                name=cap.name,
                is_required=True,
                satisfied=satisfied,
                evidence_id=evidence.id if evidence else None,
                evidence_type=evidence.evidence_type if evidence else None,
                evidence_status=evidence.status if evidence else None,
                detail=evidence.detail if evidence else None,
                leave_status=leave.status if leave else None,
            ))

    topic_name = batch.topic.name if (batch and batch.topic) else None
    missing = required_total - satisfied_count
    return schemas.EvidenceBundle(
        enrollment_id=enrollment.id,
        volunteer_id=enrollment.volunteer_id,
        volunteer_name=enrollment.volunteer.name if enrollment.volunteer else str(enrollment.volunteer_id),
        batch_id=enrollment.batch_id,
        batch_name=batch.name if batch else str(enrollment.batch_id),
        topic_id=batch.topic_id if batch else None,
        topic_name=topic_name,
        rule_version_id=version.id if version else None,
        rule_version_no=version.version_no if version else None,
        requirements=items,
        required_total=required_total,
        satisfied_count=satisfied_count,
        missing_count=missing,
        ready_for_assessment=required_total > 0 and missing == 0,
    )


def bundle_dict(db: Session, enrollment: Optional[models.Enrollment]) -> Dict[str, Any]:
    """发证快照用的可冻结结构。"""
    if enrollment is None:
        return {"rule_version_id": None, "rule_version_no": None, "requirements": []}
    bundle = build_bundle(db, enrollment)
    return {
        "rule_version_id": bundle.rule_version_id,
        "rule_version_no": bundle.rule_version_no,
        "requirements": [
            {
                "requirement_id": it.requirement_id,
                "code": it.code,
                "name": it.name,
                "evidence_id": it.evidence_id,
                "evidence_type": it.evidence_type.value if it.evidence_type else None,
                "detail": it.detail,
            }
            for it in bundle.requirements
        ],
    }


# --------------------------------------------------------------------
# 请假与替代审批
# --------------------------------------------------------------------

def create_leave(db: Session, data: schemas.LeaveRequestCreate) -> models.LeaveRequest:
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.id == data.enrollment_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="报名记录不存在")
    if data.session_id:
        session = db.query(models.TrainingSession).filter(
            models.TrainingSession.id == data.session_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="课次不存在")
        if session.batch_id != enrollment.batch_id:
            raise HTTPException(status_code=400, detail="课次不属于该报名期次")
    leave = models.LeaveRequest(
        enrollment_id=enrollment.id,
        session_id=data.session_id,
        volunteer_id=enrollment.volunteer_id,
        reason_category=data.reason_category,
        reason_detail=data.reason_detail,
        status=models.LeaveStatus.PENDING,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


def decide_leave(db: Session, leave_id: int, decision: schemas.LeaveDecision) -> models.LeaveRequest:
    leave = db.query(models.LeaveRequest).filter(models.LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    if leave.status not in (models.LeaveStatus.PENDING,):
        raise HTTPException(status_code=400, detail=f"请假已审结（{leave.status.value}），不可重复审批")
    leave.status = models.LeaveStatus.APPROVED if decision.approved else models.LeaveStatus.REJECTED
    leave.approver = decision.approver
    leave.approval_comment = decision.approval_comment
    leave.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(leave)
    return leave


def create_substitute_approval(db: Session, data: schemas.SubstituteApprovalCreate) -> models.SubstituteApproval:
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.id == data.enrollment_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="报名记录不存在")
    version = effective_rule_version(db, enrollment)
    if version is None:
        raise HTTPException(status_code=400, detail="该期次尚未定义必修能力规则")
    cap = db.query(models.RequiredCapability).filter(
        models.RequiredCapability.id == data.requirement_id,
        models.RequiredCapability.rule_version_id == version.id,
    ).first()
    if not cap:
        raise HTTPException(status_code=404, detail="必修要求不属于该期次锁定的规则版本")

    if data.leave_request_id:
        leave = db.query(models.LeaveRequest).filter(
            models.LeaveRequest.id == data.leave_request_id
        ).first()
        if not leave:
            raise HTTPException(status_code=404, detail="请假记录不存在")
        if leave.status != models.LeaveStatus.APPROVED:
            raise HTTPException(status_code=400, detail="只有已批准的请假才能安排替代/补训")

    if data.substitute_type == models.RequirementEvidenceType.SUBSTITUTE_COURSE:
        if not data.substitute_session_id:
            raise HTTPException(status_code=400, detail="替代课程必须指定 substitute_session_id")
        sub_session = db.query(models.TrainingSession).filter(
            models.TrainingSession.id == data.substitute_session_id
        ).first()
        if not sub_session:
            raise HTTPException(status_code=404, detail="替代课次不存在")
        if sub_session.batch_id == enrollment.batch_id:
            raise HTTPException(status_code=400, detail="替代课程必须来自其他课次/期次，原课请直接签到")
    elif data.substitute_type == models.RequirementEvidenceType.MAKEUP_EXAM:
        pass
    else:
        raise HTTPException(status_code=400, detail="替代审批类型只能是替代课程或补训考核")

    approval = models.SubstituteApproval(
        enrollment_id=enrollment.id,
        requirement_id=cap.id,
        substitute_type=data.substitute_type,
        substitute_session_id=data.substitute_session_id,
        leave_request_id=data.leave_request_id,
        approver=data.approver,
        comment=data.comment,
        approved_at=datetime.utcnow(),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


# --------------------------------------------------------------------
# 证据登记
# --------------------------------------------------------------------

def register_evidence(db: Session, data: schemas.RequirementEvidenceCreate) -> models.RequirementEvidence:
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.id == data.enrollment_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="报名记录不存在")
    cap = db.query(models.RequiredCapability).filter(
        models.RequiredCapability.id == data.requirement_id
    ).first()
    if not cap:
        raise HTTPException(status_code=404, detail="必修要求不存在")

    duplicate = db.query(models.RequirementEvidence).filter(
        models.RequirementEvidence.enrollment_id == enrollment.id,
        models.RequirementEvidence.requirement_id == cap.id,
        models.RequirementEvidence.status == models.EvidenceStatus.VALID,
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"要求《{cap.name}》已有有效证据(ID={duplicate.id})，一项必修能力只能由一条依据满足；"
                   f"如原依据有误请先撤销再登记"
        )

    evidence = models.RequirementEvidence(
        enrollment_id=enrollment.id,
        requirement_id=cap.id,
        volunteer_id=enrollment.volunteer_id,
        evidence_type=data.evidence_type,
        attendance_id=data.attendance_id,
        substitute_session_id=data.substitute_session_id,
        assessment_id=data.assessment_id,
        approval_id=data.approval_id,
        leave_request_id=data.leave_request_id,
        detail=data.detail,
    )

    if data.evidence_type == models.RequirementEvidenceType.ORIGINAL_ATTENDANCE:
        att = db.query(models.SessionAttendance).filter(
            models.SessionAttendance.id == data.attendance_id
        ).first() if data.attendance_id else None
        if not att:
            raise HTTPException(status_code=404, detail="原课出勤记录不存在")
        if att.enrollment_id != enrollment.id or not att.attended:
            raise HTTPException(status_code=400, detail="该出勤记录不属于本报名或未签到")
        evidence.detail = evidence.detail or f"原课出勤(ID={att.id})"

    elif data.evidence_type == models.RequirementEvidenceType.SUBSTITUTE_COURSE:
        approval = db.query(models.SubstituteApproval).filter(
            models.SubstituteApproval.id == data.approval_id
        ).first() if data.approval_id else None
        if not approval:
            raise HTTPException(status_code=404, detail="替代课程审批不存在")
        if approval.enrollment_id != enrollment.id or approval.requirement_id != cap.id:
            raise HTTPException(status_code=400, detail="审批与报名/要求不匹配")
        sub_att = db.query(models.SessionAttendance).filter(
            models.SessionAttendance.volunteer_id == enrollment.volunteer_id,
            models.SessionAttendance.session_id == approval.substitute_session_id,
            models.SessionAttendance.attended == True,  # noqa: E712
        ).first()
        if not sub_att:
            raise HTTPException(status_code=400, detail="替代课程尚无签到记录，不能作为满足依据")
        evidence.substitute_session_id = approval.substitute_session_id
        evidence.leave_request_id = approval.leave_request_id
        sub_session = approval.substitute_session
        evidence.detail = evidence.detail or (
            f"经批准以《{sub_session.title if sub_session else approval.substitute_session_id}》"
            f"替代《{cap.name}》(审批ID={approval.id})"
        )

    elif data.evidence_type == models.RequirementEvidenceType.MAKEUP_EXAM:
        approval = db.query(models.SubstituteApproval).filter(
            models.SubstituteApproval.id == data.approval_id
        ).first() if data.approval_id else None
        if not approval:
            raise HTTPException(status_code=404, detail="补训考核审批不存在")
        if approval.enrollment_id != enrollment.id or approval.requirement_id != cap.id:
            raise HTTPException(status_code=400, detail="审批与报名/要求不匹配")
        assessment = db.query(models.Assessment).filter(
            models.Assessment.id == data.assessment_id
        ).first() if data.assessment_id else None
        if not assessment:
            raise HTTPException(status_code=404, detail="补训考核记录不存在")
        if assessment.volunteer_id != enrollment.volunteer_id:
            raise HTTPException(status_code=400, detail="补训考核不属于该学员")
        if assessment.result != models.AssessmentResult.PASSED:
            raise HTTPException(status_code=400, detail="补训考核未通过，不能作为满足依据")
        evidence.leave_request_id = approval.leave_request_id
        evidence.detail = evidence.detail or (
            f"经批准以补训考核(ID={assessment.id}，{assessment.score}分)满足《{cap.name}》"
            f"(审批ID={approval.id})"
        )
    else:
        raise HTTPException(status_code=400, detail="未知证据类型")

    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


# --------------------------------------------------------------------
# 考核前置证据核对
# --------------------------------------------------------------------

def resolve_enrollment(db: Session, volunteer_id: int, batch_id: Optional[int],
                       enrollment_id: Optional[int] = None) -> Optional[models.Enrollment]:
    if enrollment_id:
        return db.query(models.Enrollment).filter(
            models.Enrollment.id == enrollment_id
        ).first()
    if not batch_id:
        return None
    return db.query(models.Enrollment).filter(
        models.Enrollment.volunteer_id == volunteer_id,
        models.Enrollment.batch_id == batch_id,
        models.Enrollment.status.in_([
            models.EnrollmentStatus.ENROLLED, models.EnrollmentStatus.COMPLETED
        ]),
    ).order_by(models.Enrollment.id.desc()).first()


def assert_ready_for_assessment(
    db: Session, volunteer_id: int, batch_id: Optional[int],
    enrollment_id: Optional[int] = None,
) -> Optional[schemas.EvidenceBundle]:
    """安排考核/补考前核对前置证据是否齐全。无规则的历史期次走旧流程（放行）。"""
    enrollment = resolve_enrollment(db, volunteer_id, batch_id, enrollment_id)
    if enrollment is None:
        return None
    version = effective_rule_version(db, enrollment)
    if version is None or not [c for c in version.capabilities if c.is_required]:
        return None
    bundle = build_bundle(db, enrollment)
    if not bundle.ready_for_assessment:
        missing = [f"{c.code} {c.name}" for c in bundle.requirements if not c.satisfied]
        raise HTTPException(
            status_code=400,
            detail="前置培训证据不齐全，不能安排考核。缺少：" + "、".join(missing)
        )
    return bundle


def attach_assessment_links(db: Session, assessment: models.Assessment,
                            bundle: Optional[schemas.EvidenceBundle]) -> None:
    """把考核当次核对通过的前置证据固化到考核记录上。"""
    if bundle is None:
        return
    for item in bundle.requirements:
        if not item.satisfied or item.evidence_id is None:
            continue
        db.add(models.AssessmentEvidenceLink(
            assessment_id=assessment.id,
            evidence_id=item.evidence_id,
            requirement_id=item.requirement_id,
            satisfied=True,
            note=f"{item.evidence_type.value if item.evidence_type else ''}",
        ))
    db.flush()


# --------------------------------------------------------------------
# 发证快照冻结
# --------------------------------------------------------------------

def freeze_certification_snapshot(db: Session, cert: models.VolunteerCertification,
                                  assessment: models.Assessment) -> None:
    enrollment = resolve_enrollment(
        db, assessment.volunteer_id, assessment.training_batch_id
    )
    snapshot_data = bundle_dict(db, enrollment)
    snapshot_data["frozen_at"] = datetime.utcnow().isoformat()

    version_id = snapshot_data.get("rule_version_id")
    cert.rule_version_id = version_id

    existing = cert.evidence_snapshot
    if existing:
        # 已冻结过的历史依据绝不重算覆盖
        return
    db.add(models.CertificationEvidenceSnapshot(
        certification_id=cert.id,
        rule_version_id=version_id,
        bundle_json=json.dumps(snapshot_data, ensure_ascii=False),
    ))
    db.flush()


# --------------------------------------------------------------------
# 撤销证据 → 受影响考核/证书进入复核（不删除成绩）
# --------------------------------------------------------------------

def void_evidence(db: Session, evidence_id: int, reason: str,
                  operator: Optional[str] = None) -> Dict[str, Any]:
    evidence = db.query(models.RequirementEvidence).filter(
        models.RequirementEvidence.id == evidence_id
    ).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="证据不存在")
    if evidence.status == models.EvidenceStatus.VOID:
        raise HTTPException(status_code=400, detail="证据已处于撤销状态")

    evidence.status = models.EvidenceStatus.VOID
    evidence.void_reason = reason
    evidence.voided_at = datetime.utcnow()

    affected_assessment_ids = set()
    link = db.query(models.AssessmentEvidenceLink).filter(
        models.AssessmentEvidenceLink.evidence_id == evidence.id
    ).all()
    for l in link:
        affected_assessment_ids.add(l.assessment_id)
    if evidence.evidence_type == models.RequirementEvidenceType.MAKEUP_EXAM and evidence.assessment_id:
        affected_assessment_ids.add(evidence.assessment_id)

    review_reason = f"其依据证据(ID={evidence.id})被撤销：{reason}"
    if operator:
        review_reason += f"（操作人：{operator}）"

    for aid in affected_assessment_ids:
        assessment = db.query(models.Assessment).filter(models.Assessment.id == aid).first()
        if assessment and assessment.review_status != models.ReviewStatus.PENDING_REVIEW:
            assessment.review_status = models.ReviewStatus.PENDING_REVIEW
            assessment.review_reason = review_reason
            assessment.reviewed_at = datetime.utcnow()

    # 证书：通过发证快照追溯（历史依据），或直接由受影响考核发证
    certs_in_review = set()
    snapshots = db.query(models.CertificationEvidenceSnapshot).all()
    for snap in snapshots:
        try:
            payload = json.loads(snap.bundle_json)
        except (ValueError, TypeError):
            continue
        ids = {r.get("evidence_id") for r in payload.get("requirements", [])}
        if evidence.id in ids:
            certs_in_review.add(snap.certification_id)

    for cert in db.query(models.VolunteerCertification).filter(
        models.VolunteerCertification.assessment_id.in_(affected_assessment_ids)
    ).all() if affected_assessment_ids else []:
        certs_in_review.add(cert.id)

    for cid in certs_in_review:
        cert = db.query(models.VolunteerCertification).filter(
            models.VolunteerCertification.id == cid
        ).first()
        if cert and cert.review_status != models.ReviewStatus.PENDING_REVIEW:
            cert.review_status = models.ReviewStatus.PENDING_REVIEW
            cert.review_reason = review_reason
            cert.reviewed_at = datetime.utcnow()

    db.commit()
    return {
        "evidence_id": evidence.id,
        "status": evidence.status,
        "affected_assessments": sorted(affected_assessment_ids),
        "certifications_in_review": sorted(certs_in_review),
        "message": "证据已撤销（保留记录），关联考核与证书已转入复核，既有成绩未被删除",
    }


def resolve_assessment_review(db: Session, assessment_id: int, maintain: bool,
                              reason: Optional[str]) -> models.Assessment:
    assessment = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="考核记录不存在")
    if maintain:
        assessment.review_status = models.ReviewStatus.CONFIRMED
    else:
        # 不删除分数，只标记复核撤销
        assessment.review_status = models.ReviewStatus.REVOKED
    assessment.review_reason = (assessment.review_reason or "") + f" || 复核结论：{reason or ''}"
    assessment.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(assessment)
    return assessment


def resolve_certification_review(db: Session, certification_id: int, maintain: bool,
                                 reason: Optional[str]) -> models.VolunteerCertification:
    cert = db.query(models.VolunteerCertification).filter(
        models.VolunteerCertification.id == certification_id
    ).first()
    if not cert:
        raise HTTPException(status_code=404, detail="资格证不存在")
    if maintain:
        cert.review_status = models.ReviewStatus.CONFIRMED
    else:
        cert.review_status = models.ReviewStatus.REVOKED
        cert.is_active = False
    cert.review_reason = (cert.review_reason or "") + f" || 复核结论：{reason or ''}"
    cert.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(cert)
    return cert
