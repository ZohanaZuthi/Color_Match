import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import main
from backend.colors import difference, rgb_lab, lab_rgb, spectrum_lab
from backend.colors import primary_proportions


@pytest.mark.parametrize(
    "rgb,expected",
    [
        ([255, 0, 0], {"red": 100, "yellow": 0, "blue": 0}),
        ([255, 255, 0], {"red": 0, "yellow": 100, "blue": 0}),
        ([0, 0, 255], {"red": 0, "yellow": 0, "blue": 100}),
        ([0, 255, 0], {"red": 0, "yellow": 50, "blue": 50}),
        ([255, 128, 0], {"red": 50, "yellow": 50, "blue": 0}),
    ],
)
def test_primary_hue_proportions(rgb, expected):
    result = primary_proportions(np.array([rgb]))
    assert result["percentages"] == {**expected, "white": 0}
    assert result["method"] == "approximate_rybw"
    assert result["message"] is None


@pytest.mark.parametrize(
    "rgb,expected",
    [
        ([255, 128, 128], {"red": 50, "yellow": 0, "blue": 0, "white": 50}),
        ([128, 128, 255], {"red": 0, "yellow": 0, "blue": 50, "white": 50}),
        ([255, 255, 128], {"red": 0, "yellow": 50, "blue": 0, "white": 50}),
        ([128, 255, 128], {"red": 0, "yellow": 25, "blue": 25, "white": 50}),
        ([255, 255, 255], {"red": 0, "yellow": 0, "blue": 0, "white": 100}),
        ([252, 252, 252], {"red": 0, "yellow": 0, "blue": 0, "white": 100}),
    ],
)
def test_white_tint_proportions(rgb, expected):
    result = primary_proportions(np.array([rgb]))
    assert result["percentages"] == expected
    assert result["message"] is None


def test_lighter_tints_increase_white():
    results = [
        primary_proportions(np.array([[255, tint, tint]]))["percentages"]
        for tint in [0, 64, 128, 192, 255]
    ]
    assert [r["white"] for r in results] == [0, 25, 50, 75, 100]
    assert [r["red"] for r in results] == [100, 75, 50, 25, 0]


def test_percentages_are_bounded_and_sum_to_100():
    for rgb in np.random.default_rng(42).integers(0, 256, size=(150, 3)):
        result = primary_proportions(np.array([rgb]))
        if result["percentages"] is not None:
            amounts = result["percentages"]
            assert set(amounts) == {"red", "yellow", "blue", "white"}
            assert all(isinstance(v, int) and 0 <= v <= 100 for v in amounts.values())
            assert sum(amounts.values()) == 100


def test_dark_chromatic_colors_have_a_limitation_warning():
    result = primary_proportions(np.array([[100, 30, 30]]))
    assert result["percentages"] is not None
    assert "darkness" in result["message"]


def test_neutral_selection_has_no_fabricated_recipe():
    for gray in [0, 128, 220, 249]:
        assert (
            primary_proportions(np.array([[gray, gray, gray]]))["percentages"] is None
        )


def test_upload_preserves_detail_for_zoom(client):
    image = upload(client, Image.new("RGB", (3000, 20), "red"))
    assert image["width"] == 3000
    assert image["height"] == 20


def test_primary_endpoint_reads_only_selected_area(client):
    image = upload(client)
    r = client.post(
        f"/api/images/{image['id']}/primary",
        json={"x": 0.6, "y": 0.1, "width": 0.3, "height": 0.7},
    )
    assert r.status_code == 200
    assert r.json()["percentages"] == {"red": 0, "yellow": 0, "blue": 100, "white": 0}
    assert sum(r.json()["percentages"].values()) == 100


@pytest.mark.parametrize(
    "color,expected",
    [
        ("#ff8080", {"red": 50, "yellow": 0, "blue": 0, "white": 50}),
        ("white", {"red": 0, "yellow": 0, "blue": 0, "white": 100}),
        ("gray", None),
    ],
)
def test_primary_endpoint_white_tint_and_neutral_regions(client, color, expected):
    photo = Image.new("RGB", (100, 100), "blue")
    photo.paste(color, (50, 0, 100, 100))
    image = upload(client, photo)
    response = client.post(
        f"/api/images/{image['id']}/primary",
        json={"x": 0.5, "y": 0, "width": 0.5, "height": 1},
    )
    assert response.status_code == 200
    assert response.json()["percentages"] == expected
    assert response.json()["method"] == "approximate_rybw"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA", tmp_path)
    with TestClient(main.app) as client:
        yield client


def upload(client, image=None):
    if image is None:
        image = Image.new("RGB", (100, 100), "#ff0000")
        image.paste("#0000ff", (50, 0, 100, 100))
    data = io.BytesIO()
    image.save(data, format="PNG")
    response = client.post(
        "/api/images", files={"file": ("sample.png", data.getvalue(), "image/png")}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ciede2000_reference_and_color_conversions():
    # Sharma et al. reference pair: distinguishes CIEDE2000 from Euclidean Lab.
    assert float(
        difference([50, 2.6772, -79.7751], [50, 0, -82.7485])
    ) == pytest.approx(2.0425, abs=0.0001)
    # Finite 380–780 nm / 10 nm integration differs slightly from full D65 xy.
    assert np.allclose(spectrum_lab(np.ones(41)), [100, 0, 0], atol=0.1)
    rgb = np.array([[0, 0, 0], [255, 255, 255], [20, 80, 170]])
    assert np.max(np.abs(lab_rgb(rgb_lab(rgb)) - rgb)) <= 1


def test_real_catalog_is_traceable_and_ratio_constrained():
    c = main.catalog()
    assert len(c["paints"]) == 13
    assert all(p["identity_status"] == "unverified_name" for p in c["paints"])
    binary_count = 0
    for r in c["recipes"]:
        assert r["evidence"] == "measured" and r["sources"]
        assert len(r["reflectance"]) == 41
        assert sum(i["fraction"] for i in r["ingredients"]) == pytest.approx(1)
        if len(r["ingredients"]) == 2:
            binary_count += 1
            assert (
                r["ingredients"][0]["fraction"] == pytest.approx(0.5)
                or r["ingredients"][0]["fraction"] == pytest.approx(1 / 3)
                or r["ingredients"][0]["fraction"] == pytest.approx(2 / 3)
            )
    assert binary_count == 780


def test_upload_region_match_and_persistent_save(client):
    image = upload(client)
    region = {"x": 0, "y": 0, "width": 0.5, "height": 1}
    result = client.post(f"/api/images/{image['id']}/selections", json=region)
    assert result.status_code == 200
    colors = result.json()["colors"]
    assert len(colors) == 1 and colors[0]["hex"] == "#ff0000"
    assert colors[0]["coverage"] == 100
    match = client.post("/api/matches", json={"lab": colors[0]["lab"]}).json()[
        "recipes"
    ][0]
    saved = client.post(
        "/api/saved-recipes",
        json={
            "image_id": image["id"],
            "region": region,
            "lab": colors[0]["lab"],
            "recipe_id": match["id"],
        },
    )
    assert saved.status_code == 200
    assert client.get("/api/saved-recipes").json()[0]["recipe"]["id"] == match["id"]
    assert client.get(image["url"]).headers["content-type"] == "image/png"


def test_exact_retrieval_filter_and_empty_palette(client):
    measured = next(r for r in main.catalog()["recipes"] if len(r["ingredients"]) == 2)
    ids = [i["paint_id"] for i in measured["ingredients"]]
    result = client.post(
        "/api/matches", json={"lab": measured["lab"], "paint_ids": ids}
    ).json()
    assert result["recipes"][0]["delta_e"] == 0
    assert result["recipes"][0]["id"] == measured["id"]
    assert all(
        i["paint_id"] in ids for r in result["recipes"] for i in r["ingredients"]
    )
    assert (
        client.post(
            "/api/matches", json={"lab": measured["lab"], "paint_ids": []}
        ).json()["recipes"]
        == []
    )
    assert (
        client.post(
            "/api/matches", json={"lab": measured["lab"], "paint_ids": ["fake"]}
        ).status_code
        == 422
    )


def test_multi_color_coverage_is_area_not_mixing_ratio(client):
    image = upload(client)
    result = client.post(
        f"/api/images/{image['id']}/selections",
        json={"x": 0, "y": 0, "width": 1, "height": 1},
    ).json()
    assert {c["hex"] for c in result["colors"]} == {"#ff0000", "#0000ff"}
    assert all(c["coverage"] == pytest.approx(50) for c in result["colors"])


def test_orientation_and_transparency(client):
    image = Image.new("RGB", (80, 40), "red")
    exif = image.getexif()
    exif[274] = 6
    content = io.BytesIO()
    image.save(content, format="JPEG", exif=exif)
    response = client.post(
        "/api/images", files={"file": ("rotated.jpg", content.getvalue())}
    )
    assert response.json()["width"] == 40 and response.json()["height"] == 80
    transparent = upload(client, Image.new("RGBA", (20, 20), (0, 0, 0, 0)))
    response = client.post(
        f"/api/images/{transparent['id']}/selections",
        json={"x": 0, "y": 0, "width": 1, "height": 1},
    )
    assert response.json()["colors"][0]["hex"] == "#ffffff"


def test_invalid_inputs_and_missing_dataset(client, monkeypatch):
    assert (
        client.post(
            "/api/images", files={"file": ("bad.png", b"not an image")}
        ).status_code
        == 422
    )
    image = upload(client)
    assert (
        client.post(
            f"/api/images/{image['id']}/selections",
            json={"x": 0.9, "y": 0, "width": 0.5, "height": 1},
        ).status_code
        == 422
    )
    assert client.post("/api/matches", json={"lab": [200, 0, 0]}).status_code == 422
    assert client.get("/api/images/unknown").status_code == 404
    monkeypatch.setattr(main, "CATALOG", None)
    assert client.get("/api/catalog").status_code == 503
