import io
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid
import warnings

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .colors import difference, palette, primary_proportions

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("WATERCOLOR_DATA_DIR", ROOT / "data" / "runtime"))
DATA.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = 15 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
app = FastAPI(title="Watercolor Study", version="0.1.0")
CATALOG_PATH = ROOT / "data" / "catalog.json"
CATALOG = json.loads(CATALOG_PATH.read_text()) if CATALOG_PATH.exists() else None


def catalog():
    if CATALOG is None:
        raise HTTPException(
            503, "Dataset is not prepared. Run scripts/prepare_data.py first."
        )
    return CATALOG


@contextmanager
def database():
    con = sqlite3.connect(DATA / "recipes.sqlite3")
    try:
        with con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS saved (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            yield con
    finally:
        con.close()


def image_path(image_id):
    if not re.fullmatch(r"[a-f0-9]{32}", image_id):
        raise HTTPException(404, "Image not found.")
    path = DATA / f"{image_id}.png"
    if not path.exists():
        raise HTTPException(404, "Image not found.")
    return path


class Region(BaseModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)


class MatchRequest(BaseModel):
    lab: list[float] = Field(min_length=3, max_length=3)
    paint_ids: list[str] | None = Field(default=None, max_length=200)
    limit: int = Field(default=3, ge=1, le=10)

    @field_validator("lab")
    @classmethod
    def valid_lab(cls, values):
        if (
            not all(math.isfinite(v) for v in values)
            or not 0 <= values[0] <= 100
            or any(abs(v) > 160 for v in values[1:])
        ):
            raise ValueError("Expected finite CIELAB coordinates.")
        return values


class SaveRequest(MatchRequest):
    image_id: str
    region: Region
    recipe_id: str


@app.get("/api/health")
def health():
    return {"status": "ok", "research_catalog_ready": CATALOG is not None}


@app.get("/api/catalog")
def get_catalog():
    c = catalog()
    return {k: v for k, v in c.items() if k != "recipes"} | {
        "recipe_count": len(c["recipes"])
    }


def normalize_image(content):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(415, "Use a JPEG, PNG, or WebP image.")
                source.load()
                image = ImageOps.exif_transpose(source)
                icc = image.info.get("icc_profile")
                alpha = (
                    image.getchannel("A")
                    if "A" in image.getbands()
                    else (
                        image.convert("RGBA").getchannel("A")
                        if "transparency" in image.info
                        else None
                    )
                )
                if icc:
                    profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    image = ImageCms.profileToProfile(
                        image.convert("RGB") if alpha is not None else image,
                        profile,
                        ImageCms.createProfile("sRGB"),
                        outputMode="RGB",
                    )
                else:
                    image = image.convert("RGB")
                if alpha is not None:
                    paper = Image.new("RGB", image.size, "white")
                    paper.paste(image, mask=alpha)
                    image = paper
                # Keep the normalized photo's full resolution for zoomed sampling.
                image_id = uuid.uuid4().hex
                image.save(DATA / f"{image_id}.png")
                return {
                    "id": image_id,
                    "url": f"/api/images/{image_id}",
                    "width": image.width,
                    "height": image.height,
                    "color_profile": "Converted to sRGB" if icc else "Assumed sRGB",
                }
    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        ImageCms.PyCMSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(
            422, "Image could not be read. Use a valid image up to 20 megapixels."
        )


@app.post("/api/images")
async def upload_image(file: UploadFile):
    content = await file.read(MAX_UPLOAD + 1)
    await file.close()
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "Choose an image smaller than 15 MB.")
    return await run_in_threadpool(normalize_image, content)


@app.get("/api/images/{image_id}")
def get_image(image_id: str):
    return FileResponse(image_path(image_id), media_type="image/png")


def selected_pixels(image_id: str, region: Region):
    if region.x + region.width > 1.000001 or region.y + region.height > 1.000001:
        raise HTTPException(422, "Selection must stay inside the image.")
    with Image.open(image_path(image_id)) as im:
        left = min(im.width - 1, int(region.x * im.width))
        top = min(im.height - 1, int(region.y * im.height))
        right = min(
            im.width, max(left + 1, math.ceil((region.x + region.width) * im.width))
        )
        bottom = min(
            im.height, max(top + 1, math.ceil((region.y + region.height) * im.height))
        )
        crop = im.crop((left, top, right, bottom))
        crop.thumbnail((400, 400))
        return np.asarray(crop.convert("RGB")), (right - left) * (bottom - top)


@app.post("/api/images/{image_id}/primary")
def analyze_primary(image_id: str, region: Region):
    pixels, _ = selected_pixels(image_id, region)
    return primary_proportions(pixels)


@app.post("/api/images/{image_id}/selections")
def analyze_selection(image_id: str, region: Region):
    pixels, area = selected_pixels(image_id, region)
    colors = palette(pixels)
    return {
        "colors": colors,
        "region": region.model_dump(),
        "pixel_area": area,
    }


def present_recipe(recipe, lab, paints):
    error = float(difference(lab, recipe["lab"]))
    return {k: v for k, v in recipe.items() if k != "reflectance"} | {
        "ingredients": [
            ingredient | {"paint": paints[ingredient["paint_id"]]}
            for ingredient in recipe["ingredients"]
        ],
        "delta_e": round(error, 2),
        "identity_status": "unverified_name",
        "match_label": "Closest catalog match"
        if error <= 5
        else "Approximate catalog match"
        if error <= 10
        else "Limited match",
        "ratio_basis": "volume",
        "paper": "Canson Ca grain (study conditions)",
        "reference_area_cm2": 2.25,
    }


@app.post("/api/matches")
def matches(request: MatchRequest):
    c = catalog()
    paints = {p["id"]: p for p in c["paints"]}
    allowed = set(paints) if request.paint_ids is None else set(request.paint_ids)
    if not allowed.issubset(paints):
        raise HTTPException(422, "Unknown study paint selected.")
    eligible = [
        r
        for r in c["recipes"]
        if all(i["paint_id"] in allowed for i in r["ingredients"])
    ]
    if not eligible:
        return {
            "recipes": [],
            "message": "No measured recipes use this selection of paints.",
        }
    errors = difference(request.lab, [r["lab"] for r in eligible])
    selected, seen = [], set()
    for index in np.argsort(errors):
        recipe = eligible[int(index)]
        signature = tuple(
            (i["paint_id"], round(i["fraction"], 6)) for i in recipe["ingredients"]
        )
        if signature in seen:
            continue
        seen.add(signature)
        selected.append(present_recipe(recipe, request.lab, paints))
        if len(selected) >= request.limit:
            break
    return {"recipes": selected, "catalog_version": c["version"], "message": None}


@app.post("/api/saved-recipes")
def save_recipe(request: SaveRequest):
    image_path(request.image_id)
    c = catalog()
    recipe = next((r for r in c["recipes"] if r["id"] == request.recipe_id), None)
    if recipe is None:
        raise HTTPException(404, "Recipe not found.")
    if (
        request.region.x + request.region.width > 1.000001
        or request.region.y + request.region.height > 1.000001
    ):
        raise HTTPException(422, "Selection must stay inside the image.")
    paints = {p["id"]: p for p in c["paints"]}
    result = {
        "id": uuid.uuid4().hex,
        "image_id": request.image_id,
        "region": request.region.model_dump(),
        "target_lab": request.lab,
        "recipe": present_recipe(recipe, request.lab, paints),
        "catalog_version": c["version"],
    }
    with database() as con:
        con.execute(
            "INSERT INTO saved VALUES (?, ?)", (result["id"], json.dumps(result))
        )
    return result


@app.get("/api/saved-recipes")
def list_saved():
    with database() as con:
        rows = con.execute(
            "SELECT payload FROM saved ORDER BY rowid DESC LIMIT 100"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
