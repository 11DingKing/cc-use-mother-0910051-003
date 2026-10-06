from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Float, Enum as SAEnum, Boolean
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


class TimeSlotStatus(str, enum.Enum):
    AVAILABLE = "可认领"
    CLAIMED = "已认领"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


class RequirementEvidenceType(str, enum.Enum):
    """满足某项必修能力要求的证据类型"""
    ORIGINAL_ATTENDANCE = "原课出勤"
    SUBSTITUTE_COURSE = "替代课程"
    MAKEUP_EXAM = "补训考核"


class LeaveStatus(str, enum.Enum):
    """缺课请假审批状态"""
    PENDING = "待审批"
    APPROVED = "已批准"
    REJECTED = "已驳回"
    CANCELLED = "已撤销"


class EvidenceStatus(str, enum.Enum):
    """证据本身的有效状态（撤销不等于删除）"""
    VALID = "有效"
    VOID = "已撤销"


class RuleVersionStatus(str, enum.Enum):
    DRAFT = "草稿"
    PUBLISHED = "已发布"


class ReviewStatus(str, enum.Enum):
    """证据被撤销后，受影响的考核/证书进入的复核状态"""
    NORMAL = "正常"
    PENDING_REVIEW = "待复核"
    CONFIRMED = "复核维持"
    REVOKED = "复核撤销"


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
    rule_version_id = Column(Integer, ForeignKey("rule_versions.id"))
    start_date = Column(Date)
    end_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    topic = relationship("AssessmentTopic")
    rule_version = relationship("RuleVersion", foreign_keys=[rule_version_id], back_populates="batches")
    sessions = relationship("TrainingSession", back_populates="batch", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="batch", cascade="all, delete-orphan")
    assessments = relationship("Assessment", back_populates="training_batch")


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
    requirement_id = Column(Integer, ForeignKey("required_capabilities.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("TrainingBatch", back_populates="sessions")
    attendances = relationship("SessionAttendance", back_populates="session", cascade="all, delete-orphan")
    requirement = relationship(
        "RequiredCapability", foreign_keys=[requirement_id],
        back_populates="sessions", post_update=True
    )


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True, index=True)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False)
    status = Column(SAEnum(EnrollmentStatus), default=EnrollmentStatus.ENROLLED)
    rule_version_id = Column(Integer, ForeignKey("rule_versions.id"))
    enrolled_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    notes = Column(Text)

    volunteer = relationship("Volunteer", back_populates="enrollments")
    batch = relationship("TrainingBatch", back_populates="enrollments")
    rule_version = relationship("RuleVersion")
    attendances = relationship("SessionAttendance", back_populates="enrollment", cascade="all, delete-orphan")


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
    rule_version_id = Column(Integer, ForeignKey("rule_versions.id"))
    review_status = Column(SAEnum(ReviewStatus), default=ReviewStatus.NORMAL)
    review_reason = Column(Text)
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="certifications")
    topic = relationship("AssessmentTopic", back_populates="certifications")
    assessment = relationship("Assessment")
    rule_version = relationship("RuleVersion")
    evidence_snapshot = relationship("CertificationEvidenceSnapshot", back_populates="certification", uselist=False, cascade="all, delete-orphan")


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
    review_status = Column(SAEnum(ReviewStatus), default=ReviewStatus.NORMAL)
    review_reason = Column(Text)
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    volunteer = relationship("Volunteer", back_populates="assessments")
    topic_obj = relationship("AssessmentTopic", back_populates="assessments")
    training_batch = relationship("TrainingBatch", back_populates="assessments")
    parent_assessment = relationship("Assessment", remote_side=[id])
    scores = relationship("AssessmentScore", back_populates="assessment", cascade="all, delete-orphan")
    certification = relationship("VolunteerCertification", back_populates="assessment", uselist=False)
    evidence_links = relationship("AssessmentEvidenceLink", back_populates="assessment", cascade="all, delete-orphan")


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


# ====================================================================
# 以培训期次要求为基准的证据组合（Evidence Bundle）
#
# 规则版本（RuleVersion）→ 必修能力（RequiredCapability）
#   每期培训在"发布当时"锁定一版规则；规则改版只产生新版本，
#   不覆盖已形成的组合与已发证人员的历史依据。
#
# 缺课请假（LeaveRequest）：缺课原因 + 审批决定全程留痕。
# 替代审批（SubstituteApproval）：批准"用替代课程/补训考核满足某要求"。
# 要求依据（RequirementEvidence）：一项必修能力由且仅由一条有效依据满足
#   （原课出勤 / 批准的替代课程 / 补训考核）。
# 考核依据（AssessmentEvidenceLink）：安排/通过考核前核对的前置证据清单。
# 发证快照（CertificationEvidenceSnapshot）：发证瞬间的依据冻结，
#   之后规则或证据变化都不会重算覆盖。
# 撤销/复核（EvidenceStatus / ReviewStatus）：撤销只置 VOID 并级联
#   标记受影响考核、证书进入复核，从不物理删除既有成绩。
# ====================================================================


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("assessment_topics.id"))
    version_no = Column(Integer, nullable=False, default=1)
    name = Column(String(100), nullable=False)
    status = Column(SAEnum(RuleVersionStatus), default=RuleVersionStatus.DRAFT)
    change_note = Column(Text)
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("AssessmentTopic")
    capabilities = relationship(
        "RequiredCapability", back_populates="rule_version",
        cascade="all, delete-orphan"
    )
    batches = relationship(
        "TrainingBatch", foreign_keys=[TrainingBatch.rule_version_id],
        back_populates="rule_version"
    )


class RequiredCapability(Base):
    """某版规则下的一项必修能力要求（通常对应一节必修课）"""
    __tablename__ = "required_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    rule_version_id = Column(Integer, ForeignKey("rule_versions.id"), nullable=False)
    code = Column(String(30), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_required = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    rule_version = relationship("RuleVersion", back_populates="capabilities")
    sessions = relationship(
        "TrainingSession", foreign_keys=[TrainingSession.requirement_id]
    )
    evidences = relationship(
        "RequirementEvidence", back_populates="requirement",
        cascade="all, delete-orphan"
    )


class LeaveRequest(Base):
    """学员针对某节必修课的缺课请假：原因与审批决定留痕"""
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("training_sessions.id"))
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    reason_category = Column(String(50), nullable=False)
    reason_detail = Column(Text)
    status = Column(SAEnum(LeaveStatus), default=LeaveStatus.PENDING)
    approver = Column(String(50))
    approval_comment = Column(Text)
    approved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    enrollment = relationship("Enrollment")
    session = relationship("TrainingSession")
    volunteer = relationship("Volunteer")


class SubstituteApproval(Base):
    """批准用替代课程或补训考核来满足某项必修要求的审批记录"""
    __tablename__ = "substitute_approvals"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False)
    requirement_id = Column(Integer, ForeignKey("required_capabilities.id"), nullable=False)
    substitute_type = Column(SAEnum(RequirementEvidenceType), nullable=False)
    substitute_session_id = Column(Integer, ForeignKey("training_sessions.id"))
    leave_request_id = Column(Integer, ForeignKey("leave_requests.id"))
    approver = Column(String(50))
    comment = Column(Text)
    approved_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    enrollment = relationship("Enrollment")
    requirement = relationship("RequiredCapability")
    substitute_session = relationship("TrainingSession", foreign_keys=[substitute_session_id])
    leave_request = relationship("LeaveRequest")


class RequirementEvidence(Base):
    """
    一项必修能力的满足依据。evidence_type:
      ORIGINAL_ATTENDANCE 原课出勤  → attendance_id
      SUBSTITUTE_COURSE   替代课程  → substitute_session_id + approval_id
      MAKEUP_EXAM         补训考核  → assessment_id + approval_id
    """
    __tablename__ = "requirement_evidences"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=False)
    requirement_id = Column(Integer, ForeignKey("required_capabilities.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    evidence_type = Column(SAEnum(RequirementEvidenceType), nullable=False)
    status = Column(SAEnum(EvidenceStatus), default=EvidenceStatus.VALID)

    attendance_id = Column(Integer, ForeignKey("session_attendances.id"))
    substitute_session_id = Column(Integer, ForeignKey("training_sessions.id"))
    assessment_id = Column(Integer, ForeignKey("assessments.id"))
    approval_id = Column(Integer, ForeignKey("substitute_approvals.id"))
    leave_request_id = Column(Integer, ForeignKey("leave_requests.id"))

    detail = Column(Text)
    void_reason = Column(Text)
    voided_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    enrollment = relationship("Enrollment")
    requirement = relationship("RequiredCapability", back_populates="evidences")
    volunteer = relationship("Volunteer")
    attendance = relationship("SessionAttendance")
    substitute_session = relationship("TrainingSession", foreign_keys=[substitute_session_id])
    assessment = relationship("Assessment")
    approval = relationship("SubstituteApproval")
    leave_request = relationship("LeaveRequest")


class AssessmentEvidenceLink(Base):
    """考核所依据的前置证据核对项：安排补考前逐项核对是否齐全"""
    __tablename__ = "assessment_evidence_links"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    evidence_id = Column(Integer, ForeignKey("requirement_evidences.id"), nullable=False)
    requirement_id = Column(Integer, ForeignKey("required_capabilities.id"), nullable=False)
    satisfied = Column(Boolean, default=False)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    assessment = relationship("Assessment", back_populates="evidence_links")
    evidence = relationship("RequirementEvidence")
    requirement = relationship("RequiredCapability")


class CertificationEvidenceSnapshot(Base):
    """发证瞬间冻结的证据组合：历史依据不随后续改版/撤销被重算覆盖"""
    __tablename__ = "certification_evidence_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    certification_id = Column(Integer, ForeignKey("volunteer_certifications.id"), nullable=False, unique=True)
    rule_version_id = Column(Integer, ForeignKey("rule_versions.id"))
    bundle_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    certification = relationship("VolunteerCertification", back_populates="evidence_snapshot")
    rule_version = relationship("RuleVersion")
