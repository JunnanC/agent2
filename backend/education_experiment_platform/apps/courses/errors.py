from apps.core.errors import CoreError


class CourseStateConflict(CoreError):
    code = "COURSE_STATE_CONFLICT"
    message = "课程当前状态不允许此操作"
    status_code = 409


class CourseGrantRequired(CoreError):
    code = "COURSE_GRANT_REQUIRED"
    message = "没有该课程所需权限"
    status_code = 403


class EnrollmentStateConflict(CoreError):
    code = "ENROLLMENT_STATE_CONFLICT"
    message = "选课当前状态不允许此操作"
    status_code = 409


class EnrollmentCapacityFull(CoreError):
    code = "ENROLLMENT_CAPACITY_FULL"
    message = "课程名额已满"
    status_code = 409


class EnrollmentAlreadyLive(CoreError):
    code = "ENROLLMENT_ALREADY_LIVE"
    message = "已经存在待处理或有效的选课周期"
    status_code = 409


class EnrollmentBlocked(CoreError):
    code = "ENROLLMENT_BLOCKED"
    message = "选课退出或移除受到阻断"
    status_code = 409


class OwnerTransferRequired(CoreError):
    code = "OWNER_TRANSFER_REQUIRED"
    message = "负责人必须先完成课程交接"
    status_code = 409


class FeatureNotAvailable(CoreError):
    code = "FEATURE_NOT_AVAILABLE"
    message = "该治理能力尚未开放"
    status_code = 501


class PrerequisiteNotSatisfied(CoreError):
    code = "PREREQUISITE_NOT_SATISFIED"
    message = "课程先修条件尚未满足"
    status_code = 409


class CrossCourseReference(CoreError):
    code = "CROSS_COURSE_REFERENCE"
    message = "不能引用其他课程的对象"
    status_code = 404


class InvitationInvalid(CoreError):
    code = "COURSE_INVITATION_INVALID"
    message = "邀请码无效或已失效"
    status_code = 400


class ContentStateConflict(CoreError):
    code = "CONTENT_STATE_CONFLICT"
    message = "内容当前状态不允许此操作"
    status_code = 409


class MaterialAssetNotClean(CoreError):
    code = "MATERIAL_ASSET_NOT_CLEAN"
    message = "资料文件尚未通过安全扫描"
    status_code = 409


class PrerequisiteCycle(CoreError):
    code = "PREREQUISITE_CYCLE"
    message = "先修关系不能形成环路"
    status_code = 422


class ActiveEnrollmentRequired(CoreError):
    code = "ACTIVE_ENROLLMENT_REQUIRED"
    message = "需要有效选课才能访问课程互动内容"
    status_code = 403
