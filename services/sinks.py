from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Synthetic fake sinks")


class Delivery(BaseModel):
    destination: str = Field(max_length=100)
    body: object
    tags: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest")
def ingest(body: Delivery):
    return {
        "received": True,
        "synthetic": True,
        "destination_label": body.destination,
        "bytes": len(str(body.body)),
        "tags": body.tags,
        "network": "Only the internal fake sink received this data",
    }
