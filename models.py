from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Float, Enum as SAEnum, Boolean, Table
from sqlalchemy.orm import relationship
from datetime import datetime, date
from database import Base
import enum


class VolunteerStatus(str, enum.Enum):
    PENDING_REVIEW = "报名待审"
    IN_TRAINING = "培训中"
    PENDING_ASSESSMENT = "待考核"
    CERTIFIED = "已持证"
    DISABLED = "已停用"


class AssessmentResult(str, enum.Enum):
    PENDING = "待考核"
    PASSED = "通过"
    FAILED = "未通过"


class TrainingBatchStatus(str, enum.Enum):
    DRAFT = "草稿"
    ENROLLING = "报名中"
    IN_PROGRESS = "进行中"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


class EnrollmentStatus(str, enum.Enum):
    ENROLLED = "已入班"
    DROPPED = "已退班"
    COMPLETED = "已完成培训"


class AbsenceReason(str, enum.Enum):
    PERSONAL = "事假"
    SICK = "病假"
    SCHOOL_ACTIVITY = "学校活动"
    OTHER = "其他"


class ApprovalDecision(str, enum.Enum):
    PENDING = "待审批"
    SUBSTITUTE = "批准替代课程"
    MAKEUP = "批准补训考核"
    REJECTED = "不予批准"


class RequirementStatus(str, enum.Enum):
    REQUIRED = "必修"
    OPTIONAL = "选修"


class EvidenceType(str, enum.Enum):
    ATTENDANCE = "原课出勤"
    SUBSTITUTE = "替代课程"
    MAKEUP_EXAM = "补训考核"


class EvidenceStatus(str, enum.Enum):
    ACTIVE = "有效"
    REVOKED = "已撤销"


class ReviewStatus(str, enum.Enum):
    PENDING = "待复核"
    CONFIRMED = "复核维持"
    REVISED = "复核改判"


class TimeSlotStatus(str, enum.Enum):
    AVAILABLE = "可认领"
    CLAIMED = "已认领"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    contact_person = Column(String(50))
    contact_phone = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteers = relationship("Volunteer", back_populates="school")


class StarLevel(Base):
    __tablename__ = "star_levels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(20), nullable=False, unique=True)
    min_hours = Column(Float, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteers = relationship("Volunteer", back_populates="star_level")


class PointsType(str, enum.Enum):
    EARN = "获得"
    SPEND = "消耗"


class PointsSource(str, enum.Enum):
    SERVICE_COMPLETION = "完成讲解"
    TEACHER_RATING = "老师好评"
    EXCHANGE_BADGE = "兑换徽章"
    EXCHANGE_PRIORITY_SLOT = "兑换优先时段"
    OTHER = "其他"


class BenefitType(str, enum.Enum):
    BADGE = "纪念徽章"
    PRIORITY_SLOT = "优先认领时段"
    OTHER = "其他权益"


class ExchangeStatus(str, enum.Enum):
    PENDING = "待处理"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


class Volunteer(Base):
    __tablename__ = "volunteers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    gender = Column(String(10))
    birth_date = Column(Date)
    school_id = Column(Integer, ForeignKey("schools.id"))
    grade = Column(String(20))
    parent_name = Column(String(50))
    parent_phone = Column(String(20))
    preferred_topic = Column(String(100))
    status = Column(SAEnum(VolunteerStatus), default=VolunteerStatus.PENDING_REVIEW)
    star_level_id = Column(Integer, ForeignKey("star_levels.id"))
    total_service_hours = Column(Float, default=0.0)
    points_balance = Column(Integer, default=0)
    registration_date = Column(Date, default=date.today)
    certification_date = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    school = relationship("School", back_populates="volunteers")
    star_level = relationship("StarLevel", back_populates="volunteers")
    trainings = relationship("TrainingAttendance", back_populates="volunteer")
    assessments = relationship("Assessment", back_populates="volunteer")
    time_slots = relationship("TimeSlot", back_populates="volunteer")
    service_records = relationship("ServiceRecord", back_populates="volunteer")
    enrollments = relationship("Enrollment", back_populates="volunteer")
    certifications = relationship("VolunteerCertification", back_populates="volunteer")
    points_records = relationship("PointsRecord", back_populates="volunteer")
    benefit_exchanges = relationship("BenefitExchange", back_populates="volunteer")
    star_certificates = relationship("StarCertificate", back_populates="volunteer")
    competency_evidences = relationship("CompetencyEvidence", back_populates="volunteer")


class AssessmentTopic(Base):
    __tablename__ = "assessment_topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    pass_score = Column(Float, default=60.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    criteria = relationship("AssessmentCriterion", back_populates="topic")
    questions = relationship("AssessmentQuestion", back_populates="topic")
    assessments = relationship("Assessment", back_populates="topic_obj")
    certifications = relationship("VolunteerCertification", back_populates="topic")


class TrainingBatch(Base):
    __tablename__ = "training_batches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    topic_id = Column(Integer, ForeignKey("assessment_topics.id"))
    description = Column(Text)
    min_attendance_rate = Column(Float, default=80.0)
    capacity = Column(Integer, default=30)
    status = Column(SAEnum(TrainingBatchStatus), default=TrainingBatchStatus.DRAFT)
    start_date = Column(Date)
    end_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    topic = relationship("AssessmentTopic")
    sessions = relationship("TrainingSession", back_populates="batch", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="batch", cascade="all, delete-orphan")
    assessments = relationship("Assessment", back_populates="training_batch")
    rule_versions = relationship("BatchRuleVersion", back_populates="batch")
    requirements = relationship("BatchRequirement", back_populates="batch")


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False)
    session_no = Column(Integer, nullable=False)
    title = Column(String(100), nullable=False)
    session_date = Column(Date, nullable=False)
    start_time = Column(String(10))
    end_time = Column(String(10))
    location = Column(String(100))
    trainer = Column(String(50))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("TrainingBatch", back_populates="sessions")
    attendances = relationship("SessionAttendance", back_populates="session", cascade="all, delete-orphan")


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False)
    status = Column(SAEnum(EnrollmentStatus), default=EnrollmentStatus.ENROLLED)
    enrolled_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    notes = Column(Text)

    volunteer = relationship("Volunteer", back_populates="enrollments")
    batch = relationship("TrainingBatch", back_populates="enrollments")
    attendances = relationship("SessionAttendance", back_populates="enrollment", cascade="all, delete-orphan")
    absences = relationship("AbsenceRecord", back_populates="enrollment")


class SessionAttendance(Base):
    __tablename__ = "session_attendances"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("training_sessions.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    attended = Column(Boolean, default=False)
    late = Column(Boolean, default=False)
    leave_early = Column(Boolean, default=False)
    checked_at = Column(DateTime)
    remarks = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    enrollment = relationship("Enrollment", back_populates="attendances")
    session = relationship("TrainingSession", back_populates="attendances")
    volunteer = relationship("Volunteer")


class AssessmentCriterion(Base):
    __tablename__ = "assessment_criteria"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("assessment_topics.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    max_score = Column(Float, default=20.0)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("AssessmentTopic", back_populates="criteria")
    scores = relationship("AssessmentScore", back_populates="criterion", cascade="all, delete-orphan")


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("assessment_topics.id"), nullable=False)
    question = Column(Text, nullable=False)
    reference_answer = Column(Text)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("AssessmentTopic", back_populates="questions")


class AssessmentScore(Base):
    __tablename__ = "assessment_scores"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    criterion_id = Column(Integer, ForeignKey("assessment_criteria.id"), nullable=False)
    score = Column(Float, default=0.0)
    comments = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    assessment = relationship("Assessment", back_populates="scores")
    criterion = relationship("AssessmentCriterion", back_populates="scores")


class VolunteerCertification(Base):
    __tablename__ = "volunteer_certifications"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("assessment_topics.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"))
    certificate_no = Column(String(50), unique=True)
    issued_date = Column(Date, default=date.today)
    expiry_date = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="certifications")
    topic = relationship("AssessmentTopic", back_populates="certifications")
    assessment = relationship("Assessment")


class Training(Base):
    __tablename__ = "trainings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    training_date = Column(Date, nullable=False)
    start_time = Column(String(10))
    end_time = Column(String(10))
    location = Column(String(100))
    trainer = Column(String(50))
    content = Column(Text)
    max_participants = Column(Integer, default=30)
    created_at = Column(DateTime, default=datetime.utcnow)

    attendances = relationship("TrainingAttendance", back_populates="training")


class TrainingAttendance(Base):
    __tablename__ = "training_attendances"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"))
    training_id = Column(Integer, ForeignKey("trainings.id"))
    attended = Column(Integer, default=0)
    remarks = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="trainings")
    training = relationship("Training", back_populates="attendances")


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    topic_id = Column(Integer, ForeignKey("assessment_topics.id"))
    training_batch_id = Column(Integer, ForeignKey("training_batches.id"))
    parent_assessment_id = Column(Integer, ForeignKey("assessments.id"))
    assessment_date = Column(Date, nullable=False)
    topic = Column(String(100))
    score = Column(Float)
    result = Column(SAEnum(AssessmentResult), default=AssessmentResult.PENDING)
    is_retake = Column(Boolean, default=False)
    attempt_no = Column(Integer, default=1)
    examiner = Column(String(50))
    comments = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="assessments")
    topic_obj = relationship("AssessmentTopic", back_populates="assessments")
    training_batch = relationship("TrainingBatch", back_populates="assessments")
    parent_assessment = relationship("Assessment", remote_side=[id])
    scores = relationship("AssessmentScore", back_populates="assessment", cascade="all, delete-orphan")
    certification = relationship("VolunteerCertification", back_populates="assessment", uselist=False)
    evidence_basis = relationship("AssessmentEvidenceBasis", back_populates="assessment")


class TimeSlot(Base):
    __tablename__ = "time_slots"

    id = Column(Integer, primary_key=True, index=True)
    slot_date = Column(Date, nullable=False)
    start_time = Column(String(10), nullable=False)
    end_time = Column(String(10), nullable=False)
    topic = Column(String(100))
    location = Column(String(100))
    status = Column(SAEnum(TimeSlotStatus), default=TimeSlotStatus.AVAILABLE)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="time_slots")
    service_record = relationship("ServiceRecord", back_populates="time_slot", uselist=False)


class ServiceRecord(Base):
    __tablename__ = "service_records"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"))
    time_slot_id = Column(Integer, ForeignKey("time_slots.id"))
    service_date = Column(Date, nullable=False)
    service_hours = Column(Float, nullable=False)
    audience_count = Column(Integer, default=0)
    teacher_name = Column(String(50))
    teacher_rating = Column(Integer)
    teacher_comments = Column(Text)
    points_awarded = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="service_records")
    time_slot = relationship("TimeSlot", back_populates="service_record")


class PointsRecord(Base):
    __tablename__ = "points_records"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    points_type = Column(SAEnum(PointsType), nullable=False)
    points_amount = Column(Integer, nullable=False)
    source = Column(SAEnum(PointsSource), nullable=False)
    service_record_id = Column(Integer, ForeignKey("service_records.id"))
    exchange_id = Column(Integer, ForeignKey("benefit_exchanges.id"))
    description = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="points_records")
    service_record = relationship("ServiceRecord")
    exchange = relationship("BenefitExchange", back_populates="points_record")


class Benefit(Base):
    __tablename__ = "benefits"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    benefit_type = Column(SAEnum(BenefitType), nullable=False)
    description = Column(Text)
    points_cost = Column(Integer, nullable=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    image_url = Column(String(500))
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    exchanges = relationship("BenefitExchange", back_populates="benefit")


class BenefitExchange(Base):
    __tablename__ = "benefit_exchanges"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    benefit_id = Column(Integer, ForeignKey("benefits.id"), nullable=False)
    points_spent = Column(Integer, nullable=False)
    status = Column(SAEnum(ExchangeStatus), default=ExchangeStatus.PENDING)
    quantity = Column(Integer, default=1)
    delivery_info = Column(Text)
    fulfilled_at = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="benefit_exchanges")
    benefit = relationship("Benefit", back_populates="exchanges")
    points_record = relationship("PointsRecord", back_populates="exchange", uselist=False)


class StarCertificate(Base):
    __tablename__ = "star_certificates"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    star_level_id = Column(Integer, ForeignKey("star_levels.id"), nullable=False)
    certificate_no = Column(String(50), unique=True, nullable=False)
    issued_date = Column(Date, default=date.today)
    total_hours = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="star_certificates")
    star_level = relationship("StarLevel")


# ==================== 培训证据组合（必修能力依据） ====================

# 必修能力要求 ↔ 原课次（一项要求可对应多节课，一节课也可支撑多项要求）
batch_requirement_sessions = Table(
    "batch_requirement_sessions",
    Base.metadata,
    Column("requirement_id", Integer, ForeignKey("batch_requirements.id"), primary_key=True),
    Column("session_id", Integer, ForeignKey("training_sessions.id"), primary_key=True),
)


class BatchRuleVersion(Base):
    """课程规则版本：改版生成新版本，旧版本及其要求、证据组合永久保留、不被重算。"""
    __tablename__ = "batch_rule_versions"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    change_summary = Column(Text)
    published_by = Column(String(50))
    published_at = Column(DateTime, default=datetime.utcnow)
    is_current = Column(Boolean, default=True)

    batch = relationship("TrainingBatch", back_populates="rule_versions")
    requirements = relationship("BatchRequirement", back_populates="rule_version")


class BatchRequirement(Base):
    """期次必修能力要求（规则版本下的快照行，发布后不可改，改版另建新行）。"""
    __tablename__ = "batch_requirements"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False)
    rule_version_id = Column(Integer, ForeignKey("batch_rule_versions.id"))
    code = Column(String(30), nullable=False)
    name = Column(String(100), nullable=False)
    requirement_status = Column(SAEnum(RequirementStatus), default=RequirementStatus.REQUIRED)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("TrainingBatch", back_populates="requirements")
    rule_version = relationship("BatchRuleVersion", back_populates="requirements")
    sessions = relationship("TrainingSession", secondary=batch_requirement_sessions)
    evidences = relationship("CompetencyEvidence", back_populates="requirement")


class AbsenceRecord(Base):
    """缺课登记与审批：缺课原因、批准的替代方式都在此留痕。"""
    __tablename__ = "absence_records"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("training_sessions.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    reason = Column(SAEnum(AbsenceReason), nullable=False)
    reason_detail = Column(Text)
    evidence_note = Column(Text)
    reported_at = Column(DateTime, default=datetime.utcnow)
    decision = Column(SAEnum(ApprovalDecision), default=ApprovalDecision.PENDING)
    decided_by = Column(String(50))
    decided_at = Column(DateTime)
    decision_comment = Column(Text)
    substitute_session_id = Column(Integer, ForeignKey("training_sessions.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    enrollment = relationship("Enrollment", back_populates="absences")
    session = relationship("TrainingSession", foreign_keys=[session_id])
    substitute_session = relationship("TrainingSession", foreign_keys=[substitute_session_id])
    evidences = relationship("CompetencyEvidence", back_populates="absence")


class CompetencyEvidence(Base):
    """
    必修能力证据组合：每项必修要求可由 原课出勤 / 批准的替代课程 / 补训考核 之一满足。
    撤销只改状态不删行；撤销后依赖它的考核、证书进入复核（见 EvidenceReview）。
    """
    __tablename__ = "competency_evidences"

    id = Column(Integer, primary_key=True, index=True)
    requirement_id = Column(Integer, ForeignKey("batch_requirements.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"))
    evidence_type = Column(SAEnum(EvidenceType), nullable=False)
    status = Column(SAEnum(EvidenceStatus), default=EvidenceStatus.ACTIVE)
    attendance_id = Column(Integer, ForeignKey("session_attendances.id"))
    substitute_session_id = Column(Integer, ForeignKey("training_sessions.id"))
    assessment_id = Column(Integer, ForeignKey("assessments.id"))
    absence_id = Column(Integer, ForeignKey("absence_records.id"))
    note = Column(Text)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime)
    revoked_by = Column(String(50))
    revoke_reason = Column(Text)

    requirement = relationship("BatchRequirement", back_populates="evidences")
    volunteer = relationship("Volunteer", back_populates="competency_evidences")
    enrollment = relationship("Enrollment")
    attendance = relationship("SessionAttendance")
    substitute_session = relationship("TrainingSession", foreign_keys=[substitute_session_id])
    assessment = relationship("Assessment", foreign_keys=[assessment_id])
    absence = relationship("AbsenceRecord", back_populates="evidences")
    basis_rows = relationship("AssessmentEvidenceBasis", back_populates="evidence")


class AssessmentEvidenceBasis(Base):
    """考核形成时的证据快照：考核依据了哪些有效证据，历史依据不随后续规则改版重算。"""
    __tablename__ = "assessment_evidence_basis"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    evidence_id = Column(Integer, ForeignKey("competency_evidences.id"), nullable=False)
    requirement_id = Column(Integer, ForeignKey("batch_requirements.id"), nullable=False)
    evidence_type = Column(SAEnum(EvidenceType), nullable=False)
    snapshot_at = Column(DateTime, default=datetime.utcnow)

    assessment = relationship("Assessment", back_populates="evidence_basis")
    evidence = relationship("CompetencyEvidence", back_populates="basis_rows")
    requirement = relationship("BatchRequirement")


class EvidenceReview(Base):
    """证据撤销引发的复核任务：关联考核/证书进入待复核，成绩与证书记录不删除。"""
    __tablename__ = "evidence_reviews"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(Integer, ForeignKey("competency_evidences.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"))
    certification_id = Column(Integer, ForeignKey("volunteer_certifications.id"))
    reason = Column(Text)
    status = Column(SAEnum(ReviewStatus), default=ReviewStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    handled_by = Column(String(50))
    handled_at = Column(DateTime)
    handle_comment = Column(Text)

    evidence = relationship("CompetencyEvidence")
    assessment = relationship("Assessment", foreign_keys=[assessment_id])
    certification = relationship("VolunteerCertification", foreign_keys=[certification_id])
