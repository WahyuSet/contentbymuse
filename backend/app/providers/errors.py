class ProviderError(Exception):
    """Basis error provider (Spec §5.5): selalu membawa pesan Indonesia dan detail vendor."""

    retryable: bool = False
    default_message_id = "Provider gagal melayani permintaan."

    def __init__(self, message_id: str | None = None, detail: str | None = None):
        self.message_id = message_id or self.default_message_id
        self.detail = (detail or "")[:500] or None
        super().__init__(self.message_id)


class AuthError(ProviderError):
    retryable = False
    default_message_id = "Kunci API provider ditolak. Periksa pengaturan provider."


class RateLimitError(ProviderError):
    retryable = True
    default_message_id = "Provider membatasi laju permintaan. Coba lagi sebentar."

    def __init__(self, message_id=None, detail=None, retry_after: float | None = None):
        super().__init__(message_id, detail)
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    default_message_id = "Provider terlalu lama menjawab."

    def __init__(self, message_id=None, detail=None, retryable: bool = True):
        super().__init__(message_id, detail)
        self.retryable = retryable


class ContentPolicyError(ProviderError):
    retryable = False
    default_message_id = "Konten ditolak oleh kebijakan provider."


class BadRequestError(ProviderError):
    retryable = False
    default_message_id = "Permintaan ke provider tidak valid."


class ServerError(ProviderError):
    retryable = True
    default_message_id = "Provider sedang bermasalah. Coba lagi nanti."


class MalformedOutputError(ProviderError):
    retryable = True
    default_message_id = "Jawaban provider tidak sesuai format yang diharapkan."
