import os
import tempfile
import logging

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from markitdown import MarkItDown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("markitdown-service")

app = FastAPI(title="MarkItDown Service")
md_converter = MarkItDown()

PORT = int(os.environ.get("MARKITDOWN_PORT", "8000"))


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    suffix = ""
    if file.filename:
        _, suffix = os.path.splitext(file.filename)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.flush()
        tmp.close()

        logger.info("Converting file: %s (%d bytes)", file.filename, len(content))
        result = md_converter.convert(tmp.name)

        return JSONResponse(
            content={
                "markdown": result.text_content,
                "page_count": None,
            }
        )
    except Exception as e:
        logger.error("Conversion failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )
    finally:
        os.unlink(tmp.name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
