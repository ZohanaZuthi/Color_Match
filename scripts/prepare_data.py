"""Fetch the original NTU files and build a traceable measured lookup catalog.

No pigment names are guessed. Spectral identities can be connected across
quantities when a measured increment output exactly matches an input spectrum.
"""

import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.request

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.colors import spectrum_lab, hex_color

BASE = "https://arxiv.org/src/1904.00275v1/anc/NTU_WPSM_dataset/"
EXPECTED_SHA256 = {
    "MQ_train_1956_X_ok.csv": "abe5c366e2cf3a24cc823add446dd7d529cc1d15d4b3bf36e0bc4ecc037ac7e4",
    "MQ_train_1956_Y_ok.csv": "a0e5f49864c01d953056d9e74afb51004d6739205c2946812738668e2c4dcc98",
    "MQ_test_488_X_ok.csv": "5bfaacf8ccf3d37057d3dd951bb3fb0fc57b713c63f02cbb8d5b158084a67bb6",
    "MQ_test_488_Y_ok.csv": "3119ebf145a03f3d0f90aac570055156575395e3f45cf38804cb081fb434e675",
}


def fingerprint(spectrum):
    return hashlib.sha256(np.round(spectrum, 8).astype("<f8").tobytes()).hexdigest()[
        :16
    ]


def main():
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    hashes, records = {}, []
    for split, size in [("train", 1956), ("test", 488)]:
        arrays = []
        for suffix, width in [("X", 207), ("Y", 41)]:
            name = f"MQ_{split}_{size}_{suffix}_ok.csv"
            path = raw / name
            if not path.exists():
                with urllib.request.urlopen(BASE + name, timeout=60) as response:
                    path.write_bytes(response.read())
            content = path.read_bytes()
            hashes[name] = hashlib.sha256(content).hexdigest()
            if hashes[name] != EXPECTED_SHA256[name]:
                raise ValueError(
                    f"{name}: source checksum changed; inspect before importing."
                )
            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
            values = np.array(rows[1:], dtype=float)
            assert values.shape == (size, width), (name, values.shape)
            assert np.isfinite(values).all(), name
            arrays.append(values)
        for index, (x, y) in enumerate(zip(*arrays)):
            assert np.all(x[-2:] > 0)
            # Columns interleave T_A, T_B, R_A, R_B, paper at each wavelength.
            blocks = x[:205].reshape(41, 5)
            records.append(
                {
                    "a": blocks[:, 2],
                    "b": blocks[:, 3],
                    "out": y,
                    "qa": float(x[-2]),
                    "qb": float(x[-1]),
                    "source": f"{split}:{index + 2}",
                }
            )

    spectra, parents = {}, {}
    for r in records:
        for side in ("a", "b"):
            key = fingerprint(r[side])
            spectra[key] = r[side]
            parents[key] = key

    def find(x):
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    for r in records:
        key = fingerprint(r["out"])
        if key in parents:
            # An exact primary-spectrum match identifies an increment relation.
            a, b = fingerprint(r["a"]), fingerprint(r["b"])
            parents[find(a)] = find(key)
            parents[find(b)] = find(key)

    groups = {}
    for key in parents:
        groups.setdefault(find(key), []).append(key)
    # Preserve deterministic identity across runs, independent of union order.
    identity = {key: "ntu-" + min(keys) for keys in groups.values() for key in keys}
    paints = []
    for index, keys in enumerate(sorted(groups.values(), key=min), 1):
        labs = [spectrum_lab(spectra[key]) for key in keys]
        representative = sorted(labs, key=lambda x: x[0])[len(labs) // 2]
        paints.append(
            {
                "id": "ntu-" + min(keys),
                "name": f"Study paint {index:02}",
                "hex": hex_color(representative),
                "identity_status": "unverified_name",
                "spectral_samples": len(keys),
            }
        )

    catalog = {}
    for r in records:
        a, b = identity[fingerprint(r["a"])], identity[fingerprint(r["b"])]
        amounts = {}
        for pid, amount in [(a, r["qa"]), (b, r["qb"])]:
            amounts[pid] = round(amounts.get(pid, 0) + amount, 8)
        ingredients = sorted(amounts.items())
        signature = json.dumps([ingredients, fingerprint(r["out"])])
        rid = hashlib.sha256(signature.encode()).hexdigest()[:16]
        if rid in catalog:
            catalog[rid]["sources"].append(r["source"])
            continue
        lab = spectrum_lab(r["out"])
        total = sum(amounts.values())
        catalog[rid] = {
            "id": rid,
            "ingredients": [
                {"paint_id": pid, "quantity_ml": q, "fraction": q / total}
                for pid, q in ingredients
            ],
            "total_quantity_ml": total,
            "lab": lab.tolist(),
            "hex": hex_color(lab),
            "reflectance": r["out"].tolist(),
            "sources": [r["source"]],
            "evidence": "measured",
        }
    payload = {
        "version": "ntu-wpsm-measured-v1",
        "source": "https://arxiv.org/abs/1904.00275",
        "identity_status": "unverified_name",
        "paints": paints,
        "recipes": list(catalog.values()),
    }
    (ROOT / "data" / "catalog.json").write_text(json.dumps(payload), encoding="utf-8")
    audit = {
        "source_sha256": hashes,
        "input_rows": len(records),
        "recipes": len(catalog),
        "spectral_components": len(spectra),
        "identity_groups": len(groups),
        "group_sizes": sorted(map(len, groups.values())),
        "name_mapping": "Not supplied in CSVs. Generic study IDs only.",
        "grouping": "Exact rounded 41-band reflectance equality via increment outputs.",
        "training": "None. Train and test files form a retrieval catalog; no held-out accuracy claim.",
    }
    (ROOT / "data" / "audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
