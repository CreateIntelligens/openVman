import os
import io
import time
import logging
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vibevoice-serve")

app = FastAPI(title="VibeVoice Serve")

# Placeholder for the actual VibeVoice models
# In a real deployment, these would be loaded from the cloned repo
# and would require the actual VibeVoice classes.
class VibeVoiceModel:
    def __init__(self, model_name: str):
        self.model_name = model_name
        logger.info(f"Initialized VibeVoice model: {model_name}")

    def synthesize(self, text: str, reference_audio: Optional[bytes] = None):
        logger.info(f"Synthesizing text with {self.model_name}: {text[:50]}...")
        # Mocking synthesis - this is where the actual VibeVoice call would go
        time.sleep(0.3 if "0.5b" in self.model_name else 1.0)
        return b"MOCK_AUDIO_DATA"

# Lazy-loaded models
models = {
    "0.5b": None,
    "1.5b": None
}

def get_model(model_name: str):
    if model_name not in models:
        raise HTTPException(status_code=400, detail=f"Model {model_name} not supported")
    if models[model_name] is None:
        models[model_name] = VibeVoiceModel(model_name)
    return models[model_name]

class SynthesizeRequest(BaseModel):
    text: str
    model: Optional[str] = "0.5b"
    reference_id: Optional[str] = None
    streaming: Optional[bool] = False

@app.get("/health")
async def health():
    return {"status": "ok", "models": list(models.keys())}

@app.post("/tts")
async def synthesize(req: SynthesizeRequest):
    try:
        model = get_model(req.model)
        
        # Reference audio handling
        ref_audio = None
        if req.reference_id:
            ref_path = f"app/assets/tts_references/{req.reference_id}"
            if not ref_path.endswith(".wav"):
                ref_path += ".wav"
            
            if os.path.exists(ref_path):
                with open(ref_path, "rb") as f:
                    ref_audio = f.read()
            else:
                logger.warning(f"Reference audio not found: {ref_path}")

        audio_data = model.synthesize(req.text, ref_audio)
        
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/mpeg"
        )
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
