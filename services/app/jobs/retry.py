from procrastinate import RetryDecision, RetryStrategy


class CatalogRetry(RuntimeError):
    def __init__(self, retry_after=None):
        super().__init__("Retryable secondary catalog lookup failure")
        self.retry_after = min(max(retry_after or 60, 60), 7 * 86400)


class CatalogRetryStrategy(RetryStrategy):
    def get_retry_decision(self, *, exception, job):
        decision = super().get_retry_decision(exception=exception, job=job)
        if decision and isinstance(exception, CatalogRetry):
            return RetryDecision(retry_in={"seconds": exception.retry_after})
        return decision


class SourceSearchRetry(RuntimeError):
    def __init__(self, seconds):
        super().__init__("Source search is waiting for its rate budget")
        self.retry_after = min(max(int(seconds), 1), 7 * 86400)


class SourceSearchRetryStrategy(RetryStrategy):
    def get_retry_decision(self, *, exception, job):
        decision = super().get_retry_decision(exception=exception, job=job)
        if decision and isinstance(exception, SourceSearchRetry):
            return RetryDecision(retry_in={"seconds": exception.retry_after})
        return decision
