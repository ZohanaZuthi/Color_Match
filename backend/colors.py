"""All matching uses CIELAB, D65 / CIE 1931 2 degree, never averaged RGB."""

import colour
import numpy as np

SHAPE = colour.SpectralShape(380, 780, 10)
CMFS = colour.MSDS_CMFS["CIE 1931 2 Degree Standard Observer"].copy().align(SHAPE)
ILLUMINANT = colour.SDS_ILLUMINANTS["D65"].copy().align(SHAPE)
WHITE = colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"]["D65"]


def spectrum_lab(values):
    sd = colour.SpectralDistribution(dict(zip(range(380, 781, 10), values)))
    xyz = colour.sd_to_XYZ(sd, CMFS, ILLUMINANT, method="Integration") / 100
    return colour.XYZ_to_Lab(xyz, WHITE)


def rgb_lab(rgb):
    return colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.asarray(rgb) / 255), WHITE)


def lab_rgb(lab):
    rgb = colour.XYZ_to_sRGB(colour.Lab_to_XYZ(np.asarray(lab), WHITE))
    return np.rint(np.clip(rgb, 0, 1) * 255).astype(int)


def hex_color(lab):
    return "#" + "".join(f"{v:02x}" for v in lab_rgb(lab))


def difference(lab, candidates):
    return colour.delta_E(np.asarray(lab), np.asarray(candidates), method="CIE 2000")


def primary_proportions(rgb_pixels):
    """Approximate RYB + white tint coordinates, not physical paint amounts.

    Retain min(sRGB)/255 as a white-tint fraction, then distribute the rest
    using the existing RYB hue heuristic. This is a display-space convention,
    not a measured white-pigment or water quantity. Darkness is not modeled.
    Near-white neutrals map to white; other neutrals have no supported recipe.
    Not fitted to NTU data.
    """
    pixels = np.asarray(rgb_pixels).reshape(-1, 3)
    pixels = pixels[:: max(1, int(np.ceil(len(pixels) / 12000)))]
    lab = rgb_lab(pixels).mean(axis=0)
    rgb = lab_rgb(lab).astype(float)
    metadata = {"hex": hex_color(lab), "method": "approximate_rybw"}
    if float(np.hypot(lab[1], lab[2])) < 4 or float(rgb.max() - rgb.min()) < 5:
        if rgb.min() >= 250:
            return {
                **metadata,
                "percentages": {"red": 0, "yellow": 0, "blue": 0, "white": 100},
                "message": None,
            }
        return {
            **metadata,
            "percentages": None,
            "message": "This gray or black shade cannot be estimated reliably by this simple palette.",
        }
    white = float(rgb.min()) / 255
    red, green, blue = rgb - rgb.min()
    yellow = min(red, green)
    red -= yellow
    green -= yellow
    if blue > 0 and green > 0:
        blue /= 2
        green /= 2
    yellow += green
    blue += green
    weights = np.array([red, yellow, blue])
    percentages = np.append(weights / weights.sum() * (1 - white), white) * 100
    whole = np.floor(percentages).astype(int)
    for index in np.argsort(-(percentages - whole), kind="stable")[
        : 100 - int(whole.sum())
    ]:
        whole[index] += 1
    return {
        **metadata,
        "percentages": dict(zip(("red", "yellow", "blue", "white"), whole.tolist())),
        "message": (
            "Hue and white tint only; this estimate does not reproduce the selected shade's darkness."
            if rgb.max() < 245
            else None
        ),
    }


def palette(rgb_pixels, count=5):
    """Deterministic Lab clustering; final representatives are actual pixels."""
    pixels = np.asarray(rgb_pixels).reshape(-1, 3)
    pixels = pixels[:: max(1, int(np.ceil(len(pixels) / 12000)))]
    labs = rgb_lab(pixels)
    centers = [labs[np.argmin(np.sum((labs - labs.mean(axis=0)) ** 2, axis=1))]]
    for _ in range(count - 1):
        distances = np.min(
            np.sum((labs[:, None] - np.array(centers)) ** 2, axis=2), axis=1
        )
        if distances.max() < 9:
            break
        centers.append(labs[np.argmax(distances)])
    centers = np.array(centers)
    for _ in range(25):
        labels = np.argmin(np.sum((labs[:, None] - centers) ** 2, axis=2), axis=1)
        updated = np.array(
            [
                labs[labels == i].mean(axis=0) if np.any(labels == i) else c
                for i, c in enumerate(centers)
            ]
        )
        if np.allclose(updated, centers, atol=0.02):
            centers = updated
            break
        centers = updated
    # Merge perceptually similar groups, then recompute memberships.
    merged = []
    for c in centers:
        if not merged or np.min(difference(c, merged)) >= 3:
            merged.append(c)
    centers = np.array(merged)
    labels = np.argmin(np.sum((labs[:, None] - centers) ** 2, axis=2), axis=1)
    result = []
    for i, c in enumerate(centers):
        members = labs[labels == i]
        if not len(members):
            continue
        representative = members[np.argmin(np.sum((members - c) ** 2, axis=1))]
        result.append(
            {
                "lab": representative.tolist(),
                "hex": hex_color(representative),
                "coverage": round(100 * len(members) / len(labs), 2),
            }
        )
    return sorted(result, key=lambda x: -x["coverage"])
