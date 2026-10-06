"""培训证据组合 API：必修要求规则版本、缺课审批、证据登记、资格缺口查询、撤销与复核。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional

from database import get_db
import models, schemas
import evidence_service as svc

router = APIRouter(prefix="/api/evidence", tags=["培训证据组合"])


def _require_entity(obj, name: str):
    if not obj:
        raise HTTPException(status_code=404, detail=name)


# ==================== 规则版本与必修要求 ====================

@router.get("/batches/{batch_id}/rule-versions", response_model=List[schemas.BatchRuleVersion])
def list_rule_versions(batch_id: int, db: Session = Depends(get_db)):
    _require_entity(db.query(models.TrainingBatch).filter(models.TrainingBatch.id == batch_id).first(), "培训期次不存在")
    return db.query(models.BatchRuleVersion).filter(
        models.BatchRuleVersion.batch_id == batch_id
    ).order_by(models.BatchRuleVersion.version_no.desc()).all()


@router.post("/batches/{batch_id}/rule-versions", response_model=schemas.BatchRuleVersion)
def publish_rule_version(batch_id: int, data: schemas.BatchRuleVersionPublish, db: Session = Depends(get_db)):
    """发布课程规则新版本：只影响之后形成的证据组合，历史版本与已发证依据冻结不重算。"""
    try:
        version = svc.publish_revision(
            db, batch_id, data.requirements, data.change_summary, data.published_by
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.refresh(version)
    return version


@router.get("/batches/{batch_id}/requirements", response_model=List[schemas.BatchRequirementDetail])
def list_requirements(
    batch_id: int, rule_version_id: Optional[int] = None,
    include_history: bool = False, db: Session = Depends(get_db)
):
    _require_entity(db.query(models.TrainingBatch).filter(models.TrainingBatch.id == batch_id).first(), "培训期次不存在")
    query = db.query(models.BatchRequirement).filter(models.BatchRequirement.batch_id == batch_id)
    if rule_version_id:
        query = query.filter(models.BatchRequirement.rule_version_id == rule_version_id)
    elif not include_history:
        current = svc.get_current_version(db, batch_id)
        query = query.filter(models.BatchRequirement.rule_version_id == current.id) if current else query.filter(False)
    reqs = query.order_by(
        models.BatchRequirement.rule_version_id, models.BatchRequirement.code
    ).all()
    result = []
    for req in reqs:
        result.append(schemas.BatchRequirementDetail(
            id=req.id, batch_id=req.batch_id, rule_version_id=req.rule_version_id,
            code=req.code, name=req.name, requirement_status=req.requirement_status,
            description=req.description, created_at=req.created_at,
            rule_version=req.rule_version,
            session_ids=[s.id for s in req.sessions],
        ))
    return result


@router.post("/batches/{batch_id}/requirements", response_model=schemas.BatchRequirementDetail)
def create_requirement(batch_id: int, data: schemas.BatchRequirementCreate, db: Session = Depends(get_db)):
    try:
        req = svc.create_requirement(db, batch_id, data)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.refresh(req)
    return schemas.BatchRequirementDetail(
        id=req.id, batch_id=req.batch_id, rule_version_id=req.rule_version_id,
        code=req.code, name=req.name, requirement_status=req.requirement_status,
        description=req.description, created_at=req.created_at,
        rule_version=req.rule_version, session_ids=[s.id for s in req.sessions],
    )


@router.put("/requirements/{requirement_id}", response_model=schemas.BatchRequirementDetail)
def update_requirement(requirement_id: int, data: schemas.BatchRequirementUpdate, db: Session = Depends(get_db)):
    try:
        req = svc.update_requirement(db, requirement_id, data)
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.refresh(req)
    return schemas.BatchRequirementDetail(
        id=req.id, batch_id=req.batch_id, rule_version_id=req.rule_version_id,
        code=req.code, name=req.name, requirement_status=req.requirement_status,
        description=req.description, created_at=req.created_at,
        rule_version=req.rule_version, session_ids=[s.id for s in req.sessions],
    )


# ==================== 缺课登记与审批留痕 ====================

@router.post("/absences", response_model=schemas.AbsenceRecordDetail)
def report_absence(data: schemas.AbsenceCreate, db: Session = Depends(get_db)):
    enrollment = db.query(models.Enrollment).filter(models.Enrollment.id == data.enrollment_id).first()
    _require_entity(enrollment, "报名记录不存在")
    session = db.query(models.TrainingSession).filter(
        models.TrainingSession.id == data.session_id,
        models.TrainingSession.batch_id == enrollment.batch_id
    ).first()
    _require_entity(session, "课次不存在或不属于该期次")
    existing = db.query(models.AbsenceRecord).filter(
        models.AbsenceRecord.enrollment_id == data.enrollment_id,
        models.AbsenceRecord.session_id == data.session_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该课次已登记缺课，请勿重复登记")
    absence = models.AbsenceRecord(
        enrollment_id=data.enrollment_id,
        session_id=data.session_id,
        volunteer_id=enrollment.volunteer_id,
        reason=data.reason,
        reason_detail=data.reason_detail,
        evidence_note=data.evidence_note,
    )
    db.add(absence)
    db.commit()
    db.refresh(absence)
    return absence


@router.get("/enrollments/{enrollment_id}/absences", response_model=List[schemas.AbsenceRecordDetail])
def list_enrollment_absences(enrollment_id: int, db: Session = Depends(get_db)):
    _require_entity(
        db.query(models.Enrollment).filter(models.Enrollment.id == enrollment_id).first(),
        "报名记录不存在"
    )
    return db.query(models.AbsenceRecord).filter(
        models.AbsenceRecord.enrollment_id == enrollment_id
    ).order_by(models.AbsenceRecord.reported_at.desc()).all()


@router.get("/volunteers/{volunteer_id}/absences", response_model=List[schemas.AbsenceRecordDetail])
def list_volunteer_absences(volunteer_id: int, db: Session = Depends(get_db)):
    _require_entity(
        db.query(models.Volunteer).filter(models.Volunteer.id == volunteer_id).first(),
        "志愿者不存在"
    )
    return db.query(models.AbsenceRecord).filter(
        models.AbsenceRecord.volunteer_id == volunteer_id
    ).order_by(models.AbsenceRecord.reported_at.desc()).all()


@router.post("/absences/{absence_id}/decision", response_model=schemas.AbsenceRecordDetail)
def decide_absence(absence_id: int, data: schemas.AbsenceDecisionUpdate, db: Session = Depends(get_db)):
    absence = db.query(models.AbsenceRecord).filter(models.AbsenceRecord.id == absence_id).first()
    _require_entity(absence, "缺课记录不存在")
    if absence.decision != models.ApprovalDecision.PENDING:
        raise HTTPException(status_code=400, detail="该缺课已审批，不能重复决定")
    if data.decision == models.ApprovalDecision.PENDING:
        raise HTTPException(status_code=400, detail="审批决定不能为待审批")
    if data.decision == models.ApprovalDecision.SUBSTITUTE:
        sub_id = data.substitute_session_id
        if not sub_id:
            raise HTTPException(status_code=400, detail="批准替代课程必须指定替代课次")
        sub_session = db.query(models.TrainingSession).filter(models.TrainingSession.id == sub_id).first()
        _require_entity(sub_session, "替代课次不存在")
        if sub_session.id == absence.session_id:
            raise HTTPException(status_code=400, detail="替代课次不能是缺课原课次")
        absence.substitute_session_id = sub_id
    absence.decision = data.decision
    absence.decided_by = data.decided_by
    absence.decision_comment = data.decision_comment
    absence.decided_at = datetime.utcnow()
    db.commit()
    db.refresh(absence)
    return absence


# ==================== 证据登记与查询 ====================

@router.post("/evidences", response_model=schemas.CompetencyEvidenceDetail)
def create_evidence(data: schemas.CompetencyEvidenceCreate, db: Session = Depends(get_db)):
    try:
        evidence = svc.create_evidence(db, data)
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.refresh(evidence)
    return evidence


@router.post("/enrollments/{enrollment_id}/sync-attendance-evidence", response_model=List[schemas.CompetencyEvidence])
def sync_attendance_evidence(enrollment_id: int, db: Session = Depends(get_db)):
    """按当前规则把原课出勤、已批准且实到的替代课程汇总为证据（幂等，已存在则跳过）。"""
    try:
        created = svc.build_attendance_evidences(db, enrollment_id)
        created += svc.build_substitute_evidences(db, enrollment_id)
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    return created


@router.get("/volunteers/{volunteer_id}/evidences", response_model=List[schemas.CompetencyEvidenceDetail])
def list_volunteer_evidences(
    volunteer_id: int, batch_id: Optional[int] = None,
    status: Optional[models.EvidenceStatus] = None, db: Session = Depends(get_db)
):
    """查询某人的证据组合；可按期次、状态过滤。"""
    _require_entity(
        db.query(models.Volunteer).filter(models.Volunteer.id == volunteer_id).first(),
        "志愿者不存在"
    )
    query = db.query(models.CompetencyEvidence).join(
        models.BatchRequirement,
        models.CompetencyEvidence.requirement_id == models.BatchRequirement.id
    ).filter(models.CompetencyEvidence.volunteer_id == volunteer_id)
    if batch_id:
        query = query.filter(models.BatchRequirement.batch_id == batch_id)
    if status:
        query = query.filter(models.CompetencyEvidence.status == status)
    return query.order_by(models.CompetencyEvidence.created_at.desc()).all()


@router.get("/volunteers/{volunteer_id}/eligibility", response_model=List[schemas.EligibilityGap])
def eligibility_gaps(
    volunteer_id: int, batch_id: Optional[int] = None, db: Session = Depends(get_db)
):
    """查询某人距离可考核还缺什么（逐期次列出必修要求的证据满足情况）。"""
    _require_entity(
        db.query(models.Volunteer).filter(models.Volunteer.id == volunteer_id).first(),
        "志愿者不存在"
    )
    if batch_id:
        batch_ids = [batch_id]
    else:
        batch_ids = [row[0] for row in db.query(models.Enrollment.batch_id).filter(
            models.Enrollment.volunteer_id == volunteer_id,
            models.Enrollment.status.in_([
                models.EnrollmentStatus.ENROLLED, models.EnrollmentStatus.COMPLETED
            ])
        ).distinct().all()]
    return [svc.evaluate_eligibility(db, volunteer_id, bid) for bid in batch_ids]


@router.get("/requirements/{requirement_id}/evidences", response_model=List[schemas.CompetencyEvidenceDetail])
def list_requirement_evidences(requirement_id: int, db: Session = Depends(get_db)):
    """一次补训/替代到底满足了哪项要求：按必修要求反查证据。"""
    _require_entity(
        db.query(models.BatchRequirement).filter(models.BatchRequirement.id == requirement_id).first(),
        "必修要求不存在"
    )
    return db.query(models.CompetencyEvidence).filter(
        models.CompetencyEvidence.requirement_id == requirement_id
    ).order_by(models.CompetencyEvidence.created_at.desc()).all()


@router.get("/assessments/prerequisite-check", response_model=schemas.AssessmentEvidenceCheck)
def assessment_prerequisite_check(
    volunteer_id: int,
    training_batch_id: Optional[int] = None,
    topic_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """安排考核/补考前核对前置证据是否齐全（必修要求逐项有效证据）。"""
    _require_entity(
        db.query(models.Volunteer).filter(models.Volunteer.id == volunteer_id).first(),
        "志愿者不存在"
    )
    ok, batch_ids, gaps = svc.check_prerequisites(db, volunteer_id, training_batch_id, topic_id)
    return schemas.AssessmentEvidenceCheck(
        volunteer_id=volunteer_id,
        topic_id=topic_id,
        training_batch_id=training_batch_id,
        prerequisites_complete=ok,
        checked_batches=batch_ids,
        gaps=gaps,
    )


# ==================== 证据撤销与复核 ====================
@router.post("/evidences/{evidence_id}/revoke")
def revoke_evidence(evidence_id: int, data: schemas.EvidenceRevoke, db: Session = Depends(get_db)):
    """撤销错误证据：不删除既有成绩，受影响的考核/证书自动生成待复核任务。"""
    try:
        evidence, reviews = svc.revoke_evidence(
            db, evidence_id, data.revoked_by, data.revoke_reason
        )
        db.commit()
    except LookupError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "message": "证据已撤销，关联考核与证书已进入复核",
        "evidence_id": evidence.id,
        "review_count": len(reviews),
        "review_ids": [r.id for r in reviews],
    }


@router.get("/reviews", response_model=List[schemas.EvidenceReview])
def list_reviews(
    status: Optional[models.ReviewStatus] = None,
    volunteer_id: Optional[int] = None, db: Session = Depends(get_db)
):
    """撤销证据后的复核清单。"""
    query = db.query(models.EvidenceReview)
    if status:
        query = query.filter(models.EvidenceReview.status == status)
    if volunteer_id:
        query = query.join(
            models.CompetencyEvidence,
            models.EvidenceReview.evidence_id == models.CompetencyEvidence.id
        ).filter(models.CompetencyEvidence.volunteer_id == volunteer_id)
    return query.order_by(models.EvidenceReview.created_at.desc()).all()


@router.post("/reviews/{review_id}/handle", response_model=schemas.EvidenceReview)
def handle_review(review_id: int, data: schemas.EvidenceReviewHandle, db: Session = Depends(get_db)):
    """复核结论：维持原考核成绩，或标记改判（成绩记录本身保留）。"""
    review = db.query(models.EvidenceReview).filter(models.EvidenceReview.id == review_id).first()
    _require_entity(review, "复核任务不存在")
    if review.status != models.ReviewStatus.PENDING:
        raise HTTPException(status_code=400, detail="该复核任务已处理")
    review.status = data.status
    review.handled_by = data.handled_by
    review.handle_comment = data.handle_comment
    review.handled_at = datetime.utcnow()
    db.commit()
    db.refresh(review)
    return review
