"""Neutralise line breaks in values interpolated into log messages."""


def log_safe(value: object) -> str:
    # Backend logs are plain text, so a raw newline forges extra log lines;
    # CodeQL only recognises a literal "\n"/"\r\n" replace as the sanitiser.
    return (
        str(value)
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
