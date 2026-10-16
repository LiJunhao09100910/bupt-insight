class InsightError(Exception):
    """Safe, fixed diagnostic text only: never pass a raw network exception."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def safe_error(exc):
    if isinstance(exc, InsightError):
        return exc.status, str(exc)
    return "failed", f"操作失败（{type(exc).__name__}）；未记录可能含凭据的原始异常"
