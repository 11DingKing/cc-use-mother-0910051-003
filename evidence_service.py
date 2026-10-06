"""
培训证据组合核心服务。

设计要点：
- 以期次必修能力要求（BatchRequirement，隶属规则版本 BatchRuleVersion）为基准；
- 每项必修要求可由 原课出勤 / 批准的替代课程 / 补训考核 三类证据之一满足；
- 规则改版生成新版本，旧版本要求与证据行冻结保留，已形成的考核依据快照不重算；
- 撤销证据只改状态，不删除成绩，并为受影响的考核/证书生成复核任务。
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

import models
import schemas


# ==================== 规则版本 ====================

def get_current_version(db: Session, batch_id: int, create: bool = False) -> Optional[models.BatchRuleVersion]:
    version = db.query(models.BatchRuleVersion).filter(
        models.BatchRuleVersion.batch_id == batch_id,
        models.BatchRuleVersion.is_current == True  # noqa: E712
    ).order_by(models.BatchRuleVersion.version_no.desc()).first()
    if version is None and create:
        version = models.BatchRuleVersion(
            batch_id=batch_id, version_no=1,
            change_summary="初始规则版本"
        )
        db.add(version)
        db.flush()
    return version


def publish_revision(
    db: Session,
    batch_id: int,
    requirements: List[schemas.BatchRequirementCreate],
    change_summary: Optional[str],
    published_by: Optional[str],
) -> models.BatchRuleVersion:
    """发布课程规则新版本：旧版本冻结，之后形成的证据组合按新版本要求登记。"""
    batch = db.query(models.TrainingBatch).filter(models.TrainingBatch.id == batch_id).first()
    if not batch:
        raise ValueError("培训期次不存在")

    codes = [r.code for r in requirements]
    if len(codes) != len(set(codes)):
        raise ValueError("同版本内要求编码不能重复")

    old = get_current_version(db, batch_id)
    next_no = (old.version_no + 1) if old else 1
    if old:
        old.is_current = False

    version = models.BatchRuleVersion(
        batch_id=batch_id,
        version_no=next_no,
        change_summary=change_summary,
        published_by=published_by,
        is_current=True,
    )
    db.add(version)
    db.flush()

    for r in requirements:
        _create_requirement_row(db, batch_id, version, r)

    db.flush()
    return version


def _create_requirement_row(
    db: Session, batch_id: int, version: models.BatchRuleVersion, data: schemas.BatchRequirementCreate
) -> models.BatchRequirement:
    for sid in data.session_ids:
        session = db.query(models.TrainingSession).filter(models.TrainingSession.id == sid).first()
        if not session or session.batch_id != batch_id:
            raise ValueError(f"课次ID={sid}不属于该期次，不能关联必修要求")
    req = models.BatchRequirement(
        batch_id=batch_id,
        rule_version_id=version.id,
        code=data.code,
        name=data.name,
        requirement_status=data.requirement_status,
        description=data.description,
    )
    db.add(req)
    db.flush()
    if data.session_ids:
        sessions = db.query(models.TrainingSession).filter(
            models.TrainingSession.id.in_(data.session_ids)
        ).all()
        req.sessions = sessions
    return req


def create_requirement(db: Session, batch_id: int, data: schemas.BatchRequirementCreate) -> models.BatchRequirement:
    batch = db.query(models.TrainingBatch).filter(models.TrainingBatch.id == batch_id).first()
    if not batch:
        raise ValueError("培训期次不存在")
    version = get_current_version(db, batch_id, create=True)
    dup = db.query(models.BatchRequirement).filter(
        models.BatchRequirement.rule_version_id == version.id,
        models.BatchRequirement.code == data.code
    ).first()
    if dup:
        raise ValueError(f"当前规则版本(v{version.version_no})下要求编码'{data.code}'已存在")
    req = _create_requirement_row(db, batch_id, version, data)
    db.flush()
    return req


def update_requirement(db: Session, requirement_id: int, data: schemas.BatchRequirementUpdate) -> models.BatchRequirement:
    """仅允许修改当前版本中的要求行；历史版本冻结。"""
    req = db.query(models.BatchRequirement).filter(models.BatchRequirement.id == requirement_id).first()
    if not req:
        raise LookupError("必修要求不存在")
    current = get_current_version(db, req.batch_id)
    if not current or req.rule_version_id != current.id:
        raise PermissionError("该要求隶属已冻结的历史规则版本，不能修改；如需调整请发布规则新版本")
    payload = data.model_dump(exclude_unset=True)
    session_ids = payload.pop("session_ids", None)
    for key, value in payload.items():
        setattr(req, key, value)
    if session_ids is not None:
        for sid in session_ids:
            session = db.query(models.TrainingSession).filter(models.TrainingSession.id == sid).first()
            if not session or session.batch_id != req.batch_id:
                raise ValueError(f"课次ID={sid}不属于该期次，不能关联必修要求")
        req.sessions = db.query(models.TrainingSession).filter(
            models.TrainingSession.id.in_(session_ids)
        ).all() if session_ids else []
    db.flush()
    return req


# ==================== 证据 / 资格计算 ====================

def _active_evidences_for_requirements(
    db: Session, volunteer_id: int, req_ids: List[int]
) -> Dict[int, List[models.CompetencyEvidence]]:
    """该志愿者在指定版本要求行上的有效证据（证据严格隶属形成时的版本要求，不跨版本继承）。"""
    if not req_ids:
        return {}
    rows = db.query(models.CompetencyEvidence).filter(
        models.CompetencyEvidence.volunteer_id == volunteer_id,
        models.CompetencyEvidence.requirement_id.in_(req_ids),
        models.CompetencyEvidence.status == models.EvidenceStatus.ACTIVE,
    ).all()
    result: Dict[int, List[models.CompetencyEvidence]] = {}
    for ev in rows:
        result.setdefault(ev.requirement_id, []).append(ev)
    return result


def _approved_makeup_session_ids(db: Session, volunteer_id: int, batch_id: int) -> set:
    """该志愿者在本期次下已获批准补训考核、但补训结果尚未形成证据的缺课课次集合。"""
    rows = db.query(models.AbsenceRecord.session_id).join(
        models.Enrollment, models.AbsenceRecord.enrollment_id == models.Enrollment.id
    ).filter(
        models.Enrollment.batch_id == batch_id,
        models.AbsenceRecord.volunteer_id == volunteer_id,
        models.AbsenceRecord.decision == models.ApprovalDecision.MAKEUP,
    ).all()
    return {row[0] for row in rows}


def evaluate_eligibility(db: Session, volunteer_id: int, batch_id: int) -> schemas.EligibilityGap:
    """以当前规则版本为基准，逐项核对必修要求是否有有效证据组合支撑。

    已获批准补训考核的要求视为"补训在途"，允许安排补考，但在补训考核证据形成前
    仍标记为未最终满足（satisfied=False）。
    """
    volunteer = db.query(models.Volunteer).filter(models.Volunteer.id == volunteer_id).first()
    if not volunteer:
        raise LookupError("志愿者不存在")
    batch = db.query(models.TrainingBatch).filter(models.TrainingBatch.id == batch_id).first()
    if not batch:
        raise LookupError("培训期次不存在")

    version = get_current_version(db, batch_id)
    reqs = db.query(models.BatchRequirement).filter(
        models.BatchRequirement.rule_version_id == version.id
    ).order_by(models.BatchRequirement.code).all() if version else []
    evidence_map = _active_evidences_for_requirements(db, volunteer_id, [r.id for r in reqs])
    makeup_session_ids = _approved_makeup_session_ids(db, volunteer_id, batch_id)

    requirement_statuses: List[schemas.RequirementEvidenceStatus] = []
    missing: List[str] = []
    for req in reqs:
        evs = evidence_map.get(req.id, [])
        satisfied = len(evs) > 0
        makeup_in_flight = (not satisfied) and any(
            s.id in makeup_session_ids for s in req.sessions
        )
        if req.requirement_status == models.RequirementStatus.REQUIRED:
            if not satisfied and not makeup_in_flight:
                missing.append(f"{req.code} {req.name}")
        requirement_statuses.append(schemas.RequirementEvidenceStatus(
            requirement_id=req.id,
            code=req.code,
            name=req.name,
            requirement_status=req.requirement_status,
            satisfied=satisfied,
            has_makeup_approval=makeup_in_flight,
            active_evidences=evs,
        ))

    return schemas.EligibilityGap(
        volunteer_id=volunteer_id,
        batch_id=batch_id,
        rule_version_id=version.id if version else None,
        can_assess=len(missing) == 0,
        requirements=requirement_statuses,
        missing_requirements=missing,
        missing_count=len(missing),
    )


def _batches_for_volunteer_topic(
    db: Session, volunteer_id: int, training_batch_id: Optional[int], topic_id: Optional[int]
) -> List[int]:
    if training_batch_id:
        return [training_batch_id]
    query = db.query(models.Enrollment.batch_id).filter(
        models.Enrollment.volunteer_id == volunteer_id,
        models.Enrollment.status.in_([
            models.EnrollmentStatus.ENROLLED, models.EnrollmentStatus.COMPLETED
        ])
    )
    if topic_id:
        query = query.join(
            models.TrainingBatch, models.Enrollment.batch_id == models.TrainingBatch.id
        ).filter(models.TrainingBatch.topic_id == topic_id)
    return [row[0] for row in query.distinct().all()]


def check_prerequisites(
    db: Session, volunteer_id: int,
    training_batch_id: Optional[int] = None, topic_id: Optional[int] = None,
) -> Tuple[bool, List[int], List[schemas.EligibilityGap]]:
    """安排考核/补考前核对前置证据：所有相关期次必修要求均有有效证据方可安排。"""
    batch_ids = _batches_for_volunteer_topic(db, volunteer_id, training_batch_id, topic_id)
    gaps = [evaluate_eligibility(db, volunteer_id, bid) for bid in batch_ids]
    incomplete = [g for g in gaps if not g.can_assess]
    return (len(incomplete) == 0, batch_ids, incomplete if incomplete else gaps)


def build_attendance_evidences(db: Session, enrollment_id: int) -> List[models.CompetencyEvidence]:
    """把原课出勤事实物化为"原课出勤"证据（出勤为真且课次关联了必修要求）。"""
    enrollment = db.query(models.Enrollment).filter(models.Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise LookupError("报名记录不存在")
    version = get_current_version(db, enrollment.batch_id)
    created: List[models.CompetencyEvidence] = []
    if not version:
        return created

    attendances = db.query(models.SessionAttendance).filter(
        models.SessionAttendance.enrollment_id == enrollment_id,
        models.SessionAttendance.attended == True  # noqa: E712
    ).all()
    att_by_session = {a.session_id: a for a in attendances}

    reqs = db.query(models.BatchRequirement).filter(
        models.BatchRequirement.rule_version_id == version.id
    ).all()
    for req in reqs:
        linked = req.sessions
        if not linked:
            continue
        valid_att = [att_by_session[s.id] for s in linked if s.id in att_by_session]
        if not valid_att:
            continue
        existing = db.query(models.CompetencyEvidence).filter(
            models.CompetencyEvidence.volunteer_id == enrollment.volunteer_id,
            models.CompetencyEvidence.requirement_id == req.id,
            models.CompetencyEvidence.evidence_type == models.EvidenceType.ATTENDANCE,
            models.CompetencyEvidence.status == models.EvidenceStatus.ACTIVE,
        ).first()
        if existing:
            continue
        ev = models.CompetencyEvidence(
            requirement_id=req.id,
            volunteer_id=enrollment.volunteer_id,
            enrollment_id=enrollment.id,
            evidence_type=models.EvidenceType.ATTENDANCE,
            attendance_id=valid_att[0].id,
            note=f"原课出勤自动汇总（{len(valid_att)}/{len(linked)}节关联课次）",
        )
        db.add(ev)
        created.append(ev)
    db.flush()
    return created


def build_substitute_evidences(db: Session, enrollment_id: int) -> List[models.CompetencyEvidence]:
    """已批准替代课程且替代课次确有出勤的，自动形成"替代课程"证据。"""
    enrollment = db.query(models.Enrollment).filter(models.Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise LookupError("报名记录不存在")
    version = get_current_version(db, enrollment.batch_id)
    created: List[models.CompetencyEvidence] = []
    if not version:
        return created

    absences = db.query(models.AbsenceRecord).filter(
        models.AbsenceRecord.enrollment_id == enrollment_id,
        models.AbsenceRecord.decision == models.ApprovalDecision.SUBSTITUTE,
        models.AbsenceRecord.substitute_session_id.isnot(None),
    ).all()

    reqs = db.query(models.BatchRequirement).filter(
        models.BatchRequirement.rule_version_id == version.id
    ).all()

    for absence in absences:
        sub_att = db.query(models.SessionAttendance).filter(
            models.SessionAttendance.volunteer_id == enrollment.volunteer_id,
            models.SessionAttendance.session_id == absence.substitute_session_id,
            models.SessionAttendance.attended == True  # noqa: E712
        ).first()
        if not sub_att:
            continue
        for req in reqs:
            if absence.session_id not in {s.id for s in req.sessions}:
                continue
            exists = db.query(models.CompetencyEvidence).filter(
                models.CompetencyEvidence.volunteer_id == enrollment.volunteer_id,
                models.CompetencyEvidence.requirement_id == req.id,
                models.CompetencyEvidence.evidence_type == models.EvidenceType.SUBSTITUTE,
                models.CompetencyEvidence.status == models.EvidenceStatus.ACTIVE,
            ).first()
            if exists:
                continue
            created.append(models.CompetencyEvidence(
                requirement_id=req.id,
                volunteer_id=enrollment.volunteer_id,
                enrollment_id=enrollment.id,
                evidence_type=models.EvidenceType.SUBSTITUTE,
                substitute_session_id=absence.substitute_session_id,
                absence_id=absence.id,
                note="替代课程出勤自动汇总",
            ))
    if created:
        db.add_all(created)
        db.flush()
    return created


def build_makeup_evidences_for_assessment(db: Session, assessment: models.Assessment) -> List[models.CompetencyEvidence]:
    """补训考核通过后，为已批准补训考核的缺课要求自动形成"补训考核"证据。"""
    if not assessment.training_batch_id or assessment.result != models.AssessmentResult.PASSED:
        return []
    version = get_current_version(db, assessment.training_batch_id)
    if not version:
        return []

    absences = db.query(models.AbsenceRecord).join(
        models.Enrollment, models.AbsenceRecord.enrollment_id == models.Enrollment.id
    ).filter(
        models.Enrollment.batch_id == assessment.training_batch_id,
        models.AbsenceRecord.volunteer_id == assessment.volunteer_id,
        models.AbsenceRecord.decision == models.ApprovalDecision.MAKEUP,
    ).all()

    reqs = db.query(models.BatchRequirement).filter(
        models.BatchRequirement.rule_version_id == version.id
    ).all()

    created: List[models.CompetencyEvidence] = []
    for absence in absences:
        for req in reqs:
            if absence.session_id not in {s.id for s in req.sessions}:
                continue
            exists = db.query(models.CompetencyEvidence).filter(
                models.CompetencyEvidence.volunteer_id == assessment.volunteer_id,
                models.CompetencyEvidence.requirement_id == req.id,
                models.CompetencyEvidence.evidence_type == models.EvidenceType.MAKEUP_EXAM,
                models.CompetencyEvidence.status == models.EvidenceStatus.ACTIVE,
            ).first()
            if exists:
                continue
            created.append(models.CompetencyEvidence(
                requirement_id=req.id,
                volunteer_id=assessment.volunteer_id,
                evidence_type=models.EvidenceType.MAKEUP_EXAM,
                assessment_id=assessment.id,
                absence_id=absence.id,
                note=f"补训考核通过自动汇总（考核ID={assessment.id}）",
            ))
    if created:
        db.add_all(created)
        db.flush()
    return created


def create_evidence(db: Session, data: schemas.CompetencyEvidenceCreate) -> models.CompetencyEvidence:
    """登记证据，并按证据类型校验前置链条（替代/补考必须有批准留痕）。"""
    volunteer = db.query(models.Volunteer).filter(models.Volunteer.id == data.volunteer_id).first()
    if not volunteer:
        raise LookupError("志愿者不存在")
    req = db.query(models.BatchRequirement).filter(
        models.BatchRequirement.id == data.requirement_id
    ).first()
    if not req:
        raise LookupError("必修要求不存在")

    absence = None
    if data.absence_id:
        absence = db.query(models.AbsenceRecord).filter(models.AbsenceRecord.id == data.absence_id).first()
        if not absence:
            raise LookupError("缺课记录不存在")
        if absence.volunteer_id != data.volunteer_id:
            raise ValueError("缺课记录与志愿者不匹配")

    if data.evidence_type == models.EvidenceType.ATTENDANCE:
        if not data.attendance_id:
            raise ValueError("原课出勤证据必须关联出勤记录")
        att = db.query(models.SessionAttendance).filter(
            models.SessionAttendance.id == data.attendance_id
        ).first()
        if not att:
            raise LookupError("出勤记录不存在")
        if att.volunteer_id != data.volunteer_id or not att.attended:
            raise ValueError("出勤记录不属于该志愿者或出勤结果为缺勤")
        linked_session_ids = {s.id for s in req.sessions}
        if linked_session_ids and att.session_id not in linked_session_ids:
            raise ValueError("该出勤课次与必修要求不对应")

    elif data.evidence_type == models.EvidenceType.SUBSTITUTE:
        if not absence or absence.decision != models.ApprovalDecision.SUBSTITUTE:
            raise ValueError("替代课程证据必须有'批准替代课程'的缺课审批留痕")
        sub_id = data.substitute_session_id or absence.substitute_session_id
        if not sub_id:
            raise ValueError("审批未指定替代课程，无法登记替代证据")
        sub_session = db.query(models.TrainingSession).filter(models.TrainingSession.id == sub_id).first()
        if not sub_session:
            raise LookupError("替代课程课次不存在")
        data.substitute_session_id = sub_id

    elif data.evidence_type == models.EvidenceType.MAKEUP_EXAM:
        if not absence or absence.decision != models.ApprovalDecision.MAKEUP:
            raise ValueError("补训考核证据必须有'批准补训考核'的缺课审批留痕")
        if not data.assessment_id:
            raise ValueError("补训考核证据必须关联考核记录")
        assessment = db.query(models.Assessment).filter(models.Assessment.id == data.assessment_id).first()
        if not assessment:
            raise LookupError("考核记录不存在")
        if assessment.volunteer_id != data.volunteer_id:
            raise ValueError("考核记录与志愿者不匹配")

    duplicate = db.query(models.CompetencyEvidence).filter(
        models.CompetencyEvidence.requirement_id == data.requirement_id,
        models.CompetencyEvidence.volunteer_id == data.volunteer_id,
        models.CompetencyEvidence.evidence_type == data.evidence_type,
        models.CompetencyEvidence.status == models.EvidenceStatus.ACTIVE,
    )
    if data.attendance_id:
        duplicate = duplicate.filter(models.CompetencyEvidence.attendance_id == data.attendance_id)
    if data.assessment_id:
        duplicate = duplicate.filter(models.CompetencyEvidence.assessment_id == data.assessment_id)
    if duplicate.first():
        raise ValueError("该要求下已存在同类有效证据，请勿重复登记")

    evidence = models.CompetencyEvidence(**data.model_dump())
    db.add(evidence)
    db.flush()
    return evidence


def snapshot_assessment_basis(db: Session, assessment: models.Assessment) -> List[models.AssessmentEvidenceBasis]:
    """考核形成时把当时所依据的有效证据组合拍成快照；之后规则改版不重算该快照。"""
    batch_id = assessment.training_batch_id
    if not batch_id:
        return []
    gap = evaluate_eligibility(db, assessment.volunteer_id, batch_id)
    basis: List[models.AssessmentEvidenceBasis] = []
    for item in gap.requirements:
        for ev in item.active_evidences:
            basis.append(models.AssessmentEvidenceBasis(
                assessment_id=assessment.id,
                evidence_id=ev.id,
                requirement_id=item.requirement_id,
                evidence_type=ev.evidence_type,
            ))
    if basis:
        db.add_all(basis)
        db.flush()
    return basis


# ==================== 证据撤销与复核 ====================

def revoke_evidence(
    db: Session, evidence_id: int, revoked_by: Optional[str], revoke_reason: Optional[str]
) -> Tuple[models.CompetencyEvidence, List[models.EvidenceReview]]:
    """撤销错误证据：证据置为已撤销（不删行、不删成绩），受影响的考核与证书进入复核。"""
    evidence = db.query(models.CompetencyEvidence).filter(
        models.CompetencyEvidence.id == evidence_id
    ).first()
    if not evidence:
        raise LookupError("证据不存在")
    if evidence.status == models.EvidenceStatus.REVOKED:
        raise ValueError("该证据已处于撤销状态")

    evidence.status = models.EvidenceStatus.REVOKED
    evidence.revoked_at = datetime.utcnow()
    evidence.revoked_by = revoked_by
    evidence.revoke_reason = revoke_reason

    reason = revoke_reason or "证据被撤销，需复核其支撑的考核与发证结论"

    # 1) 考核形成时快照引用过该证据的考核
    basis_rows = db.query(models.AssessmentEvidenceBasis).filter(
        models.AssessmentEvidenceBasis.evidence_id == evidence_id
    ).all()
    affected_assessment_ids = {row.assessment_id for row in basis_rows}
    # 2) 补训考核证据直接关联的考核
    if evidence.assessment_id:
        affected_assessment_ids.add(evidence.assessment_id)

    reviews: List[models.EvidenceReview] = []

    def _add_review(assessment_id: Optional[int], certification_id: Optional[int]):
        q = db.query(models.EvidenceReview).filter(
            models.EvidenceReview.evidence_id == evidence_id,
            models.EvidenceReview.status == models.ReviewStatus.PENDING,
        )
        if assessment_id:
            q = q.filter(models.EvidenceReview.assessment_id == assessment_id)
        if certification_id:
            q = q.filter(models.EvidenceReview.certification_id == certification_id)
        if q.first():
            return
        review = models.EvidenceReview(
            evidence_id=evidence_id,
            assessment_id=assessment_id,
            certification_id=certification_id,
            reason=reason,
        )
        db.add(review)
        reviews.append(review)

    for aid in affected_assessment_ids:
        _add_review(aid, None)
        cert = db.query(models.VolunteerCertification).filter(
            models.VolunteerCertification.assessment_id == aid,
            models.VolunteerCertification.is_active == True,  # noqa: E712
        ).first()
        if cert:
            _add_review(aid, cert.id)

    db.flush()
    return evidence, reviews
