"""
证据组合（Evidence Bundle）API。

围绕"以培训期次要求为基准的证据组合"提供：
- 规则版本（改版只产生新版本，历史组合与发证快照不重算）
- 课次↔必修能力对应
- 缺课请假与审批留痕
- 替代课程/补训考核审批
- 必修证据登记、撤销（非物理删除）
- 某人距可考核还缺什么 / 一次补训替代了哪项要求
- 撤销后进入复核的考核与证书队列、复核结论
- 发证历史依据快照查询
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
import evidence_service as svc

router = APIRouter(prefix="/api/evidence", tags=["证据组合管理"])


# ==================== 规则版本 ====================

@router.get("/rule-versions", response_model=List[schemas.RuleVersion])
def list_rule_versions(topic_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.RuleVersion)
    if topic_id is not None:
        query = query.filter(models.RuleVersion.topic_id == topic_id)
    return query.order_by(
        models.RuleVersion.topic_id, models.RuleVersion.version_no.desc()
    ).all()


@router.get("/rule-versions/{version_id}", response_model=schemas.RuleVersion)
def get_rule_version(version_id: int, db: Session = Depends(get_db)):
    version = db.query(models.RuleVersion).filter(models.RuleVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="规则版本不存在")
    return version


@router.post("/rule-versions", response_model=schemas.RuleVersion)
def create_rule_version(data: schemas.RuleVersionCreate, db: Session = Depends(get_db)):
    if data.topic_id is not None:
        topic = db.query(models.AssessmentTopic).filter(
            models.AssessmentTopic.id == data.topic_id
        ).first()
        if not topic:
            raise HTTPException(status_code=404, detail="考核主题不存在")

    caps_payload = data.capabilities
    if not caps_payload and data.source_version_id:
        source = db.query(models.RuleVersion).filter(
            models.RuleVersion.id == data.source_version_id
        ).first()
        if not source:
            raise HTTPException(status_code=404, detail="来源规则版本不存在")
        caps_payload = [
            schemas.RequiredCapabilityCreate(
                code=c.code, name=c.name, description=c.description,
                is_required=c.is_required, sort_order=c.sort_order,
            ) for c in source.capabilities
        ]
    if not caps_payload:
        raise HTTPException(status_code=400, detail="规则版本至少包含一项能力要求")

    max_no = db.query(models.RuleVersion).filter(
        models.RuleVersion.topic_id == data.topic_id
    ).count() or 0
    version = models.RuleVersion(
        topic_id=data.topic_id,
        version_no=max_no + 1,
        name=data.name,
        change_note=data.change_note,
        status=(models.RuleVersionStatus.PUBLISHED if data.publish
                else models.RuleVersionStatus.DRAFT),
        published_at=datetime.utcnow() if data.publish else None,
    )
    db.add(version)
    db.flush()
    for idx, c in enumerate(caps_payload):
        db.add(models.RequiredCapability(
            rule_version_id=version.id,
            code=c.code,
            name=c.name,
            description=c.description,
            is_required=c.is_required,
            sort_order=c.sort_order or idx,
        ))
    db.commit()
    db.refresh(version)
    return version


@router.post("/rule-versions/{version_id}/publish", response_model=schemas.RuleVersion)
def publish_rule_version(version_id: int, data: Optional[schemas.RuleVersionPublish] = None,
                         db: Session = Depends(get_db)):
    version = db.query(models.RuleVersion).filter(models.RuleVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="规则版本不存在")
    if not version.capabilities:
        raise HTTPException(status_code=400, detail="规则版本没有任何能力要求，不能发布")
    if version.status != models.RuleVersionStatus.PUBLISHED:
        version.status = models.RuleVersionStatus.PUBLISHED
        version.published_at = datetime.utcnow()
    if data and data.change_note:
        version.change_note = data.change_note
    db.commit()
    db.refresh(version)
    return version


@router.post("/sessions/link", response_model=schemas.TrainingSession)
def link_session_requirement(data: schemas.SessionRequirementLink, db: Session = Depends(get_db)):
    """把一节必修课次对应到某项必修能力（解决线下补训材料无法与原课次对应的问题）。"""
    session = db.query(models.TrainingSession).filter(
        models.TrainingSession.id == data.session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="课次不存在")
    cap = db.query(models.RequiredCapability).filter(
        models.RequiredCapability.id == data.requirement_id
    ).first()
    if not cap:
        raise HTTPException(status_code=404, detail="必修能力要求不存在")
    session.requirement_id = cap.id
    db.commit()
    db.refresh(session)
    return session


# ==================== 缺课请假 ====================

@router.get("/enrollments/{enrollment_id}/leaves", response_model=List[schemas.LeaveRequest])
def list_enrollment_leaves(enrollment_id: int, db: Session = Depends(get_db)):
    return db.query(models.LeaveRequest).filter(
        models.LeaveRequest.enrollment_id == enrollment_id
    ).order_by(models.LeaveRequest.created_at.desc()).all()


@router.post("/leaves", response_model=schemas.LeaveRequest)
def create_leave(data: schemas.LeaveRequestCreate, db: Session = Depends(get_db)):
    return svc.create_leave(db, data)


@router.post("/leaves/{leave_id}/decision", response_model=schemas.LeaveRequest)
def decide_leave(leave_id: int, decision: schemas.LeaveDecision, db: Session = Depends(get_db)):
    return svc.decide_leave(db, leave_id, decision)


# ==================== 替代/补训审批 ====================

@router.get("/enrollments/{enrollment_id}/substitute-approvals",
            response_model=List[schemas.SubstituteApproval])
def list_substitute_approvals(enrollment_id: int, db: Session = Depends(get_db)):
    return db.query(models.SubstituteApproval).filter(
        models.SubstituteApproval.enrollment_id == enrollment_id
    ).order_by(models.SubstituteApproval.approved_at.desc()).all()


@router.post("/substitute-approvals", response_model=schemas.SubstituteApproval)
def create_substitute_approval(data: schemas.SubstituteApprovalCreate, db: Session = Depends(get_db)):
    return svc.create_substitute_approval(db, data)


# ==================== 证据登记与查询 ====================

@router.get("/enrollments/{enrollment_id}/evidences", response_model=List[schemas.RequirementEvidence])
def list_enrollment_evidences(enrollment_id: int, db: Session = Depends(get_db)):
    return db.query(models.RequirementEvidence).filter(
        models.RequirementEvidence.enrollment_id == enrollment_id
    ).order_by(models.RequirementEvidence.id).all()


@router.get("/evidences/by-assessment/{assessment_id}",
            response_model=List[schemas.RequirementEvidence])
def list_evidences_by_assessment(assessment_id: int, db: Session = Depends(get_db)):
    """一次补训考核替代了哪项要求：按补训考核反查满足的必修项。"""
    return db.query(models.RequirementEvidence).filter(
        models.RequirementEvidence.assessment_id == assessment_id
    ).all()


@router.post("/evidences", response_model=schemas.RequirementEvidence)
def register_evidence(data: schemas.RequirementEvidenceCreate, db: Session = Depends(get_db)):
    return svc.register_evidence(db, data)


@router.get("/evidences/{evidence_id}", response_model=schemas.RequirementEvidence)
def get_evidence(evidence_id: int, db: Session = Depends(get_db)):
    evidence = db.query(models.RequirementEvidence).filter(
        models.RequirementEvidence.id == evidence_id
    ).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="证据不存在")
    return evidence


@router.post("/evidences/{evidence_id}/void", response_model=schemas.EvidenceVoidResult)
def void_evidence(evidence_id: int, data: schemas.VoidEvidenceRequest, db: Session = Depends(get_db)):
    """撤销错误证据：不删除记录，关联考核/证书转入复核。"""
    return svc.void_evidence(db, evidence_id, data.reason, data.operator)


# ==================== 证据组合 / 可考核差距查询 ====================

@router.get("/enrollments/{enrollment_id}/bundle", response_model=schemas.EvidenceBundle)
def get_enrollment_bundle(enrollment_id: int, db: Session = Depends(get_db)):
    enrollment = db.query(models.Enrollment).filter(
        models.Enrollment.id == enrollment_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="报名记录不存在")
    return svc.build_bundle(db, enrollment)


@router.get("/volunteers/{volunteer_id}/readiness", response_model=List[schemas.EvidenceBundle])
def volunteer_readiness(volunteer_id: int, batch_id: Optional[int] = None,
                        db: Session = Depends(get_db)):
    """某人距离可考核还缺什么：逐期返回证据组合与缺失项。"""
    volunteer = db.query(models.Volunteer).filter(models.Volunteer.id == volunteer_id).first()
    if not volunteer:
        raise HTTPException(status_code=404, detail="志愿者不存在")
    query = db.query(models.Enrollment).filter(
        models.Enrollment.volunteer_id == volunteer_id,
        models.Enrollment.status.in_([
            models.EnrollmentStatus.ENROLLED, models.EnrollmentStatus.COMPLETED
        ]),
    )
    if batch_id is not None:
        query = query.filter(models.Enrollment.batch_id == batch_id)
    return [svc.build_bundle(db, e) for e in query.order_by(models.Enrollment.id).all()]


# ==================== 考核前置依据核对 ====================

@router.get("/assessments/{assessment_id}/evidence-links")
def list_assessment_evidence_links(assessment_id: int, db: Session = Depends(get_db)):
    assessment = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="考核记录不存在")
    return [
        {
            "link_id": l.id,
            "assessment_id": l.assessment_id,
            "evidence_id": l.evidence_id,
            "requirement_id": l.requirement_id,
            "requirement_name": l.requirement.name if l.requirement else None,
            "evidence_type": l.evidence.evidence_type.value if l.evidence else None,
            "evidence_status": l.evidence.status.value if l.evidence else None,
            "detail": l.evidence.detail if l.evidence else None,
            "satisfied": l.satisfied,
        }
        for l in sorted(assessment.evidence_links, key=lambda x: x.id)
    ]


# ==================== 发证历史依据快照 ====================

@router.get("/certifications/{certification_id}/snapshot",
            response_model=Optional[schemas.CertificationEvidenceSnapshotOut])
def get_certification_snapshot(certification_id: int, db: Session = Depends(get_db)):
    cert = db.query(models.VolunteerCertification).filter(
        models.VolunteerCertification.id == certification_id
    ).first()
    if not cert:
        raise HTTPException(status_code=404, detail="资格证不存在")
    return cert.evidence_snapshot


# ==================== 复核队列与结论 ====================

@router.get("/reviews/assessments")
def list_assessments_in_review(db: Session = Depends(get_db)):
    rows = db.query(models.Assessment).filter(
        models.Assessment.review_status == models.ReviewStatus.PENDING_REVIEW
    ).order_by(models.Assessment.reviewed_at.desc()).all()
    return [
        {
            "assessment_id": a.id,
            "volunteer_id": a.volunteer_id,
            "topic_id": a.topic_id,
            "topic": a.topic,
            "score": a.score,
            "result": a.result.value if a.result else None,
            "review_status": a.review_status.value,
            "review_reason": a.review_reason,
            "reviewed_at": a.reviewed_at,
        }
        for a in rows
    ]


@router.post("/reviews/assessments/{assessment_id}")
def resolve_assessment_review(assessment_id: int, decision: schemas.ReviewDecision,
                              db: Session = Depends(get_db)):
    a = svc.resolve_assessment_review(db, assessment_id, decision.maintain, decision.reason)
    return {
        "assessment_id": a.id,
        "review_status": a.review_status.value,
        "score_kept": a.score,
        "message": "复核维持，成绩保留" if decision.maintain else "复核撤销，成绩已标记但未删除",
    }


@router.get("/reviews/certifications")
def list_certifications_in_review(db: Session = Depends(get_db)):
    rows = db.query(models.VolunteerCertification).filter(
        models.VolunteerCertification.review_status == models.ReviewStatus.PENDING_REVIEW
    ).order_by(models.VolunteerCertification.reviewed_at.desc()).all()
    return [
        {
            "certification_id": c.id,
            "volunteer_id": c.volunteer_id,
            "topic_id": c.topic_id,
            "certificate_no": c.certificate_no,
            "is_active": c.is_active,
            "review_status": c.review_status.value,
            "review_reason": c.review_reason,
            "reviewed_at": c.reviewed_at,
        }
        for c in rows
    ]


@router.post("/reviews/certifications/{certification_id}")
def resolve_certification_review(certification_id: int, decision: schemas.ReviewDecision,
                                 db: Session = Depends(get_db)):
    c = svc.resolve_certification_review(db, certification_id, decision.maintain, decision.reason)
    return {
        "certification_id": c.id,
        "certificate_no": c.certificate_no,
        "review_status": c.review_status.value,
        "is_active": c.is_active,
        "message": "复核维持，证书继续有效，历史依据快照不变" if decision.maintain
                   else "复核撤销，证书已停用（记录保留）",
    }
